"""创建本地验收账号、课程、章节和示例知识库资料。"""

from sqlalchemy import select

from app.core.security import hash_password
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User
from app.repositories.knowledge_repository import KnowledgeRepository
from app.services.knowledge_service import KnowledgeService


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        student = db.scalar(select(User).where(User.username == "student_demo"))
        if student is None:
            db.add(
                User(
                    username="student_demo",
                    password_hash=hash_password("Student@123456"),
                    role="student",
                )
            )

        course = db.scalar(select(Course).where(Course.name == "思想道德与法治（验收示例）"))
        if course is None:
            course = Course(
                name="思想道德与法治（验收示例）",
                description="用于验证课程、学习阶段、AI 助手与 RAG 知识库完整流程。",
            )
            db.add(course)
            db.flush()
            db.add_all(
                [
                    Chapter(
                        course_id=course.id,
                        title="第一章 担当复兴大任 成就时代新人",
                        content="新时代大学生应坚定理想信念、提升思想道德素质和法治素养，努力成为担当民族复兴大任的时代新人。",
                        sort_order=1,
                    ),
                    Chapter(
                        course_id=course.id,
                        title="第二章 领悟人生真谛 把握人生方向",
                        content="正确的人生观强调服务人民、奉献社会，在实践中创造有意义的人生。",
                        sort_order=2,
                    ),
                ]
            )
        db.commit()
        db.refresh(course)
        chapter = db.scalar(
            select(Chapter).where(Chapter.course_id == course.id).order_by(Chapter.sort_order)
        )
        ready_documents = KnowledgeRepository(db).list_ready_for_course(course.id)
        if not ready_documents and chapter is not None:
            KnowledgeService(db).ingest(
                filename="acceptance_material.md",
                content=(
                    "# 担当复兴大任 成就时代新人\n\n"
                    "理想信念是精神之钙。新时代青年要坚定马克思主义信仰、中国特色社会主义信念、"
                    "中华民族伟大复兴信心，把个人理想融入国家和民族事业之中。\n\n"
                    "大学生应提高思想道德素质和法治素养，在学习与社会实践中锤炼本领、担当责任。"
                ).encode("utf-8"),
                source_title="验收示例课程资料",
                course_id=course.id,
                chapter_id=chapter.id,
                knowledge_point="理想信念与时代担当",
            )
        else:
            service = KnowledgeService(db)
            for document in ready_documents:
                service.reindex(document.id)

    print("Demo data ready: admin / Admin@123456, student_demo / Student@123456")


if __name__ == "__main__":
    seed()
