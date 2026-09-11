"""Exercise every published JLPT type through the running API, then remove only this run's test-account data."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.database import ROOT, SessionLocal
from app.models import Occurrence, Option, Practice, PracticeItem, Token, User, WrongQuestion


def verify(base_url, output, provision_internal=False):
    token = None

    def request(path, data=None, extra_headers=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        headers.update(extra_headers or {})
        with urlopen(Request(base_url+path, data=json.dumps(data).encode() if data is not None else None,
                             headers=headers), timeout=30) as response:
            return json.load(response)

    assert request('/api/v1/health')['status'] == 'ok'
    username = 'verify_' + uuid4().hex
    credentials = {'username': username, 'password': uuid4().hex}
    if provision_internal:
        from app.auth import hash_password
        with SessionLocal.begin() as db:
            db.add(User(username=username, password_hash=hash_password(credentials['password'])))
        auth = request('/api/v1/auth/login', credentials)
    else:
        auth = request('/api/v1/auth/register', credentials)
    token = auth['access_token']
    guest_id = auth['user']['id']
    checked = []
    media_checked = False
    try:
        with SessionLocal() as db:
            guest = db.get(User, guest_id)
            assert guest is not None and guest.username == username
            levels = request('/api/v1/catalog/levels')['items']
            for level in levels:
                assert level['question_count'] == db.scalar(select(func.count()).select_from(Occurrence).where(
                    Occurrence.level == level['level'], Occurrence.status == 'ready'))
                for qt in request('/api/v1/catalog/types?level='+level['level'])['items']:
                    payload=dict(level=level['level'],type_id=qt['id'],count=2,request_key=uuid4().hex)
                    practice=request('/api/v1/practices',payload)
                    assert request('/api/v1/practices',payload)['id']==practice['id']
                    selected={i['question']['occurrence_id'] for i in practice['items']}
                    for item in practice['items']:
                        assert item['feedback'] is None
                        assert not {'correct_option_id','explanation','translation','subtitles'} & item['question'].keys()
                        occurrence=db.get(Occurrence,item['question']['occurrence_id'])
                        assert occurrence.status=='ready'
                        expected=set(db.scalars(select(Occurrence.id).where(Occurrence.group_key==occurrence.group_key,Occurrence.status=='ready')))
                        assert expected <= selected
                        audio=item['question']['material']['audio_url']
                        if audio:
                            listening = request(f'/api/v1/practices/{practice["id"]}/items/{item["id"]}/listening')
                            assert listening['audio_url'] == audio
                            assert all(s['end_ms'] > s['start_ms'] >= 0 for s in listening['segments'])
                            assert 'correct_option_id' not in listening
                        if audio and not media_checked:
                            with urlopen(Request(base_url+audio,headers={'Range':'bytes=0-15'}),timeout=30) as response:
                                assert response.status==206 and len(response.read())==16
                            media_checked=True
                    item=practice['items'][0]
                    chosen=item['question']['options'][0]['id']
                    result=request(f'/api/v1/practices/{practice["id"]}/items/{item["id"]}/answer',dict(option_id=chosen,elapsed_ms=100))
                    expected=db.scalar(select(Option).where(Option.id==chosen)).correct
                    assert result['feedback']['is_correct']==expected
                    resumed=request('/api/v1/practices/'+practice['id'])
                    assert resumed['answered']==1
                    checked.append(dict(level=level['level'],type_id=qt['id'],available=qt['question_count'],sample_size=practice['total']))
        result=dict(status='passed',types_checked=len(checked),media_range_checked=media_checked,checks=checked)
        Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False))
    finally:
        # Scope cleanup to the freshly created test account, after confirming it belongs to this database.
        with SessionLocal() as db:
            guest=db.get(User,guest_id)
            if guest is not None and guest.username == username:
                ids=list(db.scalars(select(Practice.id).where(Practice.user_id==guest_id)))
                db.execute(delete(PracticeItem).where(PracticeItem.practice_id.in_(ids)))
                db.execute(delete(WrongQuestion).where(WrongQuestion.user_id==guest_id))
                db.execute(delete(Practice).where(Practice.user_id==guest_id))
                db.execute(delete(Token).where(Token.user_id==guest_id))
                db.delete(guest)
                db.commit()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8001')
    parser.add_argument('--output',default=ROOT/'docs/verification.json')
    parser.add_argument('--provision-internal', action='store_true', help='Create a disposable DB account when public registration is disabled')
    args=parser.parse_args()
    verify(args.base_url,args.output,args.provision_internal)
