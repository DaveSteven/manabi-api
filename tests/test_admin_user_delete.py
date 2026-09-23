from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import os

import pytest
from sqlalchemy import func, select

from app.models import Occurrence, Practice, Token, User, WrongQuestion

PATH = '/api/v1/admin/users/{}'
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


def make_practice(client, token):
    response = client.post('/api/v1/practices', headers=auth(token),
                           json={'level': 'N2', 'type_id': 'kanji_reading', 'count': 1, 'request_key': uuid4().hex})
    assert response.status_code == 201, response.text
    return response.json()


def test_delete_requires_admin(client, account):
    missing = uuid4()
    assert client.delete(PATH.format(missing)).status_code == 401
    assert client.delete(PATH.format(missing), headers=account).status_code == 403


def test_delete_unknown_user_returns_404(client, account, database):
    promote_to_admin(database)
    assert client.delete(PATH.format(uuid4()), headers=account).status_code == 404


def test_cannot_delete_self(client, account, database):
    promote_to_admin(database)
    admin_id = client.get('/api/v1/me', headers=account).json()['id']
    response = client.delete(PATH.format(admin_id), headers=account)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'CANNOT_DELETE_SELF'


def test_cannot_delete_administrator(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Second_Admin')
    with database() as db:
        db.get(User, target_id).is_admin = True
        db.commit()
    response = client.delete(PATH.format(target_id), headers=account)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'CANNOT_DELETE_ADMIN'


def test_delete_ordinary_user_without_data(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Clean_User')

    response = client.delete(PATH.format(target_id), headers=account)
    assert response.status_code == 204, response.text
    assert client.get(PATH.format(target_id), headers=account).status_code == 404
    assert client.get('/api/v1/me', headers=auth(token)).status_code == 401

    with database() as db:
        assert db.get(User, target_id) is None
        assert db.scalar(select(func.count()).select_from(Token).where(Token.user_id == target_id)) == 0


def test_delete_user_with_practice_returns_409(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Practice_User')
    make_practice(client, token)

    response = client.delete(PATH.format(target_id), headers=account)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'HAS_PRACTICE_DATA'

    with database() as db:
        assert db.get(User, target_id) is not None
        assert db.scalar(select(func.count()).select_from(Practice).where(Practice.user_id == target_id)) == 1


def test_delete_user_with_wrong_question_returns_409(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Wrong_User')
    with database() as db:
        occurrence = db.scalar(select(Occurrence).limit(1))
        assert occurrence is not None
        db.add(WrongQuestion(user_id=target_id, occurrence_id=occurrence.id, wrong_count=1, resolved=False))
        db.commit()

    response = client.delete(PATH.format(target_id), headers=account)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'HAS_WRONG_DATA'
    assert client.get(PATH.format(target_id), headers=account).status_code == 200


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='PostgreSQL locking integration test')
def test_concurrent_practice_creation_and_delete_are_serialized(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Race_User')
    data = {'level': 'N2', 'type_id': 'kanji_reading', 'count': 1, 'request_key': uuid4().hex}

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_future = executor.submit(client.post, '/api/v1/practices', json=data, headers=auth(token))
        delete_future = executor.submit(client.delete, PATH.format(target_id), headers=account)
        create_future.result()
        delete_response = delete_future.result()

    # The delete either ran before any practice existed or observed it and refused.
    # It must never remove a user that still owns practice rows.
    assert delete_response.status_code in (204, 409, 401, 404)
    with database() as db:
        practices = db.scalar(select(func.count()).select_from(Practice).where(Practice.user_id == target_id))
        remaining = db.get(User, target_id)
    if remaining is None:
        assert practices == 0
    else:
        assert delete_response.status_code == 409
