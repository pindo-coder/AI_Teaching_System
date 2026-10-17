"""Private, per-run checkpoints. A fingerprint never crosses users or inputs."""
from __future__ import annotations

import hashlib
import json
import re
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
    def __init__(self, run_id: int, signature: dict, *, resume: bool):
        self.fingerprint = digest(signature)
        self.base = artifact_root() / str(run_id) / "ppt_jobs" / self.fingerprint
        self.base.mkdir(parents=True, exist_ok=True)
        self.resumed = False
        self.state: dict = {}
        if resume:
            try:
                identifier = json.loads((self.base / "latest.json").read_text())["job_id"]
                if not re.fullmatch(r"[0-9a-f]{32}", identifier):
                    raise ValueError("invalid checkpoint ID")
                directory = (self.base / identifier).resolve()
                if self.base.resolve() not in directory.parents:
                    raise ValueError("checkpoint path outside run")
                state = json.loads((directory / "state.json").read_text())
                if state.get("fingerprint") == self.fingerprint and state.get("status") in {"running", "failed", "partial"}:
                    self.state, self.directory, self.resumed = state, directory, True
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if not self.resumed:
            identifier = uuid4().hex
            self.directory = self.base / identifier
            self.directory.mkdir(exist_ok=False)
            self.state = {"fingerprint": self.fingerprint, "status": "running", "data": None,
                          "completed_pages": 0, "stage": "planning"}
            atomic_json(self.base / "latest.json", {"job_id": identifier})
        self.save(status="running")

    def save(self, **values) -> None:
        self.state.update(deepcopy(values))
        atomic_json(self.directory / "state.json", self.state)
