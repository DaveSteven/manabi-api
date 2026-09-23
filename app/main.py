import os
from pathlib import Path
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from .auth import bearer, current_admin, current_user, disabled_error, hash_password, issue_token, lock_user, profile, token_digest, verify_password
from .database import ROOT, get_db
from .models import Asset, Exam, Occurrence, Practice, PracticeItem, Question, QuestionType, Token, User, WrongQuestion, now
from .practice import choose_occurrences, item_out, make_snapshot, practice_out
from .schemas import AdminPasswordReset, AdminUserDetailOut, AdminUserDisable, AdminUserOut, AdminUserStatsOut, AdminUserUpdate, AdminUsersOut, AnswerIn, Credentials, InternalAccountCreate, ItemOut, Level, PracticeCreate, PracticeOut, PracticeSummary, ProfileUpdate, TokenOut, UserOut
from .schemas import IntensiveListeningOut, ExamsOut, LevelsOut, PracticesOut, StatsOut, TypesOut, WrongQuestionsOut

app = FastAPI(title='Manabi API', version='1.0.0', description='JLPT 专项练习 API。所有时间为 UTC，媒体地址相对于 API 根地址。')
app.add_middleware(CORSMiddleware,
    allow_origins=[s.strip() for s in os.getenv('CORS_ORIGINS', '').split(',') if s.strip()],
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])
ASSETS_ROOT = Path(os.getenv('JLPT_ASSETS_DIR', ROOT.parent / 'mojitest_spider/data/assets')).resolve()
auth_requests = defaultdict(deque)
auth_lock = Lock()


@app.middleware('http')
async def guard_auth(request: Request, call_next):
    if request.url.path.startswith('/api/v1/auth/') and request.method == 'POST':
        key = request.client.host if request.client else 'unknown'
        timestamp = time.monotonic()
        with auth_lock:
            # Remove expired clients as well as requests, bounding idle-client memory.
            for old_key in list(auth_requests):
                if not auth_requests[old_key] or auth_requests[old_key][-1] < timestamp - 60:
                    del auth_requests[old_key]
            bucket = auth_requests[key]
            while bucket and bucket[0] < timestamp - 60:
                bucket.popleft()
            if len(bucket) >= 20:
                return JSONResponse({'detail': 'Too many authentication requests'}, status_code=429, headers={'Retry-After': '60'})
            bucket.append(timestamp)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if not request.url.path.startswith('/api/v1/assets/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never echo credentials or arbitrary request bodies in error responses.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(e['loc']), 'msg': e['msg'], 'type': e['type']} for e in exc.errors()]})


@app.get('/api/v1/health', tags=['System'])
def health(db=Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok', 'version': '1.0.0'}


@app.post('/api/v1/auth/register', response_model=TokenOut, status_code=201, tags=['Account'])
def register(payload: Credentials, db=Depends(get_db)):
    if os.getenv('ENABLE_REGISTRATION', 'true').lower() != 'true':
        raise HTTPException(403, 'Registration is disabled')
    user = User(username=payload.username.lower(), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Username already exists')
    return issue_token(db, user)


@app.post('/api/v1/admin/users', response_model=UserOut, status_code=201, tags=['Admin'],
          summary='创建内部账号（仅管理员）',
          description='先调用 /api/v1/auth/login，然后在 Authorize 中粘贴 access_token。创建的账号为普通用户，不开放管理员授权。')
def create_internal_account(payload: InternalAccountCreate, admin=Depends(current_admin), db=Depends(get_db)):
    display_name = payload.display_name.strip() if payload.display_name else ''
    user = User(username=payload.username.lower(), password_hash=hash_password(payload.password),
                level=payload.level, is_admin=False, display_name=display_name or None)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Username already exists')
    return profile(user)


ADMIN_USER_SORT_FIELDS = {
    'created_at': User.created_at,
    'updated_at': User.updated_at,
    'last_login_at': User.last_login_at,
    'username': User.username,
    'level': User.level,
    'status': User.status,
}


def admin_user_out(user):
    return dict(id=user.id, username=user.username, display_name=user.display_name, level=user.level,
                status=user.status, is_admin=user.is_admin,
                created_at=user.created_at.isoformat() + 'Z' if user.created_at else None,
                last_login_at=user.last_login_at.isoformat() + 'Z' if user.last_login_at else None)


def keyword_pattern(value):
    # Escape LIKE wildcards so the keyword is matched literally.
    escaped = value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped.lower()}%'


@app.get('/api/v1/admin/users', response_model=AdminUsersOut, tags=['Admin'],
         summary='用户列表（仅管理员）',
         description='支持关键词、等级、状态、管理员类型筛选，分页与白名单排序。不返回密码摘要或 token。')
def list_admin_users(keyword: str | None = Query(None, max_length=64),
                     level: Level | None = None,
                     status: str | None = Query(None, pattern='^(active|disabled|deleted)$'),
                     is_admin: bool | None = None,
                     sort: Literal['created_at', 'updated_at', 'last_login_at', 'username', 'level', 'status'] = 'created_at',
                     order: Literal['asc', 'desc'] = 'desc',
                     limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                     admin=Depends(current_admin), db=Depends(get_db)):
    filters = []
    term = keyword.strip() if keyword else ''
    if term:
        pattern = keyword_pattern(term)
        filters.append(or_(func.lower(User.username).like(pattern, escape='\\'),
                           func.lower(User.display_name).like(pattern, escape='\\')))
    if level:
        filters.append(User.level == level)
    if status:
        filters.append(User.status == status)
    if is_admin is not None:
        filters.append(User.is_admin.is_(is_admin))
    column = ADMIN_USER_SORT_FIELDS[sort]
    ordering = column.asc() if order == 'asc' else column.desc()
    rows = db.scalars(select(User).where(*filters).order_by(ordering, User.id).limit(limit).offset(offset))
    return {'items': [admin_user_out(user) for user in rows],
            'total': db.scalar(select(func.count()).select_from(User).where(*filters)),
            'limit': limit, 'offset': offset}


ADMIN_LEVEL_ORDER = ['N1', 'N2', 'N3', 'N4', 'N5']


def admin_visible_user_or_404(db, user_id):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, 'User not found')
    return user


def admin_user_detail_out(user):
    data = admin_user_out(user)
    data['updated_at'] = user.updated_at.isoformat() + 'Z' if user.updated_at else None
    return data


def edit_conflict():
    return HTTPException(409, {'code': 'EDIT_CONFLICT', 'message': 'User was modified by another administrator'})


@app.get('/api/v1/admin/users/{user_id}', response_model=AdminUserDetailOut, tags=['Admin'],
         summary='用户详情（仅管理员）',
         description='返回用户基础资料和用于并发校验的 updated_at，不包含密码摘要或 token。')
def admin_user_detail(user_id: str, admin=Depends(current_admin), db=Depends(get_db)):
    return admin_user_detail_out(admin_visible_user_or_404(db, user_id))


@app.patch('/api/v1/admin/users/{user_id}', response_model=AdminUserDetailOut, tags=['Admin'],
           summary='编辑用户资料（仅管理员）',
           description='仅允许修改用户名和显示名称；通过 updated_at 乐观锁检测并发修改，冲突返回 409。不可修改等级、管理员、状态、密码或 token。')
def update_admin_user(user_id: str, payload: AdminUserUpdate, admin=Depends(current_admin), db=Depends(get_db)):
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, 'User not found')
    if not ({'username', 'display_name'} & payload.model_fields_set):
        raise HTTPException(422, 'No updatable fields provided')
    current_version = user.updated_at.isoformat() + 'Z' if user.updated_at else None
    if payload.updated_at != current_version:
        raise edit_conflict()
    if 'username' in payload.model_fields_set:
        if payload.username is None:
            raise HTTPException(422, 'Username cannot be empty')
        user.username = payload.username.lower()
    if 'display_name' in payload.model_fields_set:
        display_name = payload.display_name.strip() if payload.display_name else ''
        user.display_name = display_name or None
    user.updated_at = now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {'code': 'USERNAME_TAKEN', 'message': 'Username already exists'})
    return admin_user_detail_out(user)


@app.post('/api/v1/admin/users/{user_id}/disable', response_model=AdminUserDetailOut, tags=['Admin'],
          summary='禁用用户（仅管理员）',
          description='禁用目标账号、写入 disabled_at 并撤销该用户全部 token。不能禁用自己，也不能禁用最后一个管理员。')
def disable_admin_user(user_id: str, payload: AdminUserDisable | None = None, admin=Depends(current_admin), db=Depends(get_db)):
    if user_id == admin.id:
        raise HTTPException(409, {'code': 'CANNOT_DISABLE_SELF', 'message': 'Cannot disable your own account'})
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, 'User not found')
    if target.is_admin:
        active_admins = list(db.scalars(select(User).where(User.status == 'active', User.is_admin.is_(True))
            .order_by(User.id).with_for_update()))
        if len(active_admins) <= 1:
            raise HTTPException(409, {'code': 'LAST_ADMIN_PROTECTED', 'message': 'Cannot disable the last active administrator'})
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, 'User not found')
    if user.status == 'deleted':
        raise HTTPException(409, {'code': 'USER_DELETED', 'message': 'Deleted user cannot be disabled'})
    if user.status != 'disabled':
        user.status = 'disabled'
        user.disabled_at = now()
        user.updated_at = now()
    db.execute(delete(Token).where(Token.user_id == user_id))
    db.commit()
    return admin_user_detail_out(user)


@app.post('/api/v1/admin/users/{user_id}/enable', response_model=AdminUserDetailOut, tags=['Admin'],
          summary='启用用户（仅管理员）',
          description='将已禁用账号恢复为 active 并清除 disabled_at。已删除账号不可启用。')
def enable_admin_user(user_id: str, admin=Depends(current_admin), db=Depends(get_db)):
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, 'User not found')
    if user.status == 'deleted':
        raise HTTPException(409, {'code': 'USER_DELETED', 'message': 'Deleted user cannot be enabled'})
    if user.status != 'active':
        user.status = 'active'
        user.disabled_at = None
        user.updated_at = now()
        db.commit()
    return admin_user_detail_out(user)


@app.post('/api/v1/admin/users/{user_id}/reset-password', response_model=AdminUserDetailOut, tags=['Admin'],
          summary='重置用户密码（仅管理员）',
          description='设置新密码并撤销该用户全部 token。不返回密码摘要，也不回显请求中的密码。')
def reset_admin_user_password(user_id: str, payload: AdminPasswordReset, admin=Depends(current_admin), db=Depends(get_db)):
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, 'User not found')
    if user.status == 'deleted':
        raise HTTPException(409, {'code': 'USER_DELETED', 'message': 'Deleted user cannot be updated'})
    user.password_hash = hash_password(payload.password)
    user.updated_at = now()
    db.execute(delete(Token).where(Token.user_id == user_id))
    db.commit()
    return admin_user_detail_out(user)


@app.post('/api/v1/admin/users/{user_id}/revoke-tokens', response_model=AdminUserDetailOut, tags=['Admin'],
          summary='撤销用户全部会话（仅管理员）',
          description='删除该用户全部 token，不修改密码或其他资料。')
def revoke_admin_user_tokens(user_id: str, admin=Depends(current_admin), db=Depends(get_db)):
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, 'User not found')
    if user.status == 'deleted':
        raise HTTPException(409, {'code': 'USER_DELETED', 'message': 'Deleted user cannot be updated'})
    db.execute(delete(Token).where(Token.user_id == user_id))
    db.commit()
    return admin_user_detail_out(user)


@app.get('/api/v1/admin/users/{user_id}/stats', response_model=AdminUserStatsOut, tags=['Admin'],
         summary='用户学习摘要（仅管理员）',
         description='按等级汇总练习次数、答题数、正确率与未解决错题数，不返回答案快照或内部字段。')
def admin_user_stats(user_id: str, admin=Depends(current_admin), db=Depends(get_db)):
    admin_visible_user_or_404(db, user_id)
    practice_counts = dict(db.execute(select(Practice.level, func.count(Practice.id))
        .where(Practice.user_id == user_id).group_by(Practice.level)).all())
    answered_counts = dict(db.execute(select(Practice.level, func.count(PracticeItem.id))
        .join(PracticeItem, PracticeItem.practice_id == Practice.id)
        .where(Practice.user_id == user_id, PracticeItem.answered_at.is_not(None)).group_by(Practice.level)).all())
    correct_counts = dict(db.execute(select(Practice.level, func.count())
        .join(PracticeItem, PracticeItem.practice_id == Practice.id)
        .where(Practice.user_id == user_id, PracticeItem.correct.is_(True)).group_by(Practice.level)).all())
    wrong_counts = dict(db.execute(select(Occurrence.level, func.count())
        .join(WrongQuestion, WrongQuestion.occurrence_id == Occurrence.id)
        .where(WrongQuestion.user_id == user_id, WrongQuestion.resolved.is_(False)).group_by(Occurrence.level)).all())
    levels = set(practice_counts) | set(answered_counts) | set(correct_counts) | set(wrong_counts)
    ordered = sorted(levels, key=lambda level: ADMIN_LEVEL_ORDER.index(level) if level in ADMIN_LEVEL_ORDER else len(ADMIN_LEVEL_ORDER))
    items = [dict(level=level, practices=practice_counts.get(level, 0), answered=answered_counts.get(level, 0),
                  correct=correct_counts.get(level, 0),
                  accuracy=correct_counts.get(level, 0) / answered_counts[level] if answered_counts.get(level) else 0.0,
                  wrong_questions=wrong_counts.get(level, 0)) for level in ordered]
    answered_total = sum(answered_counts.values())
    correct_total = sum(correct_counts.values())
    return {'practices': sum(practice_counts.values()), 'answered': answered_total, 'correct': correct_total,
            'accuracy': correct_total / answered_total if answered_total else 0.0,
            'wrong_questions': sum(wrong_counts.values()), 'levels': items}


@app.post('/api/v1/auth/login', response_model=TokenOut, tags=['Account'])
def login(payload: Credentials, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username.lower()))
    if not verify_password(payload.password, user.password_hash if user else None):
        raise HTTPException(401, 'Invalid username or password')
    if user.status != 'active':
        raise disabled_error(403)
    return issue_token(db, user)


@app.post('/api/v1/auth/logout', status_code=204, tags=['Account'])
def logout(user=Depends(current_user), credentials=Depends(bearer), db=Depends(get_db)):
    db.delete(db.get(Token, token_digest(credentials.credentials)))
    db.commit()


@app.post('/api/v1/auth/upgrade', response_model=UserOut, tags=['Account'])
def upgrade_guest(payload: Credentials, user=Depends(current_user), db=Depends(get_db)):
    lock_user(db, user)
    db.refresh(user)
    if user.username is not None:
        raise HTTPException(409, 'Account is already registered')
    user.username = payload.username.lower()
    user.password_hash = hash_password(payload.password)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Username already exists')
    return profile(user)


@app.get('/api/v1/me', response_model=UserOut, tags=['Account'])
def me(user=Depends(current_user)):
    return profile(user)


@app.patch('/api/v1/me', response_model=UserOut, tags=['Account'])
def update_me(payload: ProfileUpdate, user=Depends(current_user), db=Depends(get_db)):
    user.level = payload.level
    db.commit()
    return profile(user)


@app.get('/api/v1/catalog/levels', response_model=LevelsOut, tags=['Catalog'])
def levels(db=Depends(get_db)):
    rows = db.execute(select(Occurrence.level, func.count(), func.count(func.distinct(Occurrence.exam_id)))
        .where(Occurrence.status == 'ready').group_by(Occurrence.level).order_by(Occurrence.level))
    return {'items': [dict(level=level, question_count=count, exam_count=exams) for level, count, exams in rows]}


@app.get('/api/v1/catalog/types', response_model=TypesOut, tags=['Catalog'])
def types(level: Level, db=Depends(get_db)):
    rows = db.execute(select(QuestionType, func.count(Occurrence.id), func.count(func.distinct(Occurrence.group_key)))
        .join(Occurrence, Occurrence.type_id == QuestionType.id)
        .where(Occurrence.level == level, Occurrence.status == 'ready')
        .group_by(QuestionType.id).order_by(QuestionType.sort_order))
    return {'level': level, 'items': [dict(id=t.id, category=t.category, name_zh=t.name_zh, name_ja=t.name_ja,
        question_count=count, group_count=groups) for t, count, groups in rows]}


@app.get('/api/v1/exams', response_model=ExamsOut, tags=['Catalog'])
def exams(level: Level, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(get_db)):
    rows = db.scalars(select(Exam).options(defer(Exam.source_metadata)).where(Exam.level == level, Exam.published.is_(True))
        .order_by(Exam.year.desc(), Exam.month.desc(), Exam.id).limit(limit).offset(offset))
    return {'items': [dict(id=e.id, title=e.title, level=e.level, year=e.year, month=e.month) for e in rows],
            'total': db.scalar(select(func.count()).select_from(Exam).where(Exam.level == level, Exam.published.is_(True))),
            'limit': limit, 'offset': offset}


@app.get('/api/v1/assets/{asset_id}', tags=['Media'])
def get_asset(asset_id: str, v: str | None = None, db=Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, 'Asset not found')
    if v is not None and v != asset.content_hash:
        raise HTTPException(409, 'Resource version changed; refresh the resource list')
    path = (ASSETS_ROOT / asset.path).resolve()
    if not path.is_relative_to(ASSETS_ROOT) or not path.is_file():
        raise HTTPException(404, 'Asset not available')
    return FileResponse(path, media_type=asset.mime_type, headers={'Cache-Control': 'public, max-age=3600'})


def owned_practice(db, user, practice_id, lock=False):
    query = select(Practice).where(Practice.id == practice_id, Practice.user_id == user.id)
    if lock:
        query = query.with_for_update()
    practice = db.scalar(query)
    if practice is None:
        raise HTTPException(404, 'Practice not found')
    return practice


@app.post('/api/v1/practices', response_model=PracticeOut, status_code=201, tags=['Practice'])
def create_practice(payload: PracticeCreate, user=Depends(current_user), db=Depends(get_db)):
    lock_user(db, user)
    existing = db.scalar(select(Practice).where(Practice.user_id == user.id, Practice.request_key == payload.request_key))
    if existing:
        if (existing.level, existing.type_id, existing.requested_count, existing.mode) != (payload.level, payload.type_id, payload.count, payload.mode):
            raise HTTPException(409, 'Request key was used for different parameters')
        return practice_out(db, existing)
    if db.get(QuestionType, payload.type_id) is None:
        raise HTTPException(422, 'Unknown question type')
    selected = choose_occurrences(db, user, payload)
    practice = Practice(user_id=user.id, level=payload.level, type_id=payload.type_id, mode=payload.mode,
                        requested_count=payload.count, request_key=payload.request_key)
    db.add(practice)
    db.flush()
    for position, occurrence in enumerate(selected):
        db.add(PracticeItem(practice_id=practice.id, occurrence_id=occurrence.id,
            question_id=occurrence.question_id, position=position, snapshot=make_snapshot(db, occurrence)))
    db.commit()
    return practice_out(db, practice)


@app.get('/api/v1/practices', response_model=PracticesOut, tags=['Practice'])
def list_practices(status: str | None = Query(None, pattern='^(active|completed|abandoned)$'),
                   limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                   user=Depends(current_user), db=Depends(get_db)):
    filters = [Practice.user_id == user.id]
    if status:
        filters.append(Practice.status == status)
    rows = list(db.scalars(select(Practice).where(*filters).order_by(Practice.created_at.desc(), Practice.id).limit(limit).offset(offset)))
    return {'items': [practice_out(db, p, False) for p in rows],
            'total': db.scalar(select(func.count()).select_from(Practice).where(*filters)), 'limit': limit, 'offset': offset}


@app.get('/api/v1/practices/{practice_id}', response_model=PracticeOut, tags=['Practice'])
def get_practice(practice_id: str, user=Depends(current_user), db=Depends(get_db)):
    return practice_out(db, owned_practice(db, user, practice_id))


@app.get('/api/v1/practices/{practice_id}/items/{item_id}/listening', response_model=IntensiveListeningOut, tags=['Practice'])
def intensive_listening(practice_id: str, item_id: str, user=Depends(current_user), db=Depends(get_db)):
    practice = owned_practice(db, user, practice_id)
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == item_id, PracticeItem.practice_id == practice.id))
    if item is None:
        raise HTTPException(404, 'Practice item not found')
    audio = item.snapshot['public']['material'].get('audio_url')
    if not audio:
        raise HTTPException(404, 'Listening audio not available')
    segments = [s for s in item.snapshot['private'].get('subtitles', [])
                if s['start_ms'] >= 0 and s['end_ms'] > s['start_ms'] and s['text'].strip()]
    return dict(audio_url=audio, segments=sorted(segments, key=lambda s: s['start_ms']))


@app.post('/api/v1/practices/{practice_id}/items/{item_id}/answer', response_model=ItemOut, tags=['Practice'])
def answer(practice_id: str, item_id: str, payload: AnswerIn, user=Depends(current_user), db=Depends(get_db)):
    lock_user(db, user)
    practice = owned_practice(db, user, practice_id, True)
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == item_id, PracticeItem.practice_id == practice.id))
    if item is None:
        raise HTTPException(404, 'Practice item not found')
    if item.answered_at is not None:
        if item.chosen_option_id != payload.option_id:
            raise HTTPException(409, 'Answer is already submitted')
        return item_out(item)
    if practice.status != 'active':
        raise HTTPException(409, 'Practice is not active')
    if payload.option_id not in {o['id'] for o in item.snapshot['public']['options']}:
        raise HTTPException(422, 'Option does not belong to this question')
    item.chosen_option_id = payload.option_id
    item.correct = payload.option_id == item.snapshot['private']['correct_option_id']
    item.answered_at = now()
    item.elapsed_ms = payload.elapsed_ms
    wrong = db.get(WrongQuestion, (user.id, item.occurrence_id))
    if not item.correct:
        if wrong is None:
            wrong = WrongQuestion(user_id=user.id, occurrence_id=item.occurrence_id, wrong_count=0)
            db.add(wrong)
        wrong.wrong_count += 1
        wrong.resolved = False
        wrong.updated_at = now()
    elif wrong is not None:
        wrong.resolved = True
        wrong.updated_at = now()
    db.flush()
    remaining = db.scalar(select(func.count()).select_from(PracticeItem).where(
        PracticeItem.practice_id == practice.id, PracticeItem.answered_at.is_(None)))
    if remaining == 0:
        practice.status = 'completed'
        practice.completed_at = now()
    db.commit()
    return item_out(item)


@app.post('/api/v1/practices/{practice_id}/abandon', response_model=PracticeSummary, tags=['Practice'])
def abandon(practice_id: str, user=Depends(current_user), db=Depends(get_db)):
    lock_user(db, user)
    practice = owned_practice(db, user, practice_id, True)
    if practice.status == 'completed':
        raise HTTPException(409, 'Practice is already completed')
    practice.status = 'abandoned'
    db.commit()
    return practice_out(db, practice, False)


@app.get('/api/v1/wrong-questions', response_model=WrongQuestionsOut, tags=['Review'])
def wrong_questions(level: Level | None = None, type_id: str | None = None, resolved: bool = False,
                    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                    user=Depends(current_user), db=Depends(get_db)):
    filters = [WrongQuestion.user_id == user.id, WrongQuestion.resolved == resolved]
    if level:
        filters.append(Occurrence.level == level)
    if type_id:
        filters.append(Occurrence.type_id == type_id)
    query = select(WrongQuestion, Occurrence).options(defer(Occurrence.source)).join(Occurrence, WrongQuestion.occurrence_id == Occurrence.id).where(*filters)
    rows = db.execute(query.order_by(WrongQuestion.updated_at.desc(), Occurrence.id).limit(limit).offset(offset))
    return {'items': [dict(occurrence_id=o.id, level=o.level, type_id=o.type_id,
        prompt=db.get(Question, o.question_id).prompt, wrong_count=w.wrong_count, resolved=w.resolved,
        available=o.status == 'ready', updated_at=w.updated_at.isoformat()+'Z') for w, o in rows],
        'total': db.scalar(select(func.count()).select_from(query.subquery())), 'limit': limit, 'offset': offset}


@app.get('/api/v1/me/stats', response_model=StatsOut, tags=['Review'])
def stats(user=Depends(current_user), db=Depends(get_db)):
    rows = db.execute(select(Practice.level, Practice.type_id, func.count(PracticeItem.id),
        func.sum(PracticeItem.elapsed_ms)).join(PracticeItem, PracticeItem.practice_id == Practice.id)
        .where(Practice.user_id == user.id, PracticeItem.answered_at.is_not(None)).group_by(Practice.level, Practice.type_id))
    correct_counts = {(level, qt): count for level, qt, count in db.execute(select(Practice.level, Practice.type_id, func.count())
        .join(PracticeItem, PracticeItem.practice_id == Practice.id)
        .where(Practice.user_id == user.id, PracticeItem.correct.is_(True)).group_by(Practice.level, Practice.type_id))}
    return {'items': [dict(level=level, type_id=qt, answered=count, correct=correct_counts.get((level, qt), 0),
        accuracy=correct_counts.get((level, qt), 0) / count, elapsed_ms=elapsed or 0) for level, qt, count, elapsed in rows]}


from .exam_practice import router as exam_practice_router
app.include_router(exam_practice_router)
