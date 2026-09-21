import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from .database import get_db
from .models import Token, User, now

bearer = HTTPBearer(auto_error=False)
ACCOUNT_DISABLED_CODE = 'ACCOUNT_DISABLED'


def disabled_error(status_code):
    detail = {'code': ACCOUNT_DISABLED_CODE, 'message': 'Account is disabled'}
    headers = {'WWW-Authenticate': 'Bearer'} if status_code == 401 else None
    return HTTPException(status_code, detail, headers=headers)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${hashed}'


def verify_password(password, encoded):
    if not encoded:
        # Similar work for unknown accounts to reduce username timing disclosure.
        hash_password(password, '00' * 16)
        return False
    _, _, salt, _ = encoded.split('$')
    return hmac.compare_digest(hash_password(password, salt), encoded)


def token_digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def profile(user):
    return dict(id=user.id, username=user.username, level=user.level, is_guest=user.username is None, is_admin=user.is_admin)


def issue_token(db, user):
    secret = secrets.token_urlsafe(32)
    expires = now() + timedelta(days=30)
    db.add(Token(digest=token_digest(secret), user_id=user.id, expires_at=expires))
    db.commit()
    return dict(access_token=secret, token_type='bearer', expires_at=expires.isoformat()+'Z', user=profile(user))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    if credentials is None:
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    token = db.get(Token, token_digest(credentials.credentials))
    if token is None or token.expires_at <= now():
        raise HTTPException(401, 'Invalid or expired token', headers={'WWW-Authenticate': 'Bearer'})
    user = db.get(User, token.user_id)
    if user is None or user.username is None:
        raise HTTPException(401, 'Registered account required')
    if user.status != 'active':
        raise disabled_error(401)
    return user


def lock_user(db, user):
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()


def current_admin(user=Depends(current_user)):
    if not user.is_admin:
        raise HTTPException(403, 'Administrator access required')
    return user
