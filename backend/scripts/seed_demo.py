"""创建本地验收账号、教材专题和示例知识库资料。"""

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

        course = db.scalar(select(Course).where(Course.name == "习近平新时代中国特色社会主义思想概论"))
        if course is None:
            course = Course(
                name="习近平新时代中国特色社会主义思想概论",
                description="围绕一本教材建设专题化学习、时政关联、课堂互动与 RAG 知识库。",
            )
            db.add(course)
            db.flush()
            db.add_all(
                [
                    Chapter(
                        course_id=course.id,
                        title="专题一 新时代坚持和发展中国特色社会主义",
                        content="本专题围绕新时代坚持和发展中国特色社会主义的主题，帮助学生理解新时代的历史方位、实践基础和理论创新。",
                        sort_order=1,
                    ),
                    Chapter(
                        course_id=course.id,
                        title="专题二 以中国式现代化全面推进中华民族伟大复兴",
                        content="本专题聚焦中国式现代化的中国特色、本质要求和重大原则，引导学生把握强国建设、民族复兴的战略安排。",
                        sort_order=2,
                    ),
                    Chapter(
                        course_id=course.id,
                        title="专题三 坚持党的全面领导",
                        content="本专题阐释中国共产党领导是中国特色社会主义最本质的特征和最大制度优势，理解党的领导贯穿治国理政全过程。",
                        sort_order=3,
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
                    "# 新时代坚持和发展中国特色社会主义\n\n"
                    "习近平新时代中国特色社会主义思想围绕新时代坚持和发展什么样的中国特色社会主义、"
                    "怎样坚持和发展中国特色社会主义等重大时代课题展开，体现了理论创新与实践创新的统一。\n\n"
                    "高校思政课教学应引导学生把教材知识、时代发展和个人成长联系起来，形成结构化、历史化、现实化的理解。"
                ).encode("utf-8"),
                source_title="教材专题示例资料",
                course_id=course.id,
                chapter_id=chapter.id,
                knowledge_point="新时代中国特色社会主义",
            )
        else:
            service = KnowledgeService(db)
            for document in ready_documents:
                service.reindex(document.id)

    print("Demo data ready: admin / Admin@123456, student_demo / Student@123456")


if __name__ == "__main__":
    seed()
