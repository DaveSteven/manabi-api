"""Provision an administrator through server access, preserving existing study data."""
import argparse
from getpass import getpass

from sqlalchemy import delete, select
from app.auth import hash_password
from app.database import SessionLocal
from app.models import Token, User
from app.schemas import Credentials


def set_admin(db, username, password):
    credentials = Credentials(username=username, password=password)
    user = db.scalar(select(User).where(User.username == credentials.username.lower()).with_for_update())
    if user is None:
        user = User(username=credentials.username.lower())
        db.add(user)
        db.flush()
    user.password_hash = hash_password(credentials.password)
    user.is_admin = True
    # Password replacement revokes previously issued sessions, but keeps all practice data.
    db.execute(delete(Token).where(Token.user_id == user.id))
    db.commit()
    return user.id


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('username')
    args = parser.parse_args()
    password = getpass('New administrator password: ')
    try:
        Credentials(username=args.username, password=password)
    except ValueError:
        raise SystemExit('Invalid username or password length (8–128 characters).')
    with SessionLocal() as db:
        set_admin(db, args.username, password)
    print('Administrator updated; previous sessions revoked. Study data preserved.')
