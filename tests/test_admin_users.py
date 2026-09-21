from sqlalchemy import select

from app.models import User

LIST_PATH = '/api/v1/admin/users'
FIELDS = {'id', 'username', 'display_name', 'level', 'status', 'is_admin', 'created_at', 'last_login_at'}


def register(client, username, password='a-valid-password'):
    response = client.post('/api/v1/auth/register', json={'username': username, 'password': password})
    assert response.status_code == 201, response.text
    return response.json()['access_token']


def promote_to_admin(database, username):
    with database() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        assert user is not None, f'user {username} not found'
        user.is_admin = True
        db.commit()


def usernames(response):
    assert response.status_code == 200, response.text
    return {item['username'] for item in response.json()['items']}


def test_user_list_requires_admin(client, account):
    assert client.get(LIST_PATH).status_code == 401
    assert client.get(LIST_PATH, headers=account).status_code == 403


def test_user_list_returns_paginated_safe_fields(client, account, database):
    promote_to_admin(database, 'Student_1')
    register(client, 'List_User_One')
    register(client, 'List_User_Two')

    response = client.get(LIST_PATH, headers=account, params={'limit': 2, 'offset': 0})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['limit'] == 2 and body['offset'] == 0 and body['total'] == 3
    assert len(body['items']) == 2
    assert set(body['items'][0]) == FIELDS
    assert 'password' not in response.text and 'access_token' not in response.text

    second = client.get(LIST_PATH, headers=account, params={'limit': 2, 'offset': 2}).json()
    assert len(second['items']) == 1
    ids = {item['id'] for item in body['items']} | {item['id'] for item in second['items']}
    assert len(ids) == 3


def test_user_list_filters(client, account, database):
    promote_to_admin(database, 'Student_1')
    register(client, 'Alpha_User')
    register(client, 'Beta_User')
    with database() as db:
        alpha = db.scalar(select(User).where(User.username == 'alpha_user'))
        alpha.level = 'N1'
        alpha.display_name = 'Alpha 表示名'
        beta = db.scalar(select(User).where(User.username == 'beta_user'))
        beta.status = 'disabled'
        db.commit()

    assert usernames(client.get(LIST_PATH, headers=account, params={'keyword': 'Alpha'})) == {'alpha_user'}
    assert usernames(client.get(LIST_PATH, headers=account, params={'keyword': '表示名'})) == {'alpha_user'}
    assert usernames(client.get(LIST_PATH, headers=account, params={'level': 'N1'})) == {'alpha_user'}
    assert usernames(client.get(LIST_PATH, headers=account, params={'status': 'disabled'})) == {'beta_user'}
    assert usernames(client.get(LIST_PATH, headers=account, params={'is_admin': 'true'})) == {'student_1'}
    assert usernames(client.get(LIST_PATH, headers=account, params={'is_admin': 'false'})) == {'alpha_user', 'beta_user'}


def test_user_list_keyword_wildcards_are_literal(client, account, database):
    promote_to_admin(database, 'Student_1')
    register(client, 'Percent_User')
    response = client.get(LIST_PATH, headers=account, params={'keyword': '%'})
    assert usernames(response) == set()


def test_user_list_sorting_whitelist(client, account, database):
    promote_to_admin(database, 'Student_1')
    register(client, 'Charlie_User')
    register(client, 'Bravo_User')

    ascending = client.get(LIST_PATH, headers=account, params={'sort': 'username', 'order': 'asc'})
    names = [item['username'] for item in ascending.json()['items']]
    assert names == sorted(names)

    descending = client.get(LIST_PATH, headers=account, params={'sort': 'username', 'order': 'desc'})
    assert [item['username'] for item in descending.json()['items']] == sorted(names, reverse=True)

    invalid = client.get(LIST_PATH, headers=account, params={'sort': 'password_hash'})
    assert invalid.status_code == 422


def test_user_list_rejects_invalid_filters(client, account, database):
    promote_to_admin(database, 'Student_1')
    assert client.get(LIST_PATH, headers=account, params={'status': 'unknown'}).status_code == 422
    assert client.get(LIST_PATH, headers=account, params={'level': 'N9'}).status_code == 422
    assert client.get(LIST_PATH, headers=account, params={'limit': 0}).status_code == 422
