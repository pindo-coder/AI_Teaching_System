"""Private, per-run checkpoints. A fingerprint never crosses users or inputs."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from app.services.ppt_native_service import artifact_root


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PptCheckpointStore:
    def __init__(self, run_id: int, signature: dict, *, resume: bool,
                 legacy_fingerprints: Callable[[], Iterable[str]] | None = None):
        self.fingerprint = digest(signature)
        self.jobs = artifact_root() / str(run_id) / "ppt_jobs"
        self.base = self.jobs / self.fingerprint
        if self.jobs.is_symlink() or self.jobs.parent.is_symlink() or self.base.is_symlink():
            raise ValueError("checkpoint directory must not be a symlink")
        self.base.mkdir(parents=True, exist_ok=True)
        self.resumed = False
        self.legacy_imported = False
        self.state: dict = {}
        if resume:
            match = self._read_latest(self.fingerprint)
            if match:
                self.state, self.directory = match
                self.resumed = True
            # Only upgrade when this content identity has never had a job. An
            # explicit fresh generation or a completed new job must not revive
            # an older partial deck on a later retry.
            elif not (self.base / "latest.json").exists() and legacy_fingerprints:
                newest, newest_time = None, -1
                for fingerprint in set(legacy_fingerprints()):
                    match = self._read_latest(fingerprint, include_completed=True)
                    if match and isinstance(match[0].get("data"), dict) and match[0]["data"]:
                        modified = (match[1] / "state.json").stat().st_mtime_ns
                        if modified > newest_time:
                            newest, newest_time = match, modified
                # Do not hold every historic deck in memory, or revive an old
                # failure when a newer matching legacy deck already finished.
                if newest and newest[0]["status"] != "completed":
                    state, source = newest
                    self.state = deepcopy(state)
                    self.state.update(fingerprint=self.fingerprint, migrated_from=source.parent.name)
                    self.resumed = self.legacy_imported = True
                    # Copy into the new namespace; preserve the old checkpoint
                    # byte-for-byte for rollback and its existing asset refs.
                    self._new_directory()
        if not self.resumed:
            self.state = {"fingerprint": self.fingerprint, "status": "running", "data": None,
                          "completed_pages": 0, "stage": "planning"}
            self._new_directory()
        self.save(status="running")

    def _read_latest(self, fingerprint: str, *, include_completed: bool = False) -> tuple[dict, Path] | None:
        """Fail closed on corrupt metadata, foreign runs and symlink escapes."""
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            return None
        try:
            base = self.jobs / fingerprint
            latest = base / "latest.json"
            if base.is_symlink() or base.resolve().parent != self.jobs.resolve() or latest.is_symlink() or latest.stat().st_size > 8192:
                return None
            identifier = json.loads(latest.read_text())["job_id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
                return None
            directory = base / identifier
            path = directory / "state.json"
            if directory.is_symlink() or directory.resolve().parent != base.resolve() or path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
                return None
            state = json.loads(path.read_text())
            if (isinstance(state, dict) and state.get("fingerprint") == fingerprint
                and state.get("status") in ({"running", "failed", "partial", "completed"}
                                            if include_completed else {"running", "failed", "partial"})):
                return state, directory
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _new_directory(self) -> None:
        identifier = uuid4().hex
        self.directory = self.base / identifier
        self.directory.mkdir(exist_ok=False)
        # Commit the state first; a crash must not leave latest pointing at an
        # empty directory instead of a reusable paid image checkpoint.
        self.save(status="running")
        atomic_json(self.base / "latest.json", {"job_id": identifier})

    def save(self, **values) -> None:
        self.state.update(deepcopy(values))
        atomic_json(self.directory / "state.json", self.state)
