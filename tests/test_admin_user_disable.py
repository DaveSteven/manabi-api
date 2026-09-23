from uuid import uuid4

from sqlalchemy import select

from app.models import User

DISABLE = '/api/v1/admin/users/{}/disable'
ENABLE = '/api/v1/admin/users/{}/enable'
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


def test_disable_enable_require_admin(client, account):
    missing = uuid4()
    assert client.post(DISABLE.format(missing)).status_code == 401
    assert client.post(DISABLE.format(missing), headers=account).status_code == 403
    assert client.post(ENABLE.format(missing)).status_code == 401
    assert client.post(ENABLE.format(missing), headers=account).status_code == 403


def test_disable_enable_unknown_user_returns_404(client, account, database):
    promote_to_admin(database)
    missing = uuid4()
    assert client.post(DISABLE.format(missing), headers=account).status_code == 404
    assert client.post(ENABLE.format(missing), headers=account).status_code == 404


def test_cannot_disable_self(client, account, database):
    promote_to_admin(database)
    admin_id = client.get('/api/v1/me', headers=account).json()['id']
    response = client.post(DISABLE.format(admin_id), headers=account)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'CANNOT_DISABLE_SELF'


def test_disable_revokes_tokens_and_blocks_login(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Victim_User')
    assert client.get('/api/v1/me', headers=auth(token)).status_code == 200

    response = client.post(DISABLE.format(target_id), headers=account, json={'reason': '违反使用条款'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['status'] == 'disabled' and body['updated_at'] is not None
    with database() as db:
        target = db.get(User, target_id)
        assert target.status == 'disabled' and target.disabled_at is not None

    assert client.get('/api/v1/me', headers=auth(token)).status_code == 401
    assert client.post('/api/v1/auth/login', json={'username': 'Victim_User', 'password': PASSWORD}).status_code == 403


def test_enable_restores_user(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Victim_User')
    assert client.post(DISABLE.format(target_id), headers=account).status_code == 200

    response = client.post(ENABLE.format(target_id), headers=account)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'active'
    with database() as db:
        target = db.get(User, target_id)
        assert target.status == 'active' and target.disabled_at is None
    assert client.post('/api/v1/auth/login', json={'username': 'Victim_User', 'password': PASSWORD}).status_code == 200


def test_disable_ordinary_user_is_allowed_for_sole_admin(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Ordinary_User')
    assert client.post(DISABLE.format(target_id), headers=account).status_code == 200


def test_admin_target_can_be_disabled_when_another_admin_remains(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Second_Admin')
    with database() as db:
        db.get(User, target_id).is_admin = True
        db.commit()
    response = client.post(DISABLE.format(target_id), headers=account)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'disabled'


def test_last_admin_is_protected(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Second_Admin')
    with database() as db:
        target = db.get(User, target_id)
        target.is_admin = True
        target.status = 'disabled'
        db.commit()
    response = client.post(DISABLE.format(target_id), headers=account)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'LAST_ADMIN_PROTECTED'
