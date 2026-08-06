"""使用当前 Embedding 配置重建全部个人笔记向量。

新集合名包含模型和维度，因此不会覆盖旧维度集合；脚本可安全重复执行。
"""

from sqlalchemy import select

import app.db.models  # noqa: F401  注册全部 ORM 关系后再执行独立脚本
from app.db.session import SessionLocal
from app.models.study_note import StudyNote
from app.rag.vector_store import get_study_note_vector_store, upsert_study_note_vector
from app.services.study_service import StudyService


def main() -> None:
    with SessionLocal() as db:
        notes = list(db.scalars(select(StudyNote).order_by(StudyNote.id)).all())
        expected_vectors = 0
        for note in notes:
            content = StudyService.plain_note_content(note.content)
            if content.strip():
                expected_vectors += (len(content.strip()) + 899) // 900
            upsert_study_note_vector(
                note_id=note.id,
                content=content,
                metadata={
                    "user_id": note.user_id,
                    "course_id": note.course_id,
                    "chapter_id": note.chapter_id,
                },
            )
        store = get_study_note_vector_store()
        actual_vectors = store._collection.count()
        if actual_vectors != expected_vectors:
            raise RuntimeError(f"笔记索引不完整：预期 {expected_vectors} 条，实际 {actual_vectors} 条")
        print(f"study_notes={len(notes)} vectors={actual_vectors} collection={store._collection.name}")


if __name__ == "__main__":
    main()
