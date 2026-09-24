from sqlalchemy import delete, select

from app.models import Exam, ImportRun, Occurrence, QualityIssue, User


def promote_to_admin(database, username='Student_1'):
    with database() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        assert user is not None
        user.is_admin = True
        db.commit()


def exam_id(database, level='N2'):
    with database() as db:
        return db.scalar(select(Exam).where(Exam.level == level)).id


def first_occurrence(db, level, type_id):
    exam = db.scalar(select(Exam).where(Exam.level == level))
    occurrence = db.scalar(select(Occurrence).where(Occurrence.exam_id == exam.id,
                                                    Occurrence.type_id == type_id))
    assert occurrence is not None
    return occurrence


def clear_quality_issues(database):
    with database() as db:
        db.execute(delete(QualityIssue))
        db.commit()


def set_occurrence_status(database, level, type_id, status):
    with database() as db:
        first_occurrence(db, level, type_id).status = status
        db.commit()


def add_quality_issue(database, level, type_id, severity='warning', current=True, retired=False):
    with database() as db:
        occurrence = first_occurrence(db, level, type_id)
        if retired:
            occurrence.status = 'retired'
        import_id = occurrence.import_id
        if not current:
            if db.get(ImportRun, 'old-batch') is None:
                db.add(ImportRun(id='old-batch', summary={}))
                db.flush()
            import_id = 'old-batch'
        db.add(QualityIssue(import_id=import_id, occurrence_id=occurrence.id,
                            code='missing_explanation', severity=severity, detail={}))
        db.commit()


def overview(client, account, exam):
    return client.get(f'/api/v1/admin/exams/{exam}', headers=account)


def category(body, name):
    return next(item for item in body['categories'] if item['category'] == name)


def status_count(body, name):
    return next(item for item in body['statuses'] if item['status'] == name)['count']


def quality_count(body, name):
    return next(item for item in body['qualities'] if item['severity'] == name)['count']


def test_exam_overview_requires_admin(client, account, database):
    exam = exam_id(database)
    assert client.get(f'/api/v1/admin/exams/{exam}').status_code == 401
    assert overview(client, account, exam).status_code == 403


def test_exam_overview_not_found(client, account, database):
    promote_to_admin(database)
    assert overview(client, account, 'does-not-exist').status_code == 404


def test_exam_overview_matches_database(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    exam = exam_id(database)

    response = overview(client, account, exam)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == exam and body['level'] == 'N2'
    assert body['title'] == '2025年7月'
    assert (body['year'], body['month'], body['published']) == (2025, 7, True)
    assert body['question_count'] == 5
    assert body['available_count'] == 5
    assert body['pending_review_count'] == 0
    assert body['retired_count'] == 0

    assert [item['category'] for item in body['categories']] == ['vocabulary', 'grammar', 'reading', 'listening']
    assert category(body, 'vocabulary')['question_count'] == 2
    assert category(body, 'grammar')['question_count'] == 0
    assert category(body, 'reading')['question_count'] == 2
    assert category(body, 'listening')['available_count'] == 1

    assert [item['type_id'] for item in body['types']] == ['kanji_reading', 'short_reading', 'listening_task']
    assert body['types'][0] == dict(type_id='kanji_reading', name_zh='汉字读音', name_ja='漢字読み',
                                    category='vocabulary', question_count=2, available_count=2,
                                    pending_review_count=0)

    assert status_count(body, 'ready') == 5
    assert status_count(body, 'review') == 0
    assert status_count(body, 'retired') == 0
    assert body['quality_issue_count'] == 0
    assert quality_count(body, 'error') == quality_count(body, 'warning') == quality_count(body, 'info') == 0


def test_exam_overview_reflects_status_changes(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    exam = exam_id(database)
    set_occurrence_status(database, 'N2', 'listening_task', 'retired')
    set_occurrence_status(database, 'N2', 'kanji_reading', 'review')

    body = overview(client, account, exam).json()
    assert body['question_count'] == 4
    assert body['available_count'] == 3
    assert body['pending_review_count'] == 1
    assert body['retired_count'] == 1
    assert category(body, 'listening')['question_count'] == 0
    assert category(body, 'vocabulary')['question_count'] == 2
    assert category(body, 'vocabulary')['available_count'] == 1
    assert category(body, 'vocabulary')['pending_review_count'] == 1
    assert status_count(body, 'ready') == 3
    assert status_count(body, 'review') == 1
    assert status_count(body, 'retired') == 1


def test_exam_overview_quality_counts_use_current_batch(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    exam = exam_id(database)
    add_quality_issue(database, 'N2', 'kanji_reading', 'warning')
    add_quality_issue(database, 'N2', 'short_reading', 'error')
    add_quality_issue(database, 'N2', 'listening_task', 'info')

    body = overview(client, account, exam).json()
    assert body['quality_issue_count'] == 3
    assert quality_count(body, 'error') == 1
    assert quality_count(body, 'warning') == 1
    assert quality_count(body, 'info') == 1
    assert body['pending_review_count'] == 0


def test_exam_overview_ignores_old_batch_and_retired_quality(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    exam = exam_id(database)
    add_quality_issue(database, 'N2', 'kanji_reading', 'error', current=False)
    add_quality_issue(database, 'N2', 'short_reading', 'warning', current=True, retired=True)

    body = overview(client, account, exam).json()
    assert body['quality_issue_count'] == 0
    assert status_count(body, 'retired') == 1
    assert body['question_count'] == 4
