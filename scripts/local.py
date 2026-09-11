"""Run local development commands against the independent Docker PostgreSQL DB.

Examples: python -m scripts.local migrate | import | serve
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    password = next(line.split('=', 1)[1] for line in (ROOT / '.env').read_text().splitlines()
                    if line.startswith('POSTGRES_PASSWORD='))
    env = dict(os.environ, DATABASE_URL=f'postgresql+psycopg://manabi:{password}@127.0.0.1:5433/manabi')
    if action == 'test':
        env['TEST_POSTGRES_URL'] = env['DATABASE_URL']
    commands = {
        'migrate': [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
        'import': [sys.executable, '-m', 'scripts.import_jlpt'],
        'serve': [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001'],
        'test': [sys.executable, '-m', 'pytest'],
        'verify': [sys.executable, '-m', 'scripts.verify'],
    }
    if action not in commands:
        raise SystemExit('Usage: python -m scripts.local migrate|import|serve|test|verify [arguments]')
    raise SystemExit(subprocess.call(commands[action] + sys.argv[2:], cwd=ROOT, env=env))
