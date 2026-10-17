"""Exercise the real SSE generator with an isolated DB and virtual time."""
import asyncio
import json

from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentStep
from app.models.user import User
from app.api.v1.endpoints import agents


def running_task(db):
    user = User(username="progress-owner", role="teacher", password_hash="test-only", approval_status="approved")
    db.add(user)
    db.flush()
    run = AgentRun(created_by=user.id, agent_type="teacher_lesson_prep", status="running", current_step=3,
        input_data={}, evidence_snapshot=[], output_data={})
    db.add(run)
    db.flush()
    step = AgentStep(run_id=run.id, step_key="generate_artifacts", title="生成成果", step_order=3,
        status="running", output_data={"ppt_workflow": {"stage": "planning", "completed_pages": 0, "total_pages": 10}})
    db.add(step)
    db.commit()
    return user, run


def collect(response):
    async def read():
        return [frame async for frame in response.body_iterator]
    return asyncio.run(read())


def test_slow_model_wait_sends_heartbeats_without_fabricating_progress(db, monkeypatch):
    user, run = running_task(db)
    clock = [0.0]
    monkeypatch.setattr(agents, "monotonic", lambda: clock[0])
    def advance(seconds):
        clock[0] += seconds
        if clock[0] >= 22:
            with Session(db.get_bind()) as writer:
                writer.get(AgentRun, run.id).status = "completed"
                writer.commit()
    monkeypatch.setattr(agents, "sleep", advance)
    response = agents.run_events(run.id, user, db)
    frames = collect(response)
    snapshots = [json.loads(frame.split("data: ", 1)[1]) for frame in frames if frame.startswith("event: snapshot")]
    assert frames.count(": keep-alive\n\n") == 2
    assert len(snapshots) == 2  # running, then completed; no fake intermediate work
    assert snapshots[0]["steps"][0]["output_data"]["ppt_workflow"]["completed_pages"] == 0
    assert frames[-1] == "event: done\ndata: {}\n\n"
    assert response.headers["x-accel-buffering"] == "no"


def test_committed_progress_changes_stream_without_browser_reload(db, monkeypatch):
    user, run = running_task(db)
    sleeps = [0]
    def advance(_seconds):
        sleeps[0] += 1
        with Session(db.get_bind()) as writer:
            current = writer.get(AgentRun, run.id)
            if sleeps[0] == 1:
                step = writer.query(AgentStep).filter_by(run_id=run.id).one()
                step.output_data = {"ppt_workflow": {"stage": "designing", "completed_pages": 5, "total_pages": 10}}
            else:
                current.status = "failed"
            writer.commit()
    monkeypatch.setattr(agents, "sleep", advance)
    frames = collect(agents.run_events(run.id, user, db))
    snapshots = [json.loads(frame.split("data: ", 1)[1]) for frame in frames if frame.startswith("event: snapshot")]
    assert len(snapshots) == 3
    assert snapshots[1]["steps"][0]["output_data"]["ppt_workflow"]["completed_pages"] == 5
    assert snapshots[-1]["status"] == "failed"
    assert frames[-1].startswith("event: done")
