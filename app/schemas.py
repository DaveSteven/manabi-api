from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Level = Literal['N1', 'N2', 'N3', 'N4', 'N5']


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=8, max_length=128)


class InternalAccountCreate(Credentials):
    model_config = ConfigDict(extra='forbid')
    display_name: str | None = Field(default=None, max_length=64)
    level: Level = 'N5'


class ProfileUpdate(BaseModel):
    level: Level


class PracticeCreate(BaseModel):
    level: Level
    type_id: str = Field(min_length=1, max_length=64)
    count: int = Field(default=10, ge=1, le=50)
    mode: Literal['normal', 'wrong'] = 'normal'
    request_key: str = Field(min_length=8, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')


class AnswerIn(BaseModel):
    option_id: str = Field(min_length=36, max_length=36)
    elapsed_ms: int = Field(default=0, ge=0, le=86400000)


class RichText(BaseModel):
    text: str
    html: str


class UserOut(BaseModel):
    id: str
    username: str | None
    level: str
    is_guest: bool
    is_admin: bool = False


class TokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_at: str
    user: UserOut


class AdminUserOut(BaseModel):
    id: str
    username: str | None
    display_name: str | None
    level: str
    status: str
    is_admin: bool
    created_at: str | None
    last_login_at: str | None


class AdminUsersOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    limit: int
    offset: int


class AdminUserStatsLevel(BaseModel):
    level: str
    practices: int
    answered: int
    correct: int
    accuracy: float
    wrong_questions: int


class AdminUserStatsOut(BaseModel):
    practices: int
    answered: int
    correct: int
    accuracy: float
    wrong_questions: int
    levels: list[AdminUserStatsLevel]


class OptionOut(BaseModel):
    id: str
    position: int
    content: RichText


class MaterialOut(BaseModel):
    id: str
    content: RichText
    audio_url: str | None
    image_url: str | None


class SourceOut(BaseModel):
    exam_id: str
    exam_title: str
    level: str
    section: RichText
    position: int


class QuestionOut(BaseModel):
    id: str
    occurrence_id: str
    type_id: str
    group_id: str
    prompt: RichText
    material: MaterialOut
    options: list[OptionOut]
    source: SourceOut


class SubtitleOut(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class FeedbackOut(BaseModel):
    chosen_option_id: str
    correct_option_id: str
    is_correct: bool
    explanation: RichText
    explanation_available: bool
    translation: RichText
    subtitles: list[SubtitleOut]
    answered_at: str
    elapsed_ms: int


class ItemOut(BaseModel):
    id: str
    position: int
    question: QuestionOut
    feedback: FeedbackOut | None


class PracticeSummary(BaseModel):
    id: str
    level: str
    type_id: str
    mode: str
    status: str
    requested_count: int
    total: int
    answered: int
    correct: int
    elapsed_ms: int
    created_at: str
    completed_at: str | None
    next_item_id: str | None


class PracticeOut(PracticeSummary):
    items: list[ItemOut]


class LevelOut(BaseModel):
    level: str
    question_count: int
    exam_count: int


class LevelsOut(BaseModel):
    items: list[LevelOut]


class TypeOut(BaseModel):
    id: str
    category: str
    name_zh: str
    name_ja: str
    question_count: int
    group_count: int


class TypesOut(BaseModel):
    level: str
    items: list[TypeOut]


class ExamOut(BaseModel):
    id: str
    title: str
    level: str
    year: int | None
    month: int | None


class ExamsOut(BaseModel):
    items: list[ExamOut]
    total: int
    limit: int
    offset: int


class PracticesOut(BaseModel):
    items: list[PracticeSummary]
    total: int
    limit: int
    offset: int


class WrongOut(BaseModel):
    occurrence_id: str
    level: str
    type_id: str | None
    prompt: RichText
    wrong_count: int
    resolved: bool
    available: bool
    updated_at: str


class WrongQuestionsOut(BaseModel):
    items: list[WrongOut]
    total: int
    limit: int
    offset: int


class StatsItem(BaseModel):
    level: str
    type_id: str
    answered: int
    correct: int
    accuracy: float
    elapsed_ms: int


class StatsOut(BaseModel):
    items: list[StatsItem]


class IntensiveListeningOut(BaseModel):
    audio_url: str
    segments: list[SubtitleOut]


Category = Literal['vocabulary', 'grammar', 'reading', 'listening']


class ExamProgressOut(ExamOut):
    total: int
    answered: int
    correct: int
    status: str


class ExamPracticeList(BaseModel):
    items: list[ExamProgressOut]


class ExamTypeProgressOut(BaseModel):
    id: str
    name_zh: str
    name_ja: str
    category: str
    total: int
    answered: int
    correct: int
    status: str
    practice_id: str | None


class ExamPracticeTypes(BaseModel):
    items: list[ExamTypeProgressOut]


class ResourceOut(BaseModel):
    id: str
    kind: Literal['audio', 'image']
    url: str
    mime_type: str
    byte_size: int
    sha256: str


class ExamResourcesOut(BaseModel):
    exam_id: str
    items: list[ResourceOut]
    resource_count: int
    total_bytes: int
