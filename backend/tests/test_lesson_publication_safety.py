from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import settings
from app.models.agent_run import AgentRun, AgentStep
from app.models.lesson_publication import LessonPublication
from app.schemas.agent import AgentArtifactRequest, LessonPublishRequest
from app.services.agent_service import AgentService, execute_lesson_artifacts
from app.services.lesson_artifact_state import requires_previous_confirmation
from app.services.lesson_publication_service import LessonPublicationService
from tests.test_agents import _context, _teaching_class, _headers


def publication_context(db, *, legacy=False):
    teacher, student, course, chapter = _context(db)
    teaching_class = _teaching_class(db, teacher, student, course)
    root = Path(settings.generated_artifact_directory)
    source = root / '1/ppt/revision-1/教学课件.pptx'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'PK synthetic publication fixture')
    ppt = {'title': '教师自定义公开课', 'slides': [], **({} if legacy else {
        'pipeline_version': 'ppt-master-svg-v2', 'revision_id': 'revision-1'})}
    artifact = {'kind': 'ppt', 'file_name': '教师自定义公开课.pptx',
                'storage_path': str(source.relative_to(root)), 'attempt_id': 'success',
                **({} if legacy else {'revision_id': 'revision-1'})}
    run = AgentRun(created_by=teacher.id, agent_type='teacher_lesson_prep', status='completed', current_step=3,
                   course_id=course.id, chapter_id=chapter.id, teaching_class_id=teaching_class.id,
                   input_data={'artifact_output_types': ['ppt']}, output_data={
                       'outline': {'title': '课纲'}, 'artifact_bundle': {'ppt': ppt},
                       'artifacts': {'ppt': artifact}, 'artifact_attempt': {
                           'id': 'success', 'status': 'completed', 'requested_types': ['ppt']}})
    db.add(run); db.flush()
    db.add(AgentStep(run_id=run.id, step_key='generate_artifacts', title='生成成果', step_order=3))
    db.commit()
    payload = LessonPublishRequest(teaching_class_id=teaching_class.id, title='公开课成果',
                                 publish_discussions=False, confirmed=True,
                                 expected_ppt_revision=None if legacy else 'revision-1')
    return teacher, student, run, payload, source


@pytest.mark.parametrize('revision', [None, '', 'stale-revision'])
def test_modern_publication_requires_the_reviewed_revision(db, revision):
    teacher, _, run, payload, _ = publication_context(db)
    payload.expected_ppt_revision = revision
    with pytest.raises(HTTPException) as exc:
        LessonPublicationService(db, teacher).publish(run.id, payload)
    assert exc.value.status_code == 409
    assert db.scalar(select(func.count()).select_from(LessonPublication)) == 0
    assert not (Path(settings.generated_artifact_directory) / 'publications').exists()


def test_publication_refreshes_cached_run_and_rejects_inconsistent_metadata(db):
    teacher, _, run, payload, _ = publication_context(db)
    output = deepcopy(run.output_data)
    output['artifacts']['ppt']['revision_id'] = 'different-file'
    run.output_data = output
    db.commit()
    with pytest.raises(HTTPException) as exc:
        LessonPublicationService(db, teacher).publish(run.id, payload)
    assert exc.value.status_code == 409


@pytest.mark.parametrize('attempt_status', ['failed', 'partial'])
def test_failed_retry_needs_separate_previous_version_confirmation(db, attempt_status):
    teacher, student, run, payload, source = publication_context(db)
    run.output_data = {**run.output_data,
        'artifact_errors': {'ppt': '新版生成失败'},
        'artifact_attempt': {'id': 'retry', 'status': attempt_status, 'requested_types': ['ppt']}}
    db.commit()
    assert AgentService.serialize(db, run).output_data['artifacts']['ppt']['requires_previous_confirmation']
    with pytest.raises(HTTPException) as exc:
        LessonPublicationService(db, teacher).publish(run.id, payload)
    assert exc.value.status_code == 409
    payload.allow_previous_ppt = True
    result = LessonPublicationService(db, teacher).publish(run.id, payload)
    assert LessonPublicationService(db, student).download(result.id)[0].read_bytes() == source.read_bytes()


@pytest.mark.parametrize('legacy', [True, False])
def test_student_download_preserves_custom_name_and_is_an_independent_copy(client, db, legacy):
    teacher, student, run, payload, source = publication_context(db, legacy=legacy)
    result = client.post(f'/api/v1/agent/runs/{run.id}/publish', headers=_headers(teacher), json=payload.model_dump())
    assert result.status_code == 200
    item = result.json()['data']
    assert item['ppt_file_name'] == '教师自定义公开课.pptx'
    response = client.get(f"/api/v1/agent/publications/{item['id']}/ppt", headers=_headers(student))
    from urllib.parse import unquote
    assert '教师自定义公开课.pptx' in unquote(response.headers['content-disposition'])
    source.write_bytes(b'changed later by another revision')
    assert response.content == LessonPublicationService(db, student).download(item['id'])[0].read_bytes()
    assert response.content != source.read_bytes()


def test_ppt_failure_marker_survives_a_later_document_request(db, monkeypatch):
    teacher, _, run, _, _ = publication_context(db)
    service = AgentService(db, teacher)
    service.request_artifacts(run.id, AgentArtifactRequest(output_types=['ppt']))
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic PPT failure')
    monkeypatch.setattr('app.services.agent_service.PptWorkflowService.generate', fail)
    execute_lesson_artifacts(run.id, db.get_bind())
    db.refresh(run)
    assert requires_previous_confirmation(run.output_data, 'ppt')
    service.request_artifacts(run.id, AgentArtifactRequest(output_types=['lesson_plan']))
    assert requires_previous_confirmation(run.output_data, 'ppt')
    assert not run.output_data['artifact_errors'] or 'ppt' in run.output_data['artifact_errors']
    # A document completion replacing the last-attempt metadata cannot clear
    # the per-PPT marker either.
    output = deepcopy(run.output_data)
    output['artifact_attempt'] = {'id': 'docs', 'status': 'completed', 'requested_types': ['lesson_plan']}
    output['artifact_errors'] = {}
    assert requires_previous_confirmation(output, 'ppt')
    artifact = output['artifacts']['ppt']
    service._save_updated_ppt(run, output['artifact_bundle']['ppt'], artifact)
    assert not requires_previous_confirmation(run.output_data, 'ppt')


def test_unsafe_display_filename_cannot_escape_publication_directory(db):
    teacher, _, run, payload, _ = publication_context(db)
    output = deepcopy(run.output_data)
    output['artifacts']['ppt']['file_name'] = '../bad\r\nname.pptx'
    run.output_data = output; db.commit()
    result = LessonPublicationService(db, teacher).publish(run.id, payload)
    assert '/' not in result.ppt_file_name and '\r' not in result.ppt_file_name and '\n' not in result.ppt_file_name


def test_wrong_revision_is_rejected_even_with_previous_version_acknowledgement(db):
    teacher, _, run, payload, _ = publication_context(db)
    payload.allow_previous_ppt = True
    payload.expected_ppt_revision = 'stale'
    with pytest.raises(HTTPException) as exc:
        LessonPublicationService(db, teacher).publish(run.id, payload)
    assert exc.value.status_code == 409
