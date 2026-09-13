from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    level: Mapped[str] = mapped_column(String(2), default='N3')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Token(Base):
    __tablename__ = 'tokens'
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class QuestionType(Base):
    __tablename__ = 'question_types'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(24), index=True)
    name_zh: Mapped[str] = mapped_column(String(64))
    name_ja: Mapped[str] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer)


class Exam(Base):
    __tablename__ = 'exams'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(2), index=True)
    title: Mapped[str] = mapped_column(String(128))
    year: Mapped[int | None] = mapped_column(Integer)
    month: Mapped[int | None] = mapped_column(Integer)
    published: Mapped[bool] = mapped_column(Boolean)
    source_metadata: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('level', 'source_id'),)


class Asset(Base):
    __tablename__ = 'assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12))
    path: Mapped[str] = mapped_column(Text, unique=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class Material(Base):
    __tablename__ = 'materials'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content: Mapped[dict] = mapped_column(JSON)
    translation: Mapped[dict] = mapped_column(JSON)
    subtitles: Mapped[list] = mapped_column(JSON)
    audio_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'))
    image_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'))


class Question(Base):
    __tablename__ = 'questions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prompt: Mapped[dict] = mapped_column(JSON)
    explanation: Mapped[dict] = mapped_column(JSON)
    # Immutable content revisions keep in-progress practice valid across imports.


class Option(Base):
    __tablename__ = 'options'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey('questions.id'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    correct: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (UniqueConstraint('question_id', 'position'),)


class Occurrence(Base):
    __tablename__ = 'occurrences'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    exam_id: Mapped[str] = mapped_column(ForeignKey('exams.id'), index=True)
    question_id: Mapped[str] = mapped_column(ForeignKey('questions.id'), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey('materials.id'))
    type_id: Mapped[str | None] = mapped_column(ForeignKey('question_types.id'))
    level: Mapped[str] = mapped_column(String(2))
    group_key: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer)
    instruction: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[dict] = mapped_column(JSON)
    import_id: Mapped[str] = mapped_column(String(36), index=True)
    __table_args__ = (Index('ix_occurrences_catalog', 'level', 'type_id', 'status'),)


class ImportRun(Base):
    __tablename__ = 'import_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    summary: Mapped[dict] = mapped_column(JSON)


class QualityIssue(Base):
    __tablename__ = 'quality_issues'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    import_id: Mapped[str] = mapped_column(ForeignKey('import_runs.id'), index=True)
    occurrence_id: Mapped[str | None] = mapped_column(ForeignKey('occurrences.id'))
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    detail: Mapped[dict] = mapped_column(JSON)


class Practice(Base):
    __tablename__ = 'practices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    level: Mapped[str] = mapped_column(String(2))
    type_id: Mapped[str] = mapped_column(ForeignKey('question_types.id'))
    mode: Mapped[str] = mapped_column(String(16))
    requested_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default='active')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    request_key: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('user_id', 'request_key'),)


class PracticeItem(Base):
    __tablename__ = 'practice_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    practice_id: Mapped[str] = mapped_column(ForeignKey('practices.id'), index=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey('occurrences.id'))
    question_id: Mapped[str] = mapped_column(ForeignKey('questions.id'))
    position: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    chosen_option_id: Mapped[str | None] = mapped_column(ForeignKey('options.id'))
    correct: Mapped[bool | None] = mapped_column(Boolean)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('practice_id', 'position'), UniqueConstraint('practice_id', 'occurrence_id'))


class WrongQuestion(Base):
    __tablename__ = 'wrong_questions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(ForeignKey('occurrences.id'), primary_key=True)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
