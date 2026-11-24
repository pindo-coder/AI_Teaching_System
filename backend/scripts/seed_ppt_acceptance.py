"""Create an explicitly isolated, synthetic teacher workspace for UI acceptance.

Never run this against production. It does not read/copy existing accounts.
The fixed credential is only for a localhost disposable test database.
"""
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
import app.db.models  # noqa: F401
from app.db.session import engine, SessionLocal
from app.models.user import User
from app.models.course import Course
from app.models.chapter import Chapter


def main():
    url = make_url(settings.database_url)
    database = Path(url.database or "").resolve()
    if url.get_backend_name() != "sqlite" or "ai-teaching-ppt-upgrade." not in str(database) or database.name != "ui-acceptance.db":
        raise SystemExit("仅允许写入本轮 ai-teaching-ppt-upgrade 临时目录的 ui-acceptance.db")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None:
            raise SystemExit("测试库已有用户，拒绝覆盖")
        db.add(User(username="ppt_accept_teacher", password_hash=hash_password("PptLocalTest2026!"),
            role="teacher", approval_status="approved", must_change_password=False))
        course = Course(name="PPT 本地验收课程", description="独立合成测试材料，不用于真实教学")
        db.add(course)
        db.flush()
        db.add(Chapter(course_id=course.id, title="全过程人民民主", sort_order=1,
            content="全过程人民民主是社会主义民主政治的本质属性，是最广泛、最真实、最管用的民主。"
            "协商民主是实践全过程人民民主的重要形式。基层群众自治体现人民依法直接行使民主权利。"
            "民主选举、民主协商、民主决策、民主管理、民主监督相互衔接。"
            "课堂通过模拟社区公共事务协商，分析如何保障有效参与。"))
        db.commit()
    print("isolated_ui_workspace=ready")


if __name__ == "__main__":
    main()
