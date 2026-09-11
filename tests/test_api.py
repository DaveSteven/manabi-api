from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import PracticeItem


def create(client, headers, qt='kanji_reading', count=1, **kwargs):
    data = dict(level='N2', type_id=qt, count=count, request_key=uuid4().hex, **kwargs)
    response = client.post('/api/v1/practices', json=data, headers=headers)
    assert response.status_code == 201, response.text
    return response.json(), data


def submit(client, headers, practice, item, option):
    return client.post(f'/api/v1/practices/{practice["id"]}/items/{item["id"]}/answer',
                       headers=headers, json={'option_id':option, 'elapsed_ms':1234})


def test_catalog_and_auth_required(client):
    assert client.get('/api/v1/health').json()['status']=='ok'
    assert len(client.get('/api/v1/catalog/levels').json()['items'])==2
    types = client.get('/api/v1/catalog/types?level=N2').json()['items']
    assert {t['id'] for t in types} == {'kanji_reading','short_reading','listening_task'}
    assert client.get('/api/v1/practices').status_code==401
    assert client.get('/api/v1/catalog/types?level=N1').status_code==422


def test_no_feedback_before_answer_and_resume(client, account):
    practice, _ = create(client, account, count=2)
    encoded = str(practice)
    assert 'correct_option_id' not in encoded and '解説' not in encoded and '翻译' not in encoded
    assert practice['items'][0]['feedback'] is None
    item=practice['items'][0]
    answer=submit(client,account,practice,item,item['question']['options'][0]['id'])
    assert answer.status_code==200, answer.text
    assert answer.json()['feedback']['is_correct'] is True
    resumed=client.get('/api/v1/practices/'+practice['id'],headers=account).json()
    assert resumed['answered']==1 and resumed['status']=='active'
    assert resumed['next_item_id']==practice['items'][1]['id']
    assert resumed['items'][1]['feedback'] is None


def test_idempotent_create_and_answer_and_wrong_review(client,account):
    practice, data=create(client,account)
    assert client.post('/api/v1/practices',json=data,headers=account).json()['id']==practice['id']
    assert client.post('/api/v1/practices',json={**data,'count':2},headers=account).status_code==409
    item=practice['items'][0]; wrong=item['question']['options'][1]['id']
    assert submit(client,account,practice,item,wrong).json()['feedback']['is_correct'] is False
    assert submit(client,account,practice,item,wrong).status_code==200
    assert submit(client,account,practice,item,item['question']['options'][0]['id']).status_code==409
    entries=client.get('/api/v1/wrong-questions',headers=account).json()
    assert entries['total']==1 and entries['items'][0]['wrong_count']==1
    review,_=create(client,account,mode='wrong')
    ri=review['items'][0]
    assert submit(client,account,review,ri,ri['question']['options'][0]['id']).status_code==200
    assert client.get('/api/v1/wrong-questions',headers=account).json()['total']==0
    assert client.get('/api/v1/wrong-questions?resolved=true',headers=account).json()['total']==1
    stats=client.get('/api/v1/me/stats',headers=account).json()['items'][0]
    assert stats['answered']==2 and stats['correct']==1 and stats['elapsed_ms']==2468


def test_complete_groups_even_when_requested_count_is_one(client,account):
    practice,_=create(client,account,'short_reading')
    assert practice['total']==2
    assert len({i['question']['group_id'] for i in practice['items']})==1
    assert len({i['question']['material']['id'] for i in practice['items']})==1


def test_user_isolation_and_invalid_options(client,account):
    practice,_=create(client,account)
    other={'Authorization':'Bearer '+client.post('/api/v1/auth/register',json={'username':'other_student','password':'a-valid-password'}).json()['access_token']}
    assert client.get('/api/v1/practices/'+practice['id'],headers=other).status_code==404
    item=practice['items'][0]
    assert submit(client,other,practice,item,item['question']['options'][0]['id']).status_code==404
    assert submit(client,account,practice,item,str(uuid4())).status_code==422
    assert client.post('/api/v1/practices/'+practice['id']+'/abandon',headers=account).status_code==200
    assert submit(client,account,practice,item,item['question']['options'][0]['id']).status_code==409


def test_registered_login_logout(client,account):
    credentials={'username':'Student_1','password':'a-valid-password'}
    guest=client.get('/api/v1/me',headers=account).json()
    assert guest['is_guest'] is False
    login=client.post('/api/v1/auth/login',json=credentials)
    assert login.status_code==200 and login.json()['user']['id']==guest['id']
    assert client.post('/api/v1/auth/register',json=credentials).status_code==409
    assert client.post('/api/v1/auth/login',json={**credentials,'password':'wrong-password'}).status_code==401
    assert client.post('/api/v1/auth/logout',headers=account).status_code==204
    assert client.get('/api/v1/me',headers=account).status_code==401
    invalid=client.post('/api/v1/auth/register',json={**credentials,'password':'secret'})
    assert invalid.status_code==422 and 'secret' not in invalid.text


def test_media_range_and_listening_feedback(client,account):
    practice,_=create(client,account,'listening_task')
    item=practice['items'][0]; url=item['question']['material']['audio_url']
    response=client.get(url,headers={'Range':'bytes=0-2'})
    assert response.status_code==206 and response.content==b'ID3'
    answer=submit(client,account,practice,item,item['question']['options'][0]['id']).json()
    assert answer['feedback']['subtitles'][0]['end_ms']==1500
    assert client.get('/api/v1/practices/'+practice['id'],headers=account).json()['status']=='completed'


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'),reason='PostgreSQL locking integration test')
def test_concurrent_retry_only_counts_once(client,account):
    practice,_=create(client,account)
    item=practice['items'][0];wrong=item['question']['options'][1]['id']
    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses=list(executor.map(lambda _:submit(client,account,practice,item,wrong).status_code,range(4)))
    assert statuses==[200]*4
    assert client.get('/api/v1/wrong-questions',headers=account).json()['items'][0]['wrong_count']==1


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'),reason='PostgreSQL locking integration test')
def test_concurrent_creation_reuses_practice(client,account):
    data=dict(level='N2',type_id='kanji_reading',count=1,request_key=uuid4().hex)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(lambda _:client.post('/api/v1/practices',json=data,headers=account),range(4)))
    assert all(r.status_code==201 for r in results)
    assert len({r.json()['id'] for r in results})==1


def test_guest_creation_and_existing_guest_token_are_blocked(client, database):
    from app.models import User
    from app.auth import issue_token
    assert client.post('/api/v1/auth/guest').status_code == 404
    with database() as db:
        user = User()
        db.add(user)
        db.flush()
        token = issue_token(db, user)['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    for path in ('/api/v1/me', '/api/v1/practices', '/api/v1/wrong-questions'):
        assert client.get(path, headers=headers).status_code == 401


def test_registration_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv('ENABLE_REGISTRATION', 'false')
    assert client.post('/api/v1/auth/register', json={
        'username':'blocked_user', 'password':'a-valid-password'
    }).status_code == 403


def test_intensive_listening_is_owned_and_does_not_submit(client, account):
    practice, _ = create(client, account, 'listening_task')
    item = practice['items'][0]
    path = f"/api/v1/practices/{practice['id']}/items/{item['id']}/listening"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=account)
    assert response.status_code == 200
    assert response.json()['segments'][0]['end_ms'] == 1500
    assert 'correct_option_id' not in response.text
    assert client.get('/api/v1/practices/'+practice['id'], headers=account).json()['answered'] == 0
    other = client.post('/api/v1/auth/register', json={'username':'listening_other','password':'valid-password'}).json()
    assert client.get(path, headers={'Authorization':'Bearer '+other['access_token']}).status_code == 404
    ordinary, _ = create(client, account)
    assert client.get(f"/api/v1/practices/{ordinary['id']}/items/{ordinary['items'][0]['id']}/listening", headers=account).status_code == 404


def test_exam_practice_filters_resume_completion_and_isolation(client, account):
    catalog = '/api/v1/exam-practice/exams?level=N2&category=vocabulary'
    assert client.get(catalog).status_code == 401
    exams = client.get(catalog, headers=account).json()['items']
    assert len(exams) == 1 and exams[0]['status'] == 'not_started'
    eid = exams[0]['id']
    types_path = f'/api/v1/exam-practice/exams/{eid}/types?category=vocabulary'
    types = client.get(types_path, headers=account).json()['items']
    assert [t['id'] for t in types] == ['kanji_reading']
    path = f'/api/v1/exam-practice/exams/{eid}/types/kanji_reading/practice'
    practice = client.post(path, headers=account).json()
    assert practice['mode'] == 'exam' and practice['total'] == 2
    assert {i['question']['source']['exam_id'] for i in practice['items']} == {eid}
    positions = [i['question']['source']['position'] for i in practice['items']]
    assert positions == sorted(positions)
    assert client.post(path, headers=account).json()['id'] == practice['id']
    for n, item in enumerate(practice['items'], 1):
        assert submit(client, account, practice, item, item['question']['options'][0]['id']).status_code == 200
        row = client.get(types_path, headers=account).json()['items'][0]
        assert row['answered'] == n and row['correct'] == n
        assert row['status'] == ('completed' if n == 2 else 'active')
    assert client.post(path, headers=account).json()['status'] == 'completed'
    assert client.get(catalog, headers=account).json()['items'][0]['status'] == 'completed'
    other = client.post('/api/v1/auth/register', json={'username':'exam_other','password':'valid-password'}).json()
    other_headers = {'Authorization':'Bearer '+other['access_token']}
    assert client.get(catalog, headers=other_headers).json()['items'][0]['answered'] == 0
    assert client.get('/api/v1/practices/'+practice['id'], headers=other_headers).status_code == 404
    assert client.post(f'/api/v1/exam-practice/exams/{eid}/types/not-a-type/practice', headers=account).status_code == 404
    assert client.get('/api/v1/exam-practice/exams?level=N2&category=invalid', headers=account).status_code == 422


def test_exam_reading_keeps_whole_group_and_random_does_not_count(client, account):
    normal, _ = create(client, account)
    item = normal['items'][0]
    submit(client, account, normal, item, item['question']['options'][0]['id'])
    catalog = '/api/v1/exam-practice/exams?level=N2&category=vocabulary'
    assert client.get(catalog, headers=account).json()['items'][0]['answered'] == 0
    eid = client.get('/api/v1/exam-practice/exams?level=N2&category=reading', headers=account).json()['items'][0]['id']
    result = client.post(f'/api/v1/exam-practice/exams/{eid}/types/short_reading/practice', headers=account).json()
    assert result['total'] == 2
    assert len({i['question']['group_id'] for i in result['items']}) == 1


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='PostgreSQL locking integration test')
def test_concurrent_exam_start_reuses_progress(client, account):
    eid = client.get('/api/v1/exam-practice/exams?level=N2&category=listening', headers=account).json()['items'][0]['id']
    path = f'/api/v1/exam-practice/exams/{eid}/types/listening_task/practice'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path, headers=account), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()['id'] for r in responses}) == 1
