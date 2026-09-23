from uuid import uuid4

from sqlalchemy import select

from app.models import User

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


def detail(client, admin_headers, user_id):
    response = client.get(PATH.format(user_id), headers=admin_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_update_requires_admin(client, account, database):
    missing = uuid4()
    assert client.patch(PATH.format(missing), json={'updated_at': 'x'}).status_code == 401
    assert client.patch(PATH.format(missing), headers=account, json={'updated_at': 'x'}).status_code == 403


def test_update_unknown_user_returns_404(client, account, database):
    promote_to_admin(database)
    assert client.patch(PATH.format(uuid4()), headers=account, json={'updated_at': 'x'}).status_code == 404


def test_update_applies_username_and_display_name(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Edit_Target')
    before = detail(client, account, target_id)

    response = client.patch(PATH.format(target_id), headers=account,
                            json={'username': 'Renamed_User', 'display_name': '  新名字  ', 'updated_at': before['updated_at']})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['username'] == 'renamed_user' and body['display_name'] == '新名字'
    assert body['is_admin'] is False and body['level'] == before['level']
    assert body['updated_at'] != before['updated_at']
    assert 'password' not in response.text and 'access_token' not in response.text

    with database() as db:
        user = db.get(User, target_id)
        assert user.username == 'renamed_user' and user.display_name == '新名字'
        assert user.is_admin is False and user.status == 'active'

    assert client.post('/api/v1/auth/login', json={'username': 'Renamed_User', 'password': PASSWORD}).status_code == 200


def test_update_can_clear_display_name(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Edit_Target')
    before = detail(client, account, target_id)
    response = client.patch(PATH.format(target_id), headers=account,
                            json={'display_name': None, 'updated_at': before['updated_at']})
    assert response.status_code == 200, response.text
    assert response.json()['display_name'] is None


def test_update_rejects_privileged_and_unknown_fields(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Edit_Target')
    version = detail(client, account, target_id)['updated_at']
    for payload in [{'is_admin': True}, {'level': 'N1'}, {'status': 'disabled'}, {'password': 'another-password'}]:
        response = client.patch(PATH.format(target_id), headers=account, json={**payload, 'updated_at': version})
        assert response.status_code == 422, f'{payload} -> {response.status_code}'

    untouched = detail(client, account, target_id)
    assert untouched['is_admin'] is False and untouched['level'] == 'N3' and untouched['status'] == 'active'
    assert 'password' not in untouched


def test_update_without_editable_fields_returns_422(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Edit_Target')
    version = detail(client, account, target_id)['updated_at']
    assert client.patch(PATH.format(target_id), headers=account, json={'updated_at': version}).status_code == 422


def test_stale_version_returns_409_without_changing_data(client, account, database):
    promote_to_admin(database)
    _, target_id = register(client, 'Edit_Target')
    stale = detail(client, account, target_id)['updated_at']

    first = client.patch(PATH.format(target_id), headers=account,
                         json={'display_name': '第一次', 'updated_at': stale})
    assert first.status_code == 200, first.text

    conflict = client.patch(PATH.format(target_id), headers=account,
                            json={'display_name': '第二次', 'updated_at': stale})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()['detail']['code'] == 'EDIT_CONFLICT'

    with database() as db:
        assert db.get(User, target_id).display_name == '第一次'


def test_duplicate_username_returns_409(client, account, database):
    promote_to_admin(database)
    _, first_id = register(client, 'First_User')
    _, second_id = register(client, 'Second_User')
    version = detail(client, account, second_id)['updated_at']

    conflict = client.patch(PATH.format(second_id), headers=account,
                            json={'username': 'First_User', 'updated_at': version})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()['detail']['code'] == 'USERNAME_TAKEN'
    assert 'password' not in conflict.text

    with database() as db:
        assert db.get(User, second_id).username == 'second_user'
