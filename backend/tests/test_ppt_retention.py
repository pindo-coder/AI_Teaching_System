import json
import os
from pathlib import Path
from time import time

import pytest

from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.ppt_retention_service import PptRetentionService


def fixture(db):
    user = User(username='retention-owner', role='teacher', password_hash='not-used')
    db.add(user); db.flush()
    run = AgentRun(created_by=user.id, agent_type='teacher_lesson_prep', status='completed', output_data={})
    db.add(run); db.commit()
    root = Path(settings.generated_artifact_directory)
    root.mkdir()
    return run, root, PptRetentionService(db, root)


def old_directory(root, relative):
    path = root / relative
    path.mkdir(parents=True)
    (path / 'keep.txt').write_text('recoverable')
    for item in [path, *path.rglob('*')]:
        os.utime(item, (time() - 60 * 86400, time() - 60 * 86400))
    return path


def test_retention_is_dry_run_and_keeps_current_history_and_legacy(db):
    run, root, service = fixture(db)
    orphan = old_directory(root, f'{run.id}/ppt/{"a" * 32}')
    current = old_directory(root, f'{run.id}/ppt/{"b" * 32}')
    history = old_directory(root, f'{run.id}/ppt/{"c" * 32}')
    legacy = old_directory(root, f'{run.id}/legacy')
    run.output_data = {'artifacts': {'ppt': {'storage_path': str((current / 'keep.txt').relative_to(root))}},
                       'ppt_versions': [{'artifact': {'storage_path': str((history / 'keep.txt').relative_to(root))}}]}
    db.commit()
    plan = service.plan()
    assert plan['mode'] == 'dry-run'
    assert [item['path'] for item in plan['candidates']] == [str(orphan.relative_to(root))]
    assert all(path.exists() for path in [orphan, current, history, legacy])
    with pytest.raises(ValueError, match='offline'):
        service.quarantine()


def test_quarantine_requires_offline_is_recoverable_and_never_deletes(db):
    run, root, service = fixture(db)
    orphan = old_directory(root, f'{run.id}/ppt/{"a" * 32}')
    result = service.quarantine(offline=True)
    assert not orphan.exists() and result['permanently_deleted'] == 0
    assert (root / '.ppt-quarantine' / result['batch_id'] / orphan.relative_to(root) / 'keep.txt').read_text() == 'recoverable'
    service.restore(result['batch_id'], offline=True)
    assert (orphan / 'keep.txt').read_text() == 'recoverable'
    assert service.restore(result['batch_id'], offline=True)['restored'] == []


def test_no_cleanup_with_active_jobs_or_symlinks(db, tmp_path):
    run, root, service = fixture(db)
    orphan = old_directory(root, f'{run.id}/ppt/{"a" * 32}')
    run.status = 'running'; db.commit()
    assert service.plan()['candidates'] == []
    with pytest.raises(ValueError, match='任务'):
        service.quarantine(offline=True)
    run.status = 'completed'; db.commit()
    (orphan / 'outside').symlink_to(tmp_path)
    assert service.plan()['candidates'] == []


def test_recent_and_latest_checkpoint_are_kept_but_obsolete_checkpoint_can_be_quarantined(db):
    run, root, service = fixture(db)
    prefix = f'{run.id}/ppt_jobs/{"f" * 64}'
    latest = old_directory(root, f'{prefix}/{"a" * 32}')
    obsolete = old_directory(root, f'{prefix}/{"b" * 32}')
    (latest / 'state.json').write_text('{}')
    (latest.parent / 'latest.json').write_text(json.dumps({'job_id': latest.name}))
    recent = root / f'{run.id}/ppt/{"c" * 32}'
    recent.mkdir(parents=True)
    assert [item['path'] for item in service.plan()['candidates']] == [str(obsolete.relative_to(root))]
    (latest.parent / 'latest.json').write_text('corrupt')
    assert service.plan()['candidates'] == []


def test_restore_refuses_overwrite_and_tampered_manifest(db):
    run, root, service = fixture(db)
    orphan = old_directory(root, f'{run.id}/ppt/{"a" * 32}')
    batch = service.quarantine(offline=True)['batch_id']
    orphan.mkdir()
    with pytest.raises(ValueError, match='覆盖'):
        service.restore(batch, offline=True)
    manifest = root / '.ppt-quarantine' / batch / 'manifest.json'
    manifest.write_text(json.dumps({'moved': ['../outside']}))
    with pytest.raises(ValueError, match='非法'):
        service.restore(batch, offline=True)


def test_references_from_other_runs_also_protect_native_files(db):
    run, root, service = fixture(db)
    shared = old_directory(root, f'{run.id}/ppt/{"a" * 32}')
    other = AgentRun(created_by=run.created_by, agent_type='teacher_lesson_prep', status='completed',
                     output_data={'legacy': {'preview_path': str((shared / 'keep.txt').relative_to(root))}})
    db.add(other); db.commit()
    assert service.plan()['candidates'] == []


def test_latest_checkpoint_in_a_later_run_protects_shared_assets(db):
    run, root, service = fixture(db)
    shared = old_directory(root, f'{run.id}/ppt/{"a" * 32}')
    checkpoint = old_directory(root, f'{run.id + 1}/ppt_jobs/{"f" * 64}/{"b" * 32}')
    (checkpoint / 'state.json').write_text(json.dumps({'data': {'visual_asset': {
        'storage_path': str((shared / 'keep.txt').relative_to(root))}}}))
    (checkpoint.parent / 'latest.json').write_text(json.dumps({'job_id': checkpoint.name}))
    assert service.plan()['candidates'] == []
