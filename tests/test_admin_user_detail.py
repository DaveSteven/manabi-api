from uuid import uuid4

from sqlalchemy import select

from app.models import User

DETAIL_PATH = '/api/v1/admin/users/{}'
STATS_PATH = '/api/v1/admin/users/{}/stats'
DETAIL_FIELDS = {'id', 'username', 'display_name', 'level', 'status', 'is_admin', 'created_at', 'last_login_at', 'updated_at'}
PASSWORD = 'a-valid-password'


def register(client, username):
    response = client.post('/api/v1/auth/register', json={'username': username, 'password': PASSWORD})
    assert response.status_code == 201, response.text
    body = response.json()
    return body['access_token'], body['user']['id']


def promote_to_admin(database, username='Student_1'):
    with database() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        assert user is not None, f'user {username} not found'
        user.is_admin = True
        db.commit()


def auth(token):
    return {'Authorization': 'Bearer ' + token}


def test_detail_and_stats_require_admin(client, account):
    missing = uuid4()
    assert client.get(DETAIL_PATH.format(missing)).status_code == 401
    assert client.get(DETAIL_PATH.format(missing), headers=account).status_code == 403
    assert client.get(STATS_PATH.format(missing)).status_code == 401
    assert client.get(STATS_PATH.format(missing), headers=account).status_code == 403


def test_unknown_user_returns_404(client, account, database):
    promote_to_admin(database)
    missing = uuid4()
    assert client.get(DETAIL_PATH.format(missing), headers=account).status_code == 404
    assert client.get(STATS_PATH.format(missing), headers=account).status_code == 404


def test_detail_returns_safe_fields(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Target_User')
    with database() as db:
        target = db.get(User, target_id)
        target.display_name = '目标用户'
        target.level = 'N4'
        db.commit()

    response = client.get(DETAIL_PATH.format(target_id), headers=account)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_FIELDS
    assert body['username'] == 'target_user' and body['display_name'] == '目标用户'
    assert body['level'] == 'N4' and body['status'] == 'active' and body['is_admin'] is False
    assert 'password' not in response.text and 'access_token' not in response.text


def test_stats_empty_for_user_without_practice(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Idle_User')
    response = client.get(STATS_PATH.format(target_id), headers=account)
    assert response.status_code == 200, response.text
    assert response.json() == {'practices': 0, 'answered': 0, 'correct': 0, 'accuracy': 0.0,
                               'wrong_questions': 0, 'levels': []}


def test_stats_summarizes_practice_by_level(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Learner_User')
    headers = auth(token)

    created = client.post('/api/v1/practices', headers=headers,
                          json={'level': 'N2', 'type_id': 'kanji_reading', 'count': 3, 'request_key': uuid4().hex})
    assert created.status_code == 201, created.text
    items = created.json()['items']
    assert len(items) >= 2
    practice_id = created.json()['id']

    for index, item in enumerate(items):
        options = item['question']['options']
        correct_option = options[0]['id']
        option_id = correct_option if index == 0 else next(o['id'] for o in options if o['id'] != correct_option)
        answered = client.post(f'/api/v1/practices/{practice_id}/items/{item["id"]}/answer',
                               headers=headers, json={'option_id': option_id, 'elapsed_ms': 0})
        assert answered.status_code == 200, answered.text
        assert answered.json()['feedback']['is_correct'] is (index == 0)

    total = len(items)
    response = client.get(STATS_PATH.format(target_id), headers=account)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['practices'] == 1
    assert body['answered'] == total and body['correct'] == 1
    assert body['accuracy'] == 1 / total and body['wrong_questions'] == total - 1
    assert [row['level'] for row in body['levels']] == ['N2']
    assert body['levels'][0] == {'level': 'N2', 'practices': 1, 'answered': total, 'correct': 1,
                                 'accuracy': 1 / total, 'wrong_questions': total - 1}
    assert 'snapshot' not in response.text and 'correct_option_id' not in response.text
