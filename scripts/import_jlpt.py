"""Import normalized JLPT occurrences without mutating legacy data.

Run from manabi_api: python -m scripts.import_jlpt --report data/import-report.json
"""
import argparse
from hashlib import file_digest
from collections import Counter, defaultdict
import json
import mimetypes
from pathlib import Path
import re

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.content import digest, rich, stable_id, subtitles
from app.database import ROOT, SessionLocal
from app.models import Asset, Exam, ImportRun, Material, Occurrence, Option, QualityIssue, Question, QuestionType, uid
from app.taxonomy import TYPES, type_id


def upsert(db, model, records):
    rows = list(records.values())
    insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    for offset in range(0, len(rows), 100):
        stmt = insert(model).values(rows[offset:offset + 100])
        db.execute(stmt.on_conflict_do_update(index_elements=['id'],
                   set_={c.name: getattr(stmt.excluded, c.name) for c in model.__table__.columns if c.name != 'id'}))


def run_import(db, data_dir, report_path, legacy_path=None):
    data_dir = Path(data_dir).resolve()
    assets_root = (data_dir / 'assets').resolve()
    run_id = uid()
    issues = []
    tables = {m: {} for m in [QuestionType, Exam, Asset, Material, Question, Option, Occurrence]}
    for order, (key, category, zh, ja) in enumerate(TYPES):
        tables[QuestionType][key] = dict(id=key, category=category, name_zh=zh, name_ja=ja, sort_order=order)

    def issue(oid, code, detail, severity='warning'):
        issues.append(dict(id=uid(), import_id=run_id, occurrence_id=oid,
                           code=code, severity=severity, detail=detail))

    def asset(raw_path, kind, oid):
        if not raw_path:
            return None
        raw_path = str(raw_path).replace('\\', '/')
        marker = '/data/assets/'
        relative = raw_path.split(marker, 1)[1] if marker in raw_path else raw_path
        path = (assets_root / relative).resolve()
        if not path.is_relative_to(assets_root) or not path.is_file() or not path.stat().st_size:
            issue(oid, 'missing_asset', {'kind': kind, 'path': relative}, 'error')
            return None
        relative = path.relative_to(assets_root).as_posix()
        aid = stable_id('asset', relative)
        if aid in tables[Asset]:
            return aid
        with path.open('rb') as stream:
            content_hash = file_digest(stream, 'sha256').hexdigest()
        tables[Asset][aid] = dict(content_hash=content_hash, id=aid, kind=kind, path=relative,
            mime_type=mimetypes.guess_type(path)[0] or ('audio/mpeg' if kind == 'audio' else 'application/octet-stream'),
            byte_size=path.stat().st_size)
        return aid

    legacy = {}
    legacy_options = defaultdict(list)
    previous = db.scalar(select(ImportRun).order_by(ImportRun.created_at.desc()).limit(1))
    if previous and previous.summary.get('legacy_snapshot_hash') and not legacy_path:
        raise ValueError('Previous import used a legacy snapshot; supply it again to preserve version review checks')
    if legacy_path:
        old = json.loads(Path(legacy_path).read_text())
        legacy = {q['external_id']: q for q in old['questions']}
        for option in old['options']:
            legacy_options[option['question_id']].append(option)

    source_ids = defaultdict(list)
    files = {}
    source_count = 0
    levels = []
    for level_dir in sorted((data_dir / 'normalized').iterdir()):
        if level_dir.name not in {'N2', 'N3'}:
            continue
        level = level_dir.name
        levels.append(level)
        ep, qp = level_dir / 'exams_with_assets.json', level_dir / 'questions_with_assets.json'
        source_exams, source_questions = json.loads(ep.read_text()), json.loads(qp.read_text())
        files[str(ep.relative_to(data_dir))] = digest(source_exams)
        files[str(qp.relative_to(data_dir))] = digest(source_questions)
        source_count += len(source_questions)
        exams = {e['objectId']: e for e in source_exams}
        layers = {}
        for exam in source_exams:
            eid = stable_id('exam', level, exam['objectId'])
            match = re.search(r'(\d{4})年(\d{1,2})月', exam['title'])
            tables[Exam][eid] = dict(id=eid, source_id=exam['objectId'], level=level,
                title=exam['title'], year=int(match[1]) if match else None,
                month=int(match[2]) if match else None, published=bool(exam.get('isPublished', True)),
                source_metadata={k: v for k, v in exam.items() if k != 'layers'})
            for layer in exam.get('layers', []):
                layers[(exam['objectId'], layer['objectId'])] = layer
        positions = Counter()
        repetitions = Counter()
        for source in source_questions:
            source_exam, source_layer, source_id = source['exam_id'], source['layer_id'], source['question_id']
            positions[(source_exam, source_layer)] += 1
            position = positions[(source_exam, source_layer)]
            # Scope upstream IDs to their exam/layer; ordering changes must not retarget wrong questions.
            repetition_key = (source_exam, source_layer, source_id)
            repetitions[repetition_key] += 1
            oid = stable_id('occurrence', level, source_exam, source_layer, source_id, repetitions[repetition_key])
            issue_start = len(issues)
            source_ids[source_id].append(oid)
            exam = exams.get(source_exam)
            layer = layers.get((source_exam, source_layer))
            if exam is None or layer is None:
                raise ValueError(f'Orphan source question: {level}/{source_exam}/{source_layer}/{source_id}')
            code = source.get('question_type')
            layer_code = layer.get('questionType')
            qt = type_id(level, code)
            if qt is None:
                issue(oid, 'unknown_type', {'code': code}, 'error')
            if type_id(level, layer_code) != qt:
                issue(oid, 'type_conflict', {'question_type': code, 'layer_type': layer_code}, 'error')
            elif layer_code != code:
                issue(oid, 'type_alias', {'question_type': code, 'layer_type': layer_code, 'resolved_type': qt})
            option_values = source.get('options') or []
            try:
                answer = int(source.get('right_answer'))
            except (TypeError, ValueError):
                answer = -1
            if len(option_values) not in {3, 4} or not 0 <= answer < len(option_values):
                issue(oid, 'invalid_answer', {'option_count': len(option_values), 'answer': answer}, 'error')
            segments, invalid = subtitles(source.get('subtitle'))
            if invalid:
                issue(oid, 'invalid_subtitle_segments', {'count': invalid})
            if not source.get('analysis'):
                issue(oid, 'missing_explanation', {})
            audio = asset(source.get('media_path'), 'audio', oid)
            image = asset(source.get('image_path'), 'image', oid)
            if qt and qt.startswith('listening_') and not audio:
                issue(oid, 'missing_listening_audio', {}, 'error')
            # Inline images need explicit asset conversion; never silently drop essential content.
            if any(re.search(r'<img\b', str(source.get(f) or ''), re.I)
                   for f in ['title', 'passage', 'analysis', 'translation']):
                issue(oid, 'inline_image_requires_review', {}, 'error')
            old = legacy.get(source_id)
            if old:
                differences = [field for field in ['title', 'passage', 'analysis', 'translation', 'subtitle']
                               if (old.get(field) or '') != (source.get(field) or '')]
                old_opts = sorted(legacy_options[old['id']], key=lambda o: o['source_order'])
                if [o['text'] for o in old_opts] != option_values:
                    differences.append('options')
                if [o['source_order'] for o in old_opts if o['is_correct']] != [answer]:
                    differences.append('answer')
                if differences:
                    issue(oid, 'legacy_version_difference', {'fields': differences}, 'error')
            material_data = dict(content=rich(source.get('passage')), translation=rich(source.get('translation')),
                                 subtitles=segments, audio_id=audio, image_id=image)
            mid = stable_id('material', material_data)
            tables[Material][mid] = dict(id=mid, **material_data)
            content = dict(prompt=rich(source.get('title')), explanation=rich(source.get('analysis')))
            clean_options = [rich(value) for value in option_values]
            checksum = digest([source_id, content, clean_options, answer, material_data])
            qid = stable_id('question', checksum)
            tables[Question][qid] = dict(id=qid, content_hash=checksum, **content)
            for i, value in enumerate(clean_options):
                opid = stable_id('option', qid, i)
                tables[Option][opid] = dict(id=opid, question_id=qid, position=i, content=value, correct=i == answer)
            group = stable_id('group', level, source_exam, source_layer, source.get('parent_id') or oid)
            tables[Occurrence][oid] = dict(id=oid, exam_id=stable_id('exam', level, source_exam),
                question_id=qid, material_id=mid, type_id=qt, level=level, group_key=group,
                position=position, instruction=rich(layer.get('title')),
                status='review' if any(i['severity'] == 'error' for i in issues[issue_start:]) else ('ready' if exam.get('isPublished', True) else 'hidden'),
                source={'question_id': source_id, 'exam_id': source_exam, 'layer_id': source_layer,
                        'record_hash': digest(source), 'record': source}, import_id=run_id)

    if not source_count:
        raise ValueError('No supported JLPT source files found; import aborted')
    for source_id, occurrences in source_ids.items():
        if len(occurrences) > 1:
            issue(occurrences[0], 'reused_source_id', {'source_id': source_id, 'occurrence_ids': occurrences})
    groups = defaultdict(list)
    for row in tables[Occurrence].values():
        groups[row['group_key']].append(row)
    for rows in groups.values():
        if any(r['status'] == 'review' for r in rows):
            for row in rows:
                if row['status'] != 'review':
                    row['status'] = 'review'
                    issue(row['id'], 'group_contains_review_item', {}, 'error')
        if len({r['type_id'] for r in rows}) > 1:
            for row in rows:
                row['status'] = 'review'
                issue(row['id'], 'mixed_type_group', {}, 'error')
    summary = dict(import_id=run_id, levels=levels, source_records=source_count,
        source_unique_ids=len(source_ids), exams=len(tables[Exam]), occurrences=len(tables[Occurrence]),
        question_revisions=len(tables[Question]), materials=len(tables[Material]), assets=len(tables[Asset]),
        status_counts=dict(Counter(r['status'] for r in tables[Occurrence].values())),
        issues_by_code=dict(Counter(i['code'] for i in issues)), source_hashes=files,
        legacy_snapshot_hash=digest(json.loads(Path(legacy_path).read_text())) if legacy_path else None)
    # One transaction: errors leave the previous published data intact.
    db.add(ImportRun(id=run_id, summary=summary))
    db.flush()
    for model in [QuestionType, Exam, Asset, Material, Question, Option, Occurrence]:
        upsert(db, model, tables[model])
    db.execute(update(Occurrence).where(Occurrence.level.in_(levels), Occurrence.import_id != run_id).values(status='retired'))
    if issues:
        for offset in range(0, len(issues), 100):
            db.execute(QualityIssue.__table__.insert(), issues[offset:offset+100])
    db.commit()
    report = dict(summary=summary, issues=issues)
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT.parent / 'mojitest_spider/data')
    parser.add_argument('--report', type=Path, default=ROOT / 'data/import-report.json')
    default_legacy = ROOT / 'data/legacy-jlpt-snapshot.json'
    parser.add_argument('--legacy-snapshot', type=Path, default=default_legacy if default_legacy.exists() else None)
    args = parser.parse_args()
    with SessionLocal() as session:
        print(json.dumps(run_import(session, args.data_dir, args.report, args.legacy_snapshot), ensure_ascii=False, indent=2))
