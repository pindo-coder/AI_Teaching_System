import json
import os

import pytest

from app.core.config import settings
from app.services.ppt_checkpoint_service import PptCheckpointStore, atomic_json, digest


def test_legacy_upgrade_copies_only_verified_partial_state_without_touching_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    old = PptCheckpointStore(42, {"version": 4, "owner": 1}, resume=False)
    old.save(status="partial", data={"slides": [{"svg": "approved", "visual_asset": {"storage_path": "paid.png"}}]})
    original = (old.directory / "state.json").read_bytes()
    store = PptCheckpointStore(42, {"version": 5, "owner": 1}, resume=True,
                               legacy_fingerprints=lambda: [old.fingerprint])
    assert store.resumed and store.legacy_imported
    assert store.state["data"] == old.state["data"]
    assert store.directory != old.directory
    assert store.state["fingerprint"] == store.fingerprint
    assert (old.directory / "state.json").read_bytes() == original
    assert json.loads((old.base / "latest.json").read_text())["job_id"] == old.directory.name
    # Later retries use the new namespace without loading historical keys.
    again = PptCheckpointStore(42, {"version": 5, "owner": 1}, resume=True,
                               legacy_fingerprints=lambda: pytest.fail("no history lookup needed"))
    assert again.resumed and not again.legacy_imported


@pytest.mark.parametrize("run_id,legacy_status", [(43, "partial"), (42, "completed")])
def test_legacy_import_cannot_cross_runs_or_revive_completed_jobs(tmp_path, monkeypatch, run_id, legacy_status):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    old = PptCheckpointStore(42, {"version": 4}, resume=False)
    old.save(status=legacy_status, data={"slides": ["private"]})
    store = PptCheckpointStore(run_id, {"version": 5}, resume=True,
                               legacy_fingerprints=lambda: [old.fingerprint])
    assert not store.resumed and store.state["data"] is None


def test_fresh_or_completed_new_job_never_falls_back_to_old_partial_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    signature = {"version": 5}
    current = PptCheckpointStore(42, signature, resume=False,
                                 legacy_fingerprints=lambda: pytest.fail("fresh means fresh"))
    current.save(status="completed", data={"slides": []})
    next_job = PptCheckpointStore(42, signature, resume=True,
                                  legacy_fingerprints=lambda: pytest.fail("do not revive old partial work"))
    assert not next_job.resumed and next_job.directory != current.directory


def test_a_newer_completed_legacy_deck_prevents_reviving_an_older_partial_deck(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    partial = PptCheckpointStore(42, {"version": 4, "image": "old key"}, resume=False)
    partial.save(status="partial", data={"slides": ["old partial"]})
    completed = PptCheckpointStore(42, {"version": 4, "image": "new key"}, resume=False)
    completed.save(status="completed", data={"slides": ["new completed"]})
    os.utime(partial.directory / "state.json", ns=(1, 1))
    store = PptCheckpointStore(42, {"version": 5}, resume=True,
        legacy_fingerprints=lambda: [partial.fingerprint, completed.fingerprint])
    assert not store.resumed and store.state["data"] is None


@pytest.mark.parametrize("corruption", ["traversal", "foreign_fingerprint", "symlink", "invalid_json"])
def test_corrupt_or_foreign_checkpoints_are_not_imported(tmp_path, monkeypatch, corruption):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    old = PptCheckpointStore(42, {"version": 4}, resume=False)
    old.save(status="partial", data={"slides": []})
    path = old.directory / "state.json"
    if corruption == "traversal":
        atomic_json(old.base / "latest.json", {"job_id": "../../43"})
    elif corruption == "foreign_fingerprint":
        atomic_json(path, {**old.state, "fingerprint": digest("another owner")})
    elif corruption == "symlink":
        outside = tmp_path / "foreign.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    else:
        path.write_text("not json")
    store = PptCheckpointStore(42, {"version": 5}, resume=True,
                               legacy_fingerprints=lambda: [old.fingerprint])
    assert not store.resumed


def test_checkpoint_run_directory_cannot_be_a_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "generated_artifact_directory", str(tmp_path))
    (tmp_path / "foreign").mkdir()
    (tmp_path / "42").symlink_to(tmp_path / "foreign", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        PptCheckpointStore(42, {"version": 5}, resume=False)
