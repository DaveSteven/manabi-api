from collections import defaultdict
import random

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import defer

from .models import Exam, Material, Occurrence, Option, PracticeItem, Question, WrongQuestion


def make_snapshot(db, occurrence):
    question = db.get(Question, occurrence.question_id)
    material = db.get(Material, occurrence.material_id)
    exam = db.get(Exam, occurrence.exam_id)
    options = list(db.scalars(select(Option).where(Option.question_id == question.id).order_by(Option.position)))
    correct = [option.id for option in options if option.correct]
    if len(correct) != 1:
        raise HTTPException(409, 'Question is not ready for practice')
    public = dict(id=question.id, occurrence_id=occurrence.id, type_id=occurrence.type_id,
        group_id=occurrence.group_key, prompt=question.prompt,
        material=dict(id=material.id, content=material.content,
                      audio_url=f'/api/v1/assets/{material.audio_id}' if material.audio_id else None,
                      image_url=f'/api/v1/assets/{material.image_id}' if material.image_id else None),
        options=[dict(id=o.id, position=o.position, content=o.content) for o in options],
        source=dict(exam_id=exam.id, exam_title=exam.title, level=exam.level,
                    section=occurrence.instruction, position=occurrence.position))
    private = dict(correct_option_id=correct[0], explanation=question.explanation,
                   explanation_available=bool(question.explanation['text']),
                   translation=material.translation, subtitles=material.subtitles)
    return dict(public=public, private=private)


def choose_occurrences(db, user, payload):
    rows = list(db.scalars(select(Occurrence).options(defer(Occurrence.source)).where(Occurrence.level == payload.level,
        Occurrence.type_id == payload.type_id, Occurrence.status == 'ready')))
    groups = defaultdict(list)
    for row in rows:
        groups[row.group_key].append(row)
    if payload.mode == 'wrong':
        wrong_ids = set(db.scalars(select(WrongQuestion.occurrence_id).where(
            WrongQuestion.user_id == user.id, WrongQuestion.resolved.is_(False))))
        groups = {key: value for key, value in groups.items() if any(r.id in wrong_ids for r in value)}
    choices = list(groups.values())
    random.SystemRandom().shuffle(choices)
    selected = []
    seen = set()
    for group in choices:
        # Reused identical questions should not occur twice within a practice.
        if any(row.question_id in seen for row in group):
            continue
        selected.extend(sorted(group, key=lambda r: r.position))
        seen.update(r.question_id for r in group)
        if len(selected) >= payload.count:
            break
    if not selected:
        raise HTTPException(404, 'No eligible questions for this selection')
    return selected


def feedback(item):
    if item.answered_at is None:
        return None
    return dict(**item.snapshot['private'], chosen_option_id=item.chosen_option_id,
                is_correct=item.correct, answered_at=item.answered_at.isoformat()+'Z', elapsed_ms=item.elapsed_ms)


def item_out(item):
    return dict(id=item.id, position=item.position, question=item.snapshot['public'], feedback=feedback(item))


def practice_out(db, practice, include_items=True):
    items = list(db.scalars(select(PracticeItem).where(PracticeItem.practice_id == practice.id).order_by(PracticeItem.position)))
    result = dict(id=practice.id, level=practice.level, type_id=practice.type_id, mode=practice.mode,
        status=practice.status, requested_count=practice.requested_count,
        total=len(items), answered=sum(i.answered_at is not None for i in items),
        correct=sum(i.correct is True for i in items), elapsed_ms=sum(i.elapsed_ms or 0 for i in items),
        created_at=practice.created_at.isoformat()+'Z',
        completed_at=practice.completed_at.isoformat()+'Z' if practice.completed_at else None,
        next_item_id=next((i.id for i in items if i.answered_at is None), None) if practice.status == 'active' else None)
    if include_items:
        result['items'] = [item_out(i) for i in items]
    return result
