from uuid import uuid4

from sqlalchemy import select

from app.models import User

RESET = '/api/v1/admin/users/{}/reset-password'
REVOKE = '/api/v1/admin/users/{}/revoke-tokens'
OLD_PASSWORD = 'a-valid-password'
NEW_PASSWORD = 'a-brand-new-password'


def register(client, username, password=OLD_PASSWORD):
    response = client.post('/api/v1/auth/register', json={'username': username, 'password': password})
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


def login(client, username, password):
    return client.post('/api/v1/auth/login', json={'username': username, 'password': password})


def test_password_endpoints_require_admin(client, account):
    missing = uuid4()
    assert client.post(RESET.format(missing), json={'password': NEW_PASSWORD}).status_code == 401
    assert client.post(RESET.format(missing), headers=account, json={'password': NEW_PASSWORD}).status_code == 403
    assert client.post(REVOKE.format(missing)).status_code == 401
    assert client.post(REVOKE.format(missing), headers=account).status_code == 403


def test_password_endpoints_unknown_user_returns_404(client, account, database):
    promote_to_admin(database)
    missing = uuid4()
    assert client.post(RESET.format(missing), headers=account, json={'password': NEW_PASSWORD}).status_code == 404
    assert client.post(REVOKE.format(missing), headers=account).status_code == 404


def test_reset_password_changes_credentials_and_revokes_tokens(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Reset_Target')
    assert client.get('/api/v1/me', headers=auth(token)).status_code == 200

    response = client.post(RESET.format(target_id), headers=account, json={'password': NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert 'password_hash' not in response.text and 'access_token' not in response.text
    assert NEW_PASSWORD not in response.text

    assert client.get('/api/v1/me', headers=auth(token)).status_code == 401
    assert login(client, 'Reset_Target', OLD_PASSWORD).status_code == 401
    assert login(client, 'Reset_Target', NEW_PASSWORD).status_code == 200


def test_revoke_tokens_keeps_password(client, account, database):
    promote_to_admin(database)
    token, target_id = register(client, 'Revoke_Target')

    response = client.post(REVOKE.format(target_id), headers=account)
    assert response.status_code == 200, response.text
    assert 'password_hash' not in response.text and 'access_token' not in response.text

    assert client.get('/api/v1/me', headers=auth(token)).status_code == 401
    assert login(client, 'Revoke_Target', OLD_PASSWORD).status_code == 200


def test_short_password_is_rejected_without_echoing_input(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Reset_Target')
    response = client.post(RESET.format(target_id), headers=account, json={'password': 'secretvalue'[:6]})
    assert response.status_code == 422
    assert 'secret' not in response.text
    assert login(client, 'Reset_Target', OLD_PASSWORD).status_code == 200


def test_reset_rejects_unknown_fields(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Reset_Target')
    response = client.post(RESET.format(target_id), headers=account,
                           json={'password': NEW_PASSWORD, 'is_admin': True})
    assert response.status_code == 422
    assert login(client, 'Reset_Target', OLD_PASSWORD).status_code == 200


def test_deleted_user_cannot_be_reset_or_revoked(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Deleted_Target')
    with database() as db:
        db.get(User, target_id).status = 'deleted'
        db.commit()
    reset = client.post(RESET.format(target_id), headers=account, json={'password': NEW_PASSWORD})
    assert reset.status_code == 409 and reset.json()['detail']['code'] == 'USER_DELETED'
    revoke = client.post(REVOKE.format(target_id), headers=account)
    assert revoke.status_code == 409 and revoke.json()['detail']['code'] == 'USER_DELETED'
