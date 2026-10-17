"""Shared publication/read-view rules; old JSON records need no migration."""
from __future__ import annotations


def requires_previous_confirmation(output: dict, key: str) -> bool:
    artifact = (output.get("artifacts") or {}).get(key) or {}
    if not artifact:
        return False
    # Persist this per artifact: a later DOCX retry must not erase a failed
    # PPT retry's state. An explicit restore/new verified export clears it.
    retained = artifact.get("retained_from_previous_attempt")
    if isinstance(retained, bool):
        return retained
    if (output.get("artifact_errors") or {}).get(key):
        return True
    attempt = output.get("artifact_attempt") or {}
    return bool(key in (attempt.get("requested_types") or [])
                and attempt.get("status") in {"queued", "running", "failed", "partial"}
                and artifact.get("attempt_id") != attempt.get("id"))
