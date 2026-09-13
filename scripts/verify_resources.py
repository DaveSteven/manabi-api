"""Verify deployed resource manifests and media using a disposable internal account.

Run in the API environment: python -m scripts.verify_resources --base-url https://biblenotes.cc
Only this script's temporary account/token are written and removed; no practice is created.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import delete, func, select
from app.auth import hash_password, issue_token
from app.database import SessionLocal
from app.models import Asset, Exam, Practice, Token, User


def verify(base_url):
    username = 'verify_resources_' + uuid4().hex
    with SessionLocal() as db:
        user = User(username=username, password_hash=hash_password(uuid4().hex))
        db.add(user)
        db.flush()
        uid = user.id
        token = issue_token(db, user)['access_token']
    try:
        def get(path, authorized=True):
            headers = {'Authorization': 'Bearer ' + token} if authorized else {}
            with urlopen(Request(base_url + path, headers=headers), timeout=30) as response:
                return json.load(response)

        with SessionLocal() as db:
            total = db.scalar(select(func.count()).select_from(Asset))
            unhashed = db.scalar(select(func.count()).select_from(Asset).where(Asset.content_hash.is_(None)))
            assert total > 0 and unhashed == 0
            exams = db.execute(select(Exam.id, Exam.level).where(Exam.published.is_(True)).order_by(Exam.id)).all()
        checked = 0
        samples = {}
        levels = set()
        for eid, level in exams:
            path = f'/api/v1/exam-practice/exams/{eid}/resources'
            manifest = get(path)
            items = manifest['items']
            assert manifest['exam_id'] == eid
            assert manifest['resource_count'] == len({a['id'] for a in items}) == len(items)
            assert manifest['total_bytes'] == sum(a['byte_size'] for a in items)
            for asset in items:
                assert len(asset['sha256']) == 64 and asset['byte_size'] > 0
                assert asset['url'].endswith('?v=' + asset['sha256'])
                samples.setdefault(asset['kind'], asset)
            checked += 1
            if level not in levels:
                for category in ('vocabulary', 'grammar', 'reading', 'listening'):
                    part = get(path + '?category=' + category)
                    assert {a['id'] for a in part['items']} <= {a['id'] for a in items}
                levels.add(level)
        assert checked > 0 and {'audio', 'image'} <= samples.keys()
        for kind, asset in samples.items():
            with urlopen(base_url + asset['url'], timeout=30) as response:
                data = response.read()
                assert response.status == 200
            assert len(data) == asset['byte_size'] and sha256(data).hexdigest() == asset['sha256']
            with urlopen(Request(base_url + asset['url'], headers={'Range': 'bytes=0-15'}), timeout=30) as response:
                assert response.status == 206 and response.read() == data[:16]
            try:
                get(f"/api/v1/assets/{asset['id']}?v=" + '0' * 64, authorized=False)
                raise AssertionError('Stale resource version accepted')
            except HTTPError as exc:
                assert exc.code == 409
        try:
            get(f'/api/v1/exam-practice/exams/{exams[0][0]}/resources', authorized=False)
            raise AssertionError('Unauthenticated manifest access accepted')
        except HTTPError as exc:
            assert exc.code == 401
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Practice).where(Practice.user_id == uid)) == 0
        return dict(status='passed', assets_hashed=total, published_manifests_checked=checked,
                    levels_checked=sorted(levels), media_sha256_checked=sorted(samples), range_checked=True,
                    stale_version_rejected=True, authentication_checked=True)
    finally:
        with SessionLocal.begin() as db:
            user = db.get(User, uid)
            if user is not None and user.username == username:
                db.execute(delete(Token).where(Token.user_id == uid))
                db.delete(user)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8001')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.base_url.rstrip('/'))
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
