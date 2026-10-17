"""Opt-in tests against the disposable loopback-only CI database, never production."""
import os
from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.agent_run import AgentRun
from app.services.agent_service import AgentService
from app.services.lesson_publication_service import LessonPublicationService
from tests.test_lesson_publication_safety import publication_context


@pytest.fixture
def mysql_db():
    configured = os.environ.get('PPT_MYSQL_TEST_URL')
    if not configured:
        pytest.skip('需要专用 PPT_MYSQL_TEST_URL；不连接应用配置的数据库')
    url = make_url(configured)
    if (url.get_backend_name() != 'mysql' or url.host not in {'127.0.0.1', 'localhost'}
            or url.database != 'ppt_workflow_ci' or url.username != 'ppt_ci'):
        pytest.fail('MySQL 联调只允许本机专用 ppt_ci@ppt_workflow_ci 测试库')
    engine = create_engine(url, pool_pre_ping=True, connect_args={'connect_timeout': 5})
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_mysql_real_publication_preserves_name_and_json_revision(mysql_db):
    teacher, student, run, payload, source = publication_context(mysql_db)
    assert mysql_db.scalar(select(AgentRun.id).where(
        AgentRun.output_data['artifact_bundle']['ppt']['revision_id'].as_string() == 'revision-1')) == run.id
    item = LessonPublicationService(mysql_db, teacher).publish(run.id, payload)
    assert item.ppt_file_name == '教师自定义公开课.pptx'
    assert LessonPublicationService(mysql_db, student).download(item.id)[0].read_bytes() == source.read_bytes()


def test_mysql_compare_and_swap_rejects_concurrent_version_change(mysql_db):
    teacher, _, run, _, _ = publication_context(mysql_db)
    old_path = run.output_data['artifacts']['ppt']['storage_path']
    new_output = deepcopy(run.output_data)
    new_output['artifacts']['ppt']['storage_path'] = 'new-file.pptx'
    with Session(mysql_db.get_bind()) as other:
        other.execute(update(AgentRun).where(AgentRun.id == run.id).values(output_data=new_output))
        other.commit()
    with pytest.raises(HTTPException) as exc:
        AgentService(mysql_db, teacher)._commit_artifact_mutation(run, old_path)
    assert exc.value.status_code == 409
    mysql_db.refresh(run)
    assert run.output_data['artifacts']['ppt']['storage_path'] == 'new-file.pptx'


def test_mysql_publication_row_lock_blocks_concurrent_version_update(mysql_db):
    teacher, _, run, _, _ = publication_context(mysql_db)
    LessonPublicationService(mysql_db, teacher)._require_run(run.id)
    with Session(mysql_db.get_bind()) as other:
        other.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
        with pytest.raises(OperationalError) as exc:
            other.execute(update(AgentRun).where(AgentRun.id == run.id).values(status='queued'))
        assert exc.value.orig.args[0] == 1205
        other.rollback()
    mysql_db.rollback()
