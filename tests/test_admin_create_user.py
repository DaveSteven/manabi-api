from sqlalchemy import select

from app.models import User

CREATE_PATH = '/api/v1/admin/users'
VALID = {'username': 'New_Learner', 'password': 'a-valid-password', 'level': 'N2'}


def promote_to_admin(database, username='Student_1'):
    with database() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        assert user is not None, f'user {username} not found'
        user.is_admin = True
        db.commit()


def test_create_user_requires_admin(client, account):
    assert client.post(CREATE_PATH, json=VALID).status_code == 401
    assert client.post(CREATE_PATH, json=VALID, headers=account).status_code == 403


def test_admin_creates_ordinary_user_with_display_name(client, account, database):
    promote_to_admin(database)
    response = client.post(CREATE_PATH, headers=account,
                           json={**VALID, 'display_name': '  新的学习者  '})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['username'] == 'new_learner'
    assert body['is_admin'] is False and body['level'] == 'N2'
    assert 'password' not in response.text and 'access_token' not in response.text

    with database() as db:
        user = db.scalar(select(User).where(User.username == 'new_learner'))
        assert user.display_name == '新的学习者'
        assert user.status == 'active' and user.is_admin is False
        assert user.password_hash.startswith('pbkdf2_sha256$')

    assert client.post('/api/v1/auth/login', json={'username': 'New_Learner', 'password': 'a-valid-password'}).status_code == 200


def test_create_user_cannot_escalate_to_admin(client, account, database):
    promote_to_admin(database)
    response = client.post(CREATE_PATH, headers=account, json={**VALID, 'is_admin': True})
    assert response.status_code == 422
    assert client.post('/api/v1/auth/login', json={'username': 'New_Learner', 'password': 'a-valid-password'}).status_code == 401


def test_create_user_enforces_password_and_username_rules(client, account, database):
    promote_to_admin(database)
    assert client.post(CREATE_PATH, headers=account, json={**VALID, 'password': 'short'}).status_code == 422
    assert client.post(CREATE_PATH, headers=account, json={**VALID, 'username': 'bad name'}).status_code == 422
    assert client.post(CREATE_PATH, headers=account, json={**VALID, 'username': 'ab'}).status_code == 422
    assert client.post(CREATE_PATH, headers=account, json={**VALID, 'display_name': 'x' * 65}).status_code == 422


def test_create_user_duplicate_username_conflicts(client, account, database):
    promote_to_admin(database)
    assert client.post(CREATE_PATH, headers=account, json=VALID).status_code == 201
    conflict = client.post(CREATE_PATH, headers=account, json={**VALID, 'username': 'new_learner'})
    assert conflict.status_code == 409
    assert 'a-valid-password' not in conflict.text


def test_create_user_defaults_to_n5(client, account, database):
    promote_to_admin(database)
    response = client.post(CREATE_PATH, headers=account,
                           json={'username': 'Default_Level', 'password': 'a-valid-password'})
    assert response.status_code == 201, response.text
    assert response.json()['level'] == 'N5'
    with database() as db:
        assert db.scalar(select(User).where(User.username == 'default_level')).level == 'N5'


def test_blank_display_name_is_stored_as_null(client, account, database):
    promote_to_admin(database)
    assert client.post(CREATE_PATH, headers=account,
                       json={**VALID, 'display_name': '   '}).status_code == 201
    with database() as db:
        assert db.scalar(select(User).where(User.username == 'new_learner')).display_name is None
