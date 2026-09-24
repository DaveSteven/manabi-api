import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = 'b72d06e914aa'
HEAD_REVISION = 'd4a8f2b1c6e9'
USER_STATUS_COLUMNS = {'status', 'display_name', 'updated_at', 'last_login_at', 'disabled_at'}


def run_alembic(db_path, *args):
    env = dict(os.environ, DATABASE_URL=f'sqlite:///{db_path}')
    result = subprocess.run([sys.executable, '-m', 'alembic', *args],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    return result


def user_columns(db_path):
    with sqlite3.connect(db_path) as connection:
        return {row[1] for row in connection.execute('PRAGMA table_info(users)')}


def current_revision(db_path):
    with sqlite3.connect(db_path) as connection:
        row = connection.execute('SELECT version_num FROM alembic_version').fetchone()
    return row[0] if row else None


def test_migration_upgrades_empty_database(tmp_path):
    db_path = tmp_path / 'fresh.db'
    run_alembic(db_path, 'upgrade', 'head')
    assert current_revision(db_path) == HEAD_REVISION
    assert USER_STATUS_COLUMNS <= user_columns(db_path)


def test_existing_users_migrate_to_active(tmp_path):
    db_path = tmp_path / 'existing.db'
    run_alembic(db_path, 'upgrade', PREVIOUS_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO users (id, username, password_hash, level, created_at, is_admin) VALUES (?, ?, ?, ?, ?, ?)",
            ('legacy-id', 'legacy', 'pbkdf2$hash', 'N3', '2025-01-02 03:04:05', 0))
        connection.commit()
    run_alembic(db_path, 'upgrade', 'head')
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, updated_at, last_login_at, disabled_at, display_name FROM users WHERE id = 'legacy-id'").fetchone()
    assert row == ('active', '2025-01-02 03:04:05', None, None, None)


def test_migration_downgrade_removes_user_status_fields(tmp_path):
    db_path = tmp_path / 'downgrade.db'
    run_alembic(db_path, 'upgrade', 'head')
    run_alembic(db_path, 'downgrade', PREVIOUS_REVISION)
    assert current_revision(db_path) == PREVIOUS_REVISION
    assert not (USER_STATUS_COLUMNS & user_columns(db_path))
