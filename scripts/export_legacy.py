"""Read-only export of legacy JLPT content for version comparison; no user data."""
import argparse
from pathlib import Path
import subprocess

from app.database import ROOT


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--container', default='japanese_study_db')
    parser.add_argument('--output', type=Path, default=ROOT/'data/legacy-jlpt-snapshot.json')
    args = parser.parse_args()
    sql = "SELECT json_build_object('questions',(SELECT json_agg(q) FROM exam_questions q),'options',(SELECT json_agg(o) FROM exam_options o),'layers',(SELECT json_agg(l) FROM exam_layers l),'exams',(SELECT json_agg(e) FROM exams e));"
    result = subprocess.run(['docker', 'exec', args.container, 'sh', '-c',
        'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"', 'sh', sql],
        check=True, capture_output=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result.stdout)
    print(f'Exported JLPT content only: {args.output}')
