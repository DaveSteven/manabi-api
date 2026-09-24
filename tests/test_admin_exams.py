from sqlalchemy import delete, select

from app.models import Exam, ImportRun, Occurrence, QualityIssue, User

LIST_PATH = '/api/v1/admin/exams'
ITEM_FIELDS = {
    'id', 'title', 'level', 'year', 'month', 'published',
    'question_count', 'available_count', 'pending_review_count',
    'vocabulary_count', 'grammar_count', 'reading_count', 'listening_count',
}


def promote_to_admin(database, username='Student_1'):
    with database() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        assert user is not None
        user.is_admin = True
        db.commit()


def exams(client, headers, **params):
    response = client.get(LIST_PATH, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def exam_for_level(client, headers, level):
    body = exams(client, headers, level=level, limit=100)
    assert body['total'] == 1, body
    return body['items'][0]


def first_occurrence(db, level, type_id):
    exam = db.scalar(select(Exam).where(Exam.level == level))
    occurrence = db.scalar(select(Occurrence).where(Occurrence.exam_id == exam.id,
                                                    Occurrence.type_id == type_id))
    assert occurrence is not None
    return occurrence


def set_occurrence_status(database, level, type_id, status):
    with database() as db:
        first_occurrence(db, level, type_id).status = status
        db.commit()


def clear_quality_issues(database):
    with database() as db:
        db.execute(delete(QualityIssue))
        db.commit()


def add_quality_issue(database, level, type_id, severity='warning', current=True, retired=False,
                      code='missing_explanation'):
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
                            code=code, severity=severity, detail={}))
        db.commit()


def set_exam_published(database, level, published):
    with database() as db:
        exam = db.scalar(select(Exam).where(Exam.level == level))
        exam.published = published
        db.commit()


def test_exam_list_requires_admin(client, account):
    assert client.get(LIST_PATH).status_code == 401
    assert client.get(LIST_PATH, headers=account).status_code == 403


def test_exam_list_counts_from_real_data(client, account, database):
    promote_to_admin(database)
    body = exams(client, account, limit=100)
    assert body['total'] == 2 and body['limit'] == 100 and body['offset'] == 0
    assert len(body['items']) == 2
    assert set(body['items'][0]) == ITEM_FIELDS
    assert 'source_metadata' not in client.get(LIST_PATH, headers=account).text

    item = exam_for_level(client, account, 'N2')
    assert item['title'] == '2025年7月'
    assert item['year'] == 2025 and item['month'] == 7
    assert item['published'] is True
    assert item['question_count'] == 5
    assert item['available_count'] == 5
    assert item['pending_review_count'] == 0
    assert (item['vocabulary_count'], item['grammar_count']) == (2, 0)
    assert (item['reading_count'], item['listening_count']) == (2, 1)


def test_retired_history_is_not_counted_as_available(client, account, database):
    promote_to_admin(database)
    set_occurrence_status(database, 'N2', 'listening_task', 'retired')

    item = exam_for_level(client, account, 'N2')
    assert item['question_count'] == 4
    assert item['available_count'] == 4
    assert item['listening_count'] == 0


def test_review_status_counts_and_quality_filter(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    set_occurrence_status(database, 'N2', 'kanji_reading', 'review')
    add_quality_issue(database, 'N2', 'kanji_reading', 'error')

    item = exam_for_level(client, account, 'N2')
    assert item['question_count'] == 5
    assert item['available_count'] == 4
    assert item['pending_review_count'] == 1

    with_issues = exams(client, account, has_issues='true', limit=100)
    assert with_issues['total'] == 1 and with_issues['items'][0]['level'] == 'N2'
    without_issues = exams(client, account, has_issues='false', limit=100)
    assert without_issues['total'] == 1 and without_issues['items'][0]['level'] == 'N3'


def test_quality_filter_covers_ready_warning_and_info(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    assert exams(client, account, has_issues='true', limit=100)['total'] == 0
    assert exams(client, account, has_issues='false', limit=100)['total'] == 2

    add_quality_issue(database, 'N2', 'kanji_reading', 'warning')
    add_quality_issue(database, 'N3', 'short_reading', 'info')

    body = exams(client, account, has_issues='true', limit=100)
    assert body['total'] == 2
    first = exams(client, account, has_issues='true', limit=1, offset=0)
    second = exams(client, account, has_issues='true', limit=1, offset=1)
    assert first['total'] == 2 == second['total']
    assert first['items'][0]['id'] != second['items'][0]['id']
    item = exam_for_level(client, account, 'N2')
    assert item['available_count'] == 5 and item['pending_review_count'] == 0
    assert exams(client, account, has_issues='false', limit=100)['total'] == 0


def test_quality_filter_ignores_old_batch_and_retired(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    add_quality_issue(database, 'N2', 'kanji_reading', 'error', current=False)
    assert exams(client, account, has_issues='true', limit=100)['total'] == 0

    add_quality_issue(database, 'N3', 'kanji_reading', 'error', current=True, retired=True)
    assert exams(client, account, has_issues='true', limit=100)['total'] == 0
    item = exam_for_level(client, account, 'N3')
    assert item['question_count'] == 4 and item['available_count'] == 4


def test_quality_filter_does_not_duplicate_exam(client, account, database):
    promote_to_admin(database)
    clear_quality_issues(database)
    add_quality_issue(database, 'N2', 'kanji_reading', 'warning')
    add_quality_issue(database, 'N2', 'short_reading', 'info')

    body = exams(client, account, has_issues='true', limit=100)
    assert body['total'] == 1 and len(body['items']) == 1


def test_exam_list_filters(client, account, database):
    promote_to_admin(database)
    set_exam_published(database, 'N3', False)

    assert exams(client, account, level='N2')['total'] == 1
    assert exams(client, account, level='N1')['total'] == 0
    assert exams(client, account, year=2025)['total'] == 2
    assert exams(client, account, year=2024)['total'] == 0
    assert exams(client, account, month=7)['total'] == 2
    assert exams(client, account, month=8)['total'] == 0
    assert exams(client, account, keyword='2025')['total'] == 2
    assert exams(client, account, keyword='zzz')['total'] == 0
    assert exams(client, account, keyword='%')['total'] == 0
    assert exams(client, account, published='true')['items'][0]['level'] == 'N2'
    assert exams(client, account, published='false')['items'][0]['level'] == 'N3'


def test_exam_list_pagination_and_sorting_whitelist(client, account, database):
    promote_to_admin(database)

    first = exams(client, account, limit=1, offset=0)
    second = exams(client, account, limit=1, offset=1)
    assert first['total'] == 2 == second['total']
    assert first['items'][0]['id'] != second['items'][0]['id']

    titles = [item['title'] for item in exams(client, account, sort='title', order='asc')['items']]
    assert titles == sorted(titles)

    assert client.get(LIST_PATH, headers=account, params={'sort': 'source_id'}).status_code == 422
    assert client.get(LIST_PATH, headers=account, params={'level': 'N9'}).status_code == 422
    assert client.get(LIST_PATH, headers=account, params={'month': 13}).status_code == 422
    assert client.get(LIST_PATH, headers=account, params={'limit': 0}).status_code == 422
