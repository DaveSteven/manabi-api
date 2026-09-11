import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import main
from scripts.import_jlpt import run_import


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    (root / 'assets/audio').mkdir(parents=True)
    (root / 'assets/audio/sample.mp3').write_bytes(b'ID3' + b'0' * 100)
    for level in ['N2', 'N3']:
        path = root / 'normalized' / level
        path.mkdir(parents=True)
        exam = dict(objectId='shared-exam', title='2025年7月', isPublished=True,
                    layers=[dict(objectId='vocab', questionType=11, title='問題1 読み方を選んでください。'),
                            dict(objectId='reading', questionType=31, title='問題2 文章を読んでください。'),
                            dict(objectId='audio', questionType=41, title='問題3 聞いてください。')])
        rows = []
        for i, (layer, code, parent) in enumerate([('vocab',11,''),('vocab',11,''),('reading',31,'parent'),('reading',31,'parent'),('audio',41,'')]):
            rows.append(dict(question_id=f'q{i}', exam_id='shared-exam', layer_id=layer,
                question_type=code, layer_question_type=code, title=f'<u>題{i}</u>',
                passage='<p>共有文章</p>' if parent else '', parent_id=parent,
                options=['正解','不正解','別の選択肢'], right_answer='0', analysis='解説',
                translation='<p>翻译</p>',
                subtitle='<p data-starttime="00:00:00,000" data-endtime="00:00:01,500">音声</p>' if code==41 else '',
                media_path='audio/sample.mp3' if code==41 else ''))
        (path / 'exams_with_assets.json').write_text(json.dumps([exam]))
        (path / 'questions_with_assets.json').write_text(json.dumps(rows))
    return root


@pytest.fixture
def database(source, tmp_path):
    pg = os.getenv('TEST_POSTGRES_URL')
    admin = None
    if pg:
        schema = 'manabi_test_' + uuid4().hex
        admin = create_engine(pg)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(pg, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
        from sqlalchemy import event
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        run_import(db, source, tmp_path/'report.json')
    yield sessions
    engine.dispose()
    if admin:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


@pytest.fixture
def client(database, source, monkeypatch):
    def session():
        with database() as db:
            yield db
    main.app.dependency_overrides[get_db] = session
    monkeypatch.setattr(main, 'ASSETS_ROOT', source / 'assets')
    main.auth_requests.clear()
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


@pytest.fixture
def account(client):
    r = client.post('/api/v1/auth/register', json={'username':'Student_1','password':'a-valid-password'})
    assert r.status_code == 201, r.text
    return {'Authorization': 'Bearer '+r.json()['access_token']}
