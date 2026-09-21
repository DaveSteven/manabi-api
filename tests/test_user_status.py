from sqlalchemy import select

from app.models import User


def register(client, username='status_user', password='a-valid-password'):
    response = client.post('/api/v1/auth/register', json={'username': username, 'password': password})
    assert response.status_code == 201, response.text
    return response.json()['access_token']


def set_status(database, username, status):
    with database() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        assert user is not None, f'user {username} not found'
        user.status = status
        db.commit()


def test_active_account_behaviour_unchanged(client, database):
    token = register(client, 'Active_User')
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/me', headers=headers).json()['username'] == 'active_user'
    login = client.post('/api/v1/auth/login', json={'username': 'Active_User', 'password': 'a-valid-password'})
    assert login.status_code == 200


def test_disabled_account_cannot_login(client, database):
    register(client, 'Disabled_User')
    set_status(database, 'Disabled_User', 'disabled')
    response = client.post('/api/v1/auth/login', json={'username': 'Disabled_User', 'password': 'a-valid-password'})
    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'ACCOUNT_DISABLED'
    assert 'access_token' not in response.text


def test_disabled_account_existing_token_is_rejected(client, database):
    token = register(client, 'Disabled_Token')
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/me', headers=headers).status_code == 200
    set_status(database, 'Disabled_Token', 'disabled')
    me = client.get('/api/v1/me', headers=headers)
    assert me.status_code == 401
    assert me.json()['detail']['code'] == 'ACCOUNT_DISABLED'
    assert client.get('/api/v1/practices', headers=headers).status_code == 401


def test_wrong_password_on_disabled_account_stays_unauthorized(client, database):
    register(client, 'Disabled_Password')
    set_status(database, 'Disabled_Password', 'disabled')
    response = client.post('/api/v1/auth/login', json={'username': 'Disabled_Password', 'password': 'wrong-password'})
    assert response.status_code == 401


def test_reenabled_account_can_login_again(client, database):
    register(client, 'Reenabled_User')
    set_status(database, 'Reenabled_User', 'disabled')
    set_status(database, 'Reenabled_User', 'active')
    response = client.post('/api/v1/auth/login', json={'username': 'Reenabled_User', 'password': 'a-valid-password'})
    assert response.status_code == 200
