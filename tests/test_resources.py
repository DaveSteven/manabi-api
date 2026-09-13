from hashlib import sha256
from sqlalchemy import select, func
from app.models import Asset, Exam, Material, Occurrence, Practice
from scripts.hash_assets import hash_assets


def manifest_url(database):
    with database() as db:
        eid = db.scalar(select(Exam.id).where(Exam.level == 'N2'))
    return f'/api/v1/exam-practice/exams/{eid}/resources'


def test_manifest_filters_dedup_and_download(client, account, database, source):
    image = source / 'assets/sample.png'
    image.write_bytes(b'example-image')
    with database() as db:
        audio = db.scalar(select(Asset))
        db.add(Asset(id='image', kind='image', path='sample.png', mime_type='image/png',
                     byte_size=13, content_hash=sha256(image.read_bytes()).hexdigest()))
        db.flush()
        for material in db.scalars(select(Material)):
            material.audio_id = audio.id
            material.image_id = 'image'
        db.commit()
    url = manifest_url(database)
    assert client.get(url).status_code == 401
    response = client.get(url, headers=account)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['resource_count'] == 2
    assert data['total_bytes'] == 116
    assert len({a['id'] for a in data['items']}) == 2
    for asset in data['items']:
        download = client.get(asset['url'])
        assert download.status_code == 200
        assert len(download.content) == asset['byte_size']
        assert sha256(download.content).hexdigest() == asset['sha256']
        assert 'path' not in asset
    for query in ['?category=listening', '?type_id=kanji_reading', '?category=vocabulary&type_id=kanji_reading']:
        assert client.get(url+query, headers=account).json()['items'] == data['items']
    assert client.get(url+'?category=grammar', headers=account).json()['total_bytes'] == 0
    for query in ['?category=invalid', '?type_id=invalid', '?category=listening&type_id=kanji_reading']:
        assert client.get(url+query, headers=account).status_code == 422
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Practice)) == 0
        for occurrence in db.scalars(select(Occurrence).where(Occurrence.level == 'N2')):
            occurrence.status = 'review'
        db.commit()
    assert client.get(url, headers=account).json()['items'] == []
    with database() as db:
        db.scalar(select(Exam).where(Exam.level == 'N2')).published = False
        db.commit()
    assert client.get(url, headers=account).status_code == 404
    assert client.get('/api/v1/exam-practice/exams/missing/resources', headers=account).status_code == 404


def test_backfill_and_changed_resource_version(client, account, database, source):
    url = manifest_url(database)
    old = client.get(url, headers=account).json()['items'][0]
    with database() as db:
        db.scalar(select(Asset)).content_hash = None
        db.commit()
    assert client.get(url, headers=account).status_code == 503
    (source / 'assets/audio/sample.mp3').write_bytes(b'new-content')
    with database() as db:
        assert hash_assets(db, source / 'assets') == 1
        db.commit()
    new = client.get(url, headers=account).json()['items'][0]
    assert new['id'] == old['id']
    assert new['sha256'] != old['sha256']
    assert new['byte_size'] == 11
    assert client.get(old['url']).status_code == 409
    assert client.get(new['url']).content == b'new-content'
    assert client.get(f"/api/v1/assets/{new['id']}").status_code == 200
