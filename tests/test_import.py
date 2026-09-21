import json
from sqlalchemy import func, select
import pytest

from app.models import Material, Occurrence, Option, PracticeItem, Question
from scripts.import_jlpt import run_import


def change(source, fn):
    path=source/'normalized/N2/questions_with_assets.json'
    rows=json.loads(path.read_text());fn(rows);path.write_text(json.dumps(rows))


def test_source_id_reuse_does_not_overwrite_level_and_import_is_repeatable(database,source,tmp_path):
    with database() as db:
        before={o.id for o in db.scalars(select(Occurrence))}
        assert len(before)==10
        assert set(db.scalars(select(Occurrence.level)))=={'N2','N3'}
        summary=run_import(db,source,tmp_path/'report.json')
        assert summary['occurrences']==10
        assert {o.id for o in db.scalars(select(Occurrence))}==before
        assert db.scalar(select(func.count()).select_from(Question))==5


def test_conflict_quarantines_entire_material_group(database,source,tmp_path):
    change(source,lambda rows:rows[2].update(question_type=32))
    with database() as db:
        run_import(db,source,tmp_path/'report.json')
        rows=list(db.scalars(select(Occurrence).where(Occurrence.level=='N2',Occurrence.status=='review')))
        assert len(rows)==2


def test_missing_audio_and_invalid_answer_are_not_practice_ready(database,source,tmp_path):
    change(source,lambda rows:(rows[0].update(right_answer='9'),rows[4].update(media_path='../../secret')))
    with database() as db:
        result=run_import(db,source,tmp_path/'report.json')
        assert result['issues_by_code']['invalid_answer']==1
        assert result['issues_by_code']['missing_asset']==1
        assert result['status_counts']['review']==2


def test_import_does_not_change_existing_practice_snapshot(client,account,database,source,tmp_path):
    response=client.post('/api/v1/practices',headers=account,json=dict(level='N2',type_id='kanji_reading',count=2,request_key='snapshot-test'))
    practice=response.json()
    change(source,lambda rows:rows[0].update(title='修订题目',analysis='修订解析'))
    with database() as db:
        run_import(db,source,tmp_path/'report.json')
    assert client.get('/api/v1/practices/'+practice['id'],headers=account).json()==practice


def test_malformed_import_rolls_back(database,source,tmp_path):
    change(source,lambda rows:rows[0].update(layer_id='missing'))
    with database() as db:
        with pytest.raises(ValueError):run_import(db,source,tmp_path/'report.json')
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Occurrence))==10


def test_reordering_does_not_retarget_occurrences(database,source,tmp_path):
    with database() as db:
        before={o.source['question_id']:o.id for o in db.scalars(select(Occurrence).where(Occurrence.level=='N2'))}
        change(source,lambda rows:rows.reverse())
        run_import(db,source,tmp_path/'report.json')
        db.expire_all()
        after={o.source['question_id']:o.id for o in db.scalars(select(Occurrence).where(Occurrence.level=='N2',Occurrence.status=='ready'))}
        assert before==after


@pytest.mark.parametrize('level', ['N1', 'N4', 'N5'])
def test_new_level_import_is_scoped_and_practice_available(level,database,source,tmp_path,client,account):
    import shutil
    shutil.copytree(source/'normalized/N2', source/'normalized'/level)
    with database() as db:
        before={o.id:(o.status,o.import_id) for o in db.scalars(select(Occurrence))}
        summary=run_import(db,source,tmp_path/'new-report.json',selected_levels=[level])
        assert summary['levels']==[level]
        assert summary['occurrences']==5
        db.expire_all()
        assert {o.id:(o.status,o.import_id) for o in db.scalars(select(Occurrence).where(Occurrence.level.in_(['N2','N3'])))}==before
        run_import(db,source,tmp_path/'repeat-report.json',selected_levels=[level])
        assert db.scalar(select(func.count()).select_from(Occurrence))==15
    assert client.get('/api/v1/catalog/types',params={'level':level}).status_code==200
    assert client.patch('/api/v1/me',headers=account,json={'level':level}).status_code==200
    response=client.post('/api/v1/practices',headers=account,json=dict(level=level,type_id='kanji_reading',count=2,request_key=f'new-level-{level}'))
    assert response.status_code==201,response.text
    assert response.json()['total']==2


def test_missing_selected_level_cannot_retire_data(database,source,tmp_path):
    with database() as db:
        with pytest.raises(ValueError,match='Missing source file'):
            run_import(db,source,tmp_path/'report.json',selected_levels=['N5'])
        assert db.scalar(select(func.count()).select_from(Occurrence).where(Occurrence.status=='ready'))==10


def test_n1_aliases_keep_other_levels_unchanged():
    from app.taxonomy import type_id
    assert type_id('N1',13)==type_id('N1',14)=='context_vocabulary'
    assert type_id('N1',44)==type_id('N1',45)=='listening_response'
    assert type_id('N2',13)=='word_formation'
    assert type_id('N4',44)==type_id('N5',44)=='listening_expression'
