"""Backfill/refresh media hashes: python -m scripts.hash_assets [--assets-dir PATH].

Run after migration and whenever media files are replaced outside the importer.
All changes commit together; missing/unsafe files abort without partial metadata.
"""
import argparse
from hashlib import file_digest
import os
from pathlib import Path

from sqlalchemy import select
from app.database import ROOT, SessionLocal
from app.models import Asset


def hash_assets(db, root):
    root = Path(root).resolve()
    count = 0
    for asset in db.scalars(select(Asset).order_by(Asset.id)):
        path = (root / asset.path).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Asset unavailable: {asset.id}')
        with path.open('rb') as stream:
            asset.content_hash = file_digest(stream, 'sha256').hexdigest()
        asset.byte_size = path.stat().st_size
        count += 1
    db.flush()
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets-dir', type=Path, default=Path(os.getenv(
        'JLPT_ASSETS_DIR', ROOT.parent / 'mojitest_spider/data/assets')))
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        count = hash_assets(db, args.assets_dir)
    print(f'Updated {count} resource hashes')
