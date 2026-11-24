"""Conservative offline retention: quarantine only unreferenced native revisions.

Never delete files, legacy decks, publications, shared images or the latest
resumable checkpoint. Apply/restore require the operator to stop the backend.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from time import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.models.lesson_publication import LessonPublication
from app.services.ppt_checkpoint_service import atomic_json


def _paths(value, root: Path) -> set[Path]:
    result: set[Path] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {'storage_path', 'preview_path', 'ppt_storage_path'} and isinstance(item, str):
                path = (root / item).resolve()
                if root in path.parents:
                    result.add(path)
            else:
                result.update(_paths(item, root))
    elif isinstance(value, list):
        for item in value:
            result.update(_paths(item, root))
    return result


def _safe_directory(root: Path, path: Path) -> bool:
    return (path.is_dir() and not path.is_symlink() and root in path.resolve().parents
            and not any(part.is_symlink() for part in [path, *path.parents] if part != root)
            and not any(child.is_symlink() for child in path.rglob('*')))


class PptRetentionService:
    def __init__(self, db: Session, root: Path):
        if root.is_symlink():
            raise ValueError('成果根目录不能是符号链接')
        self.db, self.root = db, root.resolve()
        if self.root == Path(self.root.anchor) or self.root == Path.home():
            raise ValueError('不能将系统根目录或用户目录作为成果清理根目录')

    def plan(self, *, days: int = 30, now: float | None = None) -> dict:
        if days < 7:
            raise ValueError('至少保留最近 7 天的文件')
        referenced: set[Path] = set()
        active: set[int] = set()
        for run in self.db.scalars(select(AgentRun).execution_options(populate_existing=True)):
            referenced.update(_paths(run.output_data, self.root))
            if run.status in {'queued', 'running'}:
                active.add(run.id)
        for path in self.db.scalars(select(LessonPublication.ppt_storage_path)):
            if path:
                referenced.add((self.root / path).resolve())
        cutoff = (time() if now is None else now) - days * 86400
        candidates = []
        choices: list[Path] = []
        for run_dir in self.root.iterdir():
            if not run_dir.name.isdigit() or not _safe_directory(self.root, run_dir) or int(run_dir.name) in active:
                continue
            native = run_dir / 'ppt'
            if native.is_dir():
                choices.extend(path for path in native.iterdir() if re.fullmatch(r'[0-9a-f]{32}', path.name))
            jobs = run_dir / 'ppt_jobs'
            if jobs.is_dir():
                for signature in jobs.iterdir():
                    if not re.fullmatch(r'[0-9a-f]{64}', signature.name) or not _safe_directory(self.root, signature):
                        continue
                    try:
                        latest = json.loads((signature / 'latest.json').read_text())['job_id']
                        if not re.fullmatch(r'[0-9a-f]{32}', latest):
                            continue
                        state = json.loads((signature / latest / 'state.json').read_text())
                    except (OSError, ValueError, KeyError, TypeError):
                        continue  # Ambiguous checkpoints are never cleanup candidates.
                    referenced.update(_paths(state, self.root))
                    choices.extend(path for path in signature.iterdir()
                                   if re.fullmatch(r'[0-9a-f]{32}', path.name) and path.name != latest)
        # Inspect all latest checkpoints before selecting any directory. Even
        # a reference from a later run/checkpoint must protect an older file.
        for directory in choices:
            if not _safe_directory(self.root, directory):
                continue
            if any(directory == path or directory in path.parents for path in referenced):
                continue
            tree = [directory, *directory.rglob('*')]
            if max(path.stat().st_mtime for path in tree) >= cutoff:
                continue
            candidates.append({'path': directory.relative_to(self.root).as_posix(),
                               'bytes': sum(path.stat().st_size for path in tree if path.is_file())})
        return {'mode': 'dry-run', 'retention_days': days, 'active_run_ids': sorted(active),
                'candidates': sorted(candidates, key=lambda item: item['path']),
                'bytes': sum(item['bytes'] for item in candidates)}

    @staticmethod
    def _candidate_name(relative: str) -> bool:
        parts = Path(relative).parts
        return bool(parts and parts[0].isdigit() and (
            len(parts) == 3 and parts[1] == 'ppt' and re.fullmatch(r'[0-9a-f]{32}', parts[2])
            or len(parts) == 4 and parts[1] == 'ppt_jobs'
            and re.fullmatch(r'[0-9a-f]{64}', parts[2]) and re.fullmatch(r'[0-9a-f]{32}', parts[3])))

    def quarantine(self, *, days: int = 30, offline: bool = False) -> dict:
        if not offline:
            raise ValueError('请先停止后端，并显式传入 --offline；运行中不允许移动成果')
        plan = self.plan(days=days)
        if plan['active_run_ids']:
            raise ValueError('仍有排队/运行中的任务，请先等待完成或取消后再维护')
        batch = uuid4().hex
        folder = self.root / '.ppt-quarantine' / batch
        if (self.root / '.ppt-quarantine').is_symlink():
            raise ValueError('隔离目录不能是符号链接')
        folder.mkdir(parents=True, exist_ok=False)
        manifest = {'batch_id': batch, 'created_time': datetime.now(timezone.utc).isoformat(), 'moved': []}
        atomic_json(folder / 'manifest.json', manifest)
        for item in plan['candidates']:
            relative = item['path']
            source = self.root / relative
            if not self._candidate_name(relative) or not _safe_directory(self.root, source):
                continue
            destination = folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Record intent first: interruption after rename remains recoverable.
            manifest['moved'].append(relative)
            atomic_json(folder / 'manifest.json', manifest)
            source.rename(destination)
        return {**manifest, 'mode': 'quarantine', 'bytes': plan['bytes'], 'permanently_deleted': 0}

    def restore(self, batch: str, *, offline: bool = False) -> dict:
        if not offline or not re.fullmatch(r'[0-9a-f]{32}', batch):
            raise ValueError('恢复需要合法批次号，并先停止后端、传入 --offline')
        if self.db.scalar(select(AgentRun.id).where(AgentRun.status.in_(['queued', 'running'])).limit(1)):
            raise ValueError('仍有活动任务，不允许恢复')
        folder = self.root / '.ppt-quarantine' / batch
        if not _safe_directory(self.root, folder):
            raise ValueError('隔离批次目录无效')
        manifest = json.loads((folder / 'manifest.json').read_text())
        restored = []
        for relative in manifest['moved']:
            if not self._candidate_name(relative):
                raise ValueError('隔离记录包含非法路径')
            source, destination = folder / relative, self.root / relative
            if not source.exists():
                continue  # Already restored, or the original move never happened.
            if destination.exists() or destination.is_symlink():
                raise ValueError(f'原路径已存在，拒绝覆盖：{relative}')
            if not _safe_directory(self.root, source) or any(p.is_symlink() for p in destination.parents):
                raise ValueError('恢复路径存在符号链接')
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            restored.append(relative)
        return {'batch_id': batch, 'mode': 'restore', 'restored': restored}
