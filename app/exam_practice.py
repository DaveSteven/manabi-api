"""Persistent, ordered practice for a complete exam question type."""
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import defer

from .auth import current_user, lock_user
from .database import get_db
from .models import Asset, Material, Exam, Occurrence, Practice, PracticeItem, QuestionType
from .practice import make_snapshot, practice_out
from .schemas import ExamResourcesOut, Category, ExamPracticeList, ExamPracticeTypes, Level, PracticeOut

router = APIRouter(prefix='/api/v1/exam-practice', tags=['Exam practice'])


def progress_rows(db, user, level, category):
    exam_ids = select(Exam.id).where(Exam.level == level, Exam.published.is_(True))
    rows = db.execute(select(Occurrence.exam_id, QuestionType, func.count(Occurrence.id))
        .join(QuestionType, Occurrence.type_id == QuestionType.id)
        .where(Occurrence.exam_id.in_(exam_ids), Occurrence.status == 'ready', QuestionType.category == category)
        .group_by(Occurrence.exam_id, QuestionType.id).order_by(QuestionType.sort_order))
    result = {}
    for exam_id, qt, total in rows:
        result[(exam_id, qt.id)] = dict(id=qt.id, name_zh=qt.name_zh, name_ja=qt.name_ja,
            category=qt.category, total=total, answered=0, correct=0, status='not_started', practice_id=None)
    # Only this module's sessions contribute to exam progress; random drills stay independent.
    progress = db.execute(select(Occurrence.exam_id, QuestionType, Practice.id, Practice.status,
        func.count(PracticeItem.id), func.count(PracticeItem.answered_at),
        func.count(PracticeItem.id).filter(PracticeItem.correct.is_(True)))
        .select_from(Practice).join(PracticeItem, PracticeItem.practice_id == Practice.id)
        .join(Occurrence, Occurrence.id == PracticeItem.occurrence_id)
        .join(QuestionType, QuestionType.id == Practice.type_id)
        .where(Practice.user_id == user.id, Practice.mode == 'exam',
               Occurrence.exam_id.in_(exam_ids), QuestionType.category == category)
        .group_by(Occurrence.exam_id, QuestionType.id, Practice.id))
    for exam_id, qt, pid, status, total, answered, correct in progress:
        result[(exam_id, qt.id)] = dict(id=qt.id, name_zh=qt.name_zh, name_ja=qt.name_ja,
            category=qt.category, total=total, answered=answered, correct=correct, status=status, practice_id=pid)
    return result


@router.get('/exams', response_model=ExamPracticeList)
def list_exams(level: Level, category: Category, user=Depends(current_user), db=Depends(get_db)):
    progress = progress_rows(db, user, level, category)
    exams = db.scalars(select(Exam).options(defer(Exam.source_metadata))
        .where(Exam.level == level, Exam.published.is_(True))
        .order_by(Exam.year.desc().nullslast(), Exam.month.desc().nullslast(), Exam.id))
    items = []
    for exam in exams:
        types = [row for (eid, _), row in progress.items() if eid == exam.id]
        if not types:
            continue
        total = sum(row['total'] for row in types)
        answered = sum(row['answered'] for row in types)
        status = 'completed' if all(row['status'] == 'completed' for row in types) else (
            'active' if any(row['practice_id'] for row in types) else 'not_started')
        items.append(dict(id=exam.id, title=exam.title, level=exam.level, year=exam.year, month=exam.month,
            total=total, answered=answered, correct=sum(row['correct'] for row in types), status=status))
    return dict(items=items)


@router.get('/exams/{exam_id}/types', response_model=ExamPracticeTypes)
def list_types(exam_id: str, category: Category, user=Depends(current_user), db=Depends(get_db)):
    exam = db.get(Exam, exam_id)
    if exam is None or not exam.published:
        raise HTTPException(404, 'Exam not available')
    progress = progress_rows(db, user, exam.level, category)
    order = dict(db.execute(select(QuestionType.id, QuestionType.sort_order)).all())
    items = [row for (eid, _), row in progress.items() if eid == exam_id]
    return dict(items=sorted(items, key=lambda row: order[row['id']]))


@router.post('/exams/{exam_id}/types/{type_id}/practice', response_model=PracticeOut)
def start_exam_type(exam_id: str, type_id: str, user=Depends(current_user), db=Depends(get_db)):
    lock_user(db, user)
    exam = db.get(Exam, exam_id)
    if exam is None or not exam.published:
        raise HTTPException(404, 'Exam not available')
    key = 'exam-' + str(uuid5(NAMESPACE_URL, exam_id + '/' + type_id))
    existing = db.scalar(select(Practice).where(Practice.user_id == user.id, Practice.request_key == key))
    if existing:
        if existing.mode != 'exam' or existing.type_id != type_id or existing.level != exam.level:
            raise HTTPException(409, 'Practice request key is already in use')
        if existing.status == 'abandoned':
            existing.status = 'active'
            db.commit()
        return practice_out(db, existing)
    occurrences = list(db.scalars(select(Occurrence).options(defer(Occurrence.source))
        .where(Occurrence.exam_id == exam_id, Occurrence.type_id == type_id, Occurrence.status == 'ready')
        .order_by(Occurrence.position, Occurrence.id)))
    if not occurrences:
        raise HTTPException(404, 'No ready questions for this exam type')
    practice = Practice(user_id=user.id, level=exam.level, type_id=type_id, mode='exam',
        requested_count=len(occurrences), request_key=key)
    db.add(practice)
    db.flush()
    for position, occurrence in enumerate(occurrences):
        db.add(PracticeItem(practice_id=practice.id, occurrence_id=occurrence.id,
            question_id=occurrence.question_id, position=position, snapshot=make_snapshot(db, occurrence)))
    db.commit()
    return practice_out(db, practice)


@router.get('/exams/{exam_id}/resources', response_model=ExamResourcesOut,
            summary='List deduplicated audio and image resources for a paper')
def list_resources(exam_id: str, category: Category | None = None, type_id: str | None = None,
                   user=Depends(current_user), db=Depends(get_db)):
    """Omit filters for the whole paper; category and type_id intersect when both supplied.

    Only published papers and ready questions are included. Does not create practice or
    modify progress. total_bytes counts unique resource IDs, before device cache deductions.
    sha256 is the content version and download integrity checksum; URLs are relative.
    """
    exam = db.get(Exam, exam_id)
    if exam is None or not exam.published:
        raise HTTPException(404, 'Exam not available')
    if type_id is not None:
        qt = db.get(QuestionType, type_id)
        if qt is None or (category is not None and qt.category != category):
            raise HTTPException(422, 'Unknown question type or category mismatch')
    materials = (select(Material.audio_id, Material.image_id)
        .join(Occurrence, Occurrence.material_id == Material.id)
        .join(QuestionType, QuestionType.id == Occurrence.type_id)
        .where(Occurrence.exam_id == exam_id, Occurrence.status == 'ready'))
    if category is not None:
        materials = materials.where(QuestionType.category == category)
    if type_id is not None:
        materials = materials.where(Occurrence.type_id == type_id)
    refs = materials.subquery()
    assets = db.scalars(select(Asset).where(
        Asset.id.in_(select(refs.c.audio_id).union(select(refs.c.image_id))))
        .order_by(Asset.kind, Asset.id)).all()
    if any(not asset.content_hash for asset in assets):
        raise HTTPException(503, 'Resource metadata is not ready')
    items = [dict(id=a.id, kind=a.kind, url=f'/api/v1/assets/{a.id}?v={a.content_hash}',
                  mime_type=a.mime_type, byte_size=a.byte_size, sha256=a.content_hash) for a in assets]
    return dict(exam_id=exam_id, items=items, resource_count=len(items),
                total_bytes=sum(a.byte_size for a in assets))
