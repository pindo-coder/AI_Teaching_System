from datetime import datetime, timedelta
from html import unescape
import logging
import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.review_schedule import ReviewSchedule
from app.models.study_note import StudyNote
from app.models.study_chat_message import StudyChatMessage
from app.models.review_practice import ReviewPractice
from app.rag.retriever import retrieve
from app.rag.vector_store import delete_study_note_vectors, get_study_note_vector_store, upsert_study_note_vector
from app.schemas.study import StudyChatHistorySave


REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]
logger = logging.getLogger(__name__)


class StudyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def require_chapter(self, chapter_id: int) -> Chapter:
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="专题不存在")
        return chapter

    @staticmethod
    def plain_note_content(content: str) -> str:
        """富文本仅负责显示，Embedding、AI 和导出统一使用无标签正文。"""
        text = re.sub(r"<br\s*/?>", "\n", content, flags=re.IGNORECASE)
        text = re.sub(r"</(?:p|h[1-6]|li|div)>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return re.sub(r"\n{3,}", "\n\n", unescape(text)).strip()

    def get_note(self, user_id: int, chapter_id: int) -> StudyNote | None:
        self.require_chapter(chapter_id)
        return self.db.scalar(select(StudyNote).where(StudyNote.user_id == user_id, StudyNote.chapter_id == chapter_id))

    def list_notes(self, user_id: int) -> list[dict[str, object]]:
        query = (
            select(StudyNote, Course.name, Chapter.title)
            .join(Course, Course.id == StudyNote.course_id)
            .join(Chapter, Chapter.id == StudyNote.chapter_id)
            .where(StudyNote.user_id == user_id)
            .order_by(StudyNote.updated_time.desc(), StudyNote.id.desc())
        )
        return [
            {
                "id": note.id,
                "user_id": note.user_id,
                "course_id": note.course_id,
                "chapter_id": note.chapter_id,
                "content": note.content,
                "created_time": note.created_time,
                "updated_time": note.updated_time,
                "course_name": course_name,
                "chapter_title": chapter_title,
            }
            for note, course_name, chapter_title in self.db.execute(query).all()
        ]

    def delete_note(self, user_id: int, note_id: int) -> None:
        note = self.db.scalar(select(StudyNote).where(StudyNote.id == note_id, StudyNote.user_id == user_id))
        if note is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学习笔记不存在")
        schedule = self.db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == user_id, ReviewSchedule.chapter_id == note.chapter_id))
        if schedule is not None:
            self.db.delete(schedule)
        delete_study_note_vectors(note_id)
        self.db.delete(note)
        self.db.commit()

    def list_chat_history(self, user_id: int, chapter_id: int) -> list[StudyChatMessage]:
        self.require_chapter(chapter_id)
        return list(self.db.scalars(select(StudyChatMessage).where(
            StudyChatMessage.user_id == user_id,
            StudyChatMessage.chapter_id == chapter_id,
        ).order_by(StudyChatMessage.created_time, StudyChatMessage.id)).all())

    def save_chat_history(self, user_id: int, payload: StudyChatHistorySave) -> list[StudyChatMessage]:
        chapter = self.require_chapter(payload.chapter_id)
        if chapter.course_id != payload.course_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="专题与教材不匹配")
        self.db.add_all([
            StudyChatMessage(user_id=user_id, course_id=payload.course_id, chapter_id=payload.chapter_id,
                             role="user", content=payload.question.strip(), sources=[]),
            StudyChatMessage(user_id=user_id, course_id=payload.course_id, chapter_id=payload.chapter_id,
                             role="assistant", content=payload.answer.strip(), model=payload.model,
                             sources=payload.sources),
        ])
        self.db.commit()
        return self.list_chat_history(user_id, payload.chapter_id)

    def clear_chat_history(self, user_id: int, chapter_id: int) -> None:
        self.require_chapter(chapter_id)
        messages = self.db.scalars(select(StudyChatMessage).where(
            StudyChatMessage.user_id == user_id, StudyChatMessage.chapter_id == chapter_id
        )).all()
        for message in messages:
            self.db.delete(message)
        self.db.commit()

    def save_note(self, user_id: int, chapter_id: int, content: str) -> StudyNote:
        chapter = self.require_chapter(chapter_id)
        note = self.db.scalar(select(StudyNote).where(StudyNote.user_id == user_id, StudyNote.chapter_id == chapter_id))
        if note is None:
            note = StudyNote(user_id=user_id, course_id=chapter.course_id, chapter_id=chapter.id, content=content.strip())
            self.db.add(note)
        else:
            note.content = content.strip()
        self.db.commit()
        self.db.refresh(note)
        # 向量索引失败不影响笔记保存，避免外部 Embedding 服务短暂不可用时丢失用户内容。
        try:
            upsert_study_note_vector(
                note_id=note.id,
                content=self.plain_note_content(note.content),
                metadata={"user_id": user_id, "course_id": note.course_id, "chapter_id": note.chapter_id},
            )
        except Exception:
            logger.exception("study_note_vector_upsert_failed note_id=%s", note.id)
        return note

    def search_notes(self, user_id: int, query: str, course_id: int | None = None) -> list[dict[str, object]]:
        query = query.strip()
        if not query:
            return []
        filters: list[dict[str, object]] = [{"user_id": user_id}]
        if course_id is not None:
            filters.append({"course_id": course_id})
        where: dict[str, object] = filters[0] if len(filters) == 1 else {"$and": filters}
        try:
            results = get_study_note_vector_store().similarity_search_with_relevance_scores(query, k=8, filter=where)
        except Exception:
            logger.exception("study_note_semantic_search_failed")
            return []
        note_ids = list(dict.fromkeys(int(item.metadata["note_id"]) for item, _ in results if item.metadata.get("note_id")))
        if not note_ids:
            return []
        rows = self.db.execute(
            select(StudyNote, Course.name, Chapter.title)
            .join(Course, Course.id == StudyNote.course_id)
            .join(Chapter, Chapter.id == StudyNote.chapter_id)
            .where(StudyNote.id.in_(note_ids), StudyNote.user_id == user_id)
        ).all()
        indexed = {note.id: (note, course_name, chapter_title) for note, course_name, chapter_title in rows}
        output: list[dict[str, object]] = []
        seen: set[int] = set()
        for item, score in results:
            note_id = int(item.metadata["note_id"])
            if note_id in seen or note_id not in indexed:
                continue
            seen.add(note_id)
            note, course_name, chapter_title = indexed[note_id]
            output.append({"id": note.id, "course_id": note.course_id, "chapter_id": note.chapter_id,
                           "course_name": course_name, "chapter_title": chapter_title,
                           "excerpt": item.page_content[:240], "score": round(float(score), 3)})
        return output

    def related_note_content(self, user_id: int, chapter_id: int) -> dict[str, object]:
        note = self.get_note(user_id, chapter_id)
        chapter = self.require_chapter(chapter_id)
        if note is None or not self.plain_note_content(note.content):
            return {"related_notes": [], "textbook_chunks": [], "status": "note_empty",
                    "message": "请先填写并保存笔记，系统将依据笔记内容关联教材。"}
        query = self.plain_note_content(note.content)
        note_results = [item for item in self.search_notes(user_id, query[:800], chapter.course_id) if item["id"] != note.id][:3]
        retrieval_failed = False
        try:
            chunks = retrieve(query[:1200], course_id=chapter.course_id, chapter_id=chapter.id, top_k=3, fallback_to_course=False)
        except Exception:
            logger.exception("related_textbook_retrieve_failed chapter_id=%s", chapter.id)
            chunks = []
            retrieval_failed = True
        textbook_chunks = [{"source_title": str(chunk.metadata.get("source_title", chapter.title)),
                            "excerpt": chunk.content[:280],
                            "position": str(chunk.metadata.get("position_label", "当前专题正文")),
                            "score": round(chunk.score, 3)} for chunk in chunks]
        if textbook_chunks:
            return {"related_notes": note_results, "textbook_chunks": textbook_chunks,
                    "status": "vector", "message": f"已从章节知识库找到 {len(textbook_chunks)} 个相关教材段落。"}

        # 整本教材导入时，旧数据可能没有为向量块写入 chapter_id。
        # 此时直接从当前章节正文中做本地相关度筛选，保证教材关联始终可用且不会串章。
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n|(?<=[。！？；])", chapter.content or "") if len(item.strip()) >= 20]
        query_grams = {query[index:index + 2] for index in range(max(0, len(query) - 1))}
        ranked: list[tuple[float, int, str]] = []
        for index, paragraph in enumerate(paragraphs):
            grams = {paragraph[pos:pos + 2] for pos in range(max(0, len(paragraph) - 1))}
            score = len(query_grams & grams) / max(1, min(len(query_grams), 80))
            if score > 0:
                ranked.append((score, index, paragraph))
        ranked.sort(reverse=True)
        fallback_chunks = [{"source_title": chapter.title, "excerpt": paragraph[:280],
                            "position": f"当前专题正文第 {index + 1} 段", "score": round(score, 3)}
                           for score, index, paragraph in ranked[:3]]
        if fallback_chunks:
            return {"related_notes": note_results, "textbook_chunks": fallback_chunks,
                    "status": "chapter_fallback",
                    "message": f"章节向量索引暂无匹配，已直接从当前专题正文找到 {len(fallback_chunks)} 个相关段落。"}
        return {
            "related_notes": note_results,
            "textbook_chunks": [],
            "status": "error" if retrieval_failed else "no_match",
            "message": "Embedding 服务暂时不可用，且当前专题没有可用于兜底的正文。" if retrieval_failed else "未找到与当前笔记相关的教材段落，请补充更具体的概念或观点后重试。",
        }

    def build_export_markdown(self, user_id: int, chapter_id: int) -> tuple[str, str]:
        note = self.get_note(user_id, chapter_id)
        chapter = self.require_chapter(chapter_id)
        if note is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前专题尚未保存笔记")
        history = self.list_chat_history(user_id, chapter_id)
        lines = [f"# {chapter.title}｜学习笔记", "", "## 我的笔记", "", self.plain_note_content(note.content) or "（暂无正文）", "", "## 本章 AI 问答"]
        if history:
            for item in history:
                speaker = "学生" if item.role == "user" else "AI 助教"
                lines.extend(["", f"### {speaker}", "", item.content])
        else:
            lines.extend(["", "（暂无本章问答记录）"])
        return "\n".join(lines), chapter.title

    @staticmethod
    def _keywords(text: str) -> set[str]:
        return {word for word in re.findall(r"[\u4e00-\u9fff]{2,}", text) if len(word) >= 2}

    def create_review_questions(self, user_id: int, chapter_id: int) -> list[ReviewPractice]:
        """由模型优先生成开放题；服务不可用时保留教材化兜底题。"""
        chapter = self.require_chapter(chapter_id)
        note = self.get_note(user_id, chapter_id)
        existing = self.db.scalars(select(ReviewPractice).where(
            ReviewPractice.user_id == user_id, ReviewPractice.chapter_id == chapter_id,
            ReviewPractice.answered_at.is_(None),
        ).order_by(ReviewPractice.id)).all()
        if existing:
            return list(existing)
        base = (self.plain_note_content(note.content) if note and note.content.strip() else chapter.content or "").strip()
        excerpt = base[:650] or f"围绕《{chapter.title}》的教材核心内容进行复习。"
        questions = [
            (f"请概括“{chapter.title}”的核心主旨，并说明其要解决的主要问题。", excerpt),
            (f"结合本专题教材，说明其中一个核心概念或主要观点的内涵及其逻辑作用。", excerpt),
            (f"根据本专题学习内容，如何理解相关理论的现实意义？请写出你的分析依据。", excerpt),
        ]
        try:
            # 题干由当前章节 AI 生成；参考依据仍从笔记/教材截取，确保反馈可追溯。
            from app.schemas.ai import AiAssistRequest
            from app.services.ai_service import AiService

            generated = AiService(self.db).assist(AiAssistRequest(
                course_id=chapter.course_id, chapter_id=chapter.id, learning_stage="review", task_type="mock_questions",
                question=("请只生成 3 道适合本章间隔复习的简答题，每题独立成行，以“1.、2.、3.”开头。"
                          "题目必须围绕章节教材与学生笔记的已有表述，不要给答案、不要选择题。"
                          f"\n\n学生笔记：\n{(self.plain_note_content(note.content) if note else '')[:3000]}"),
            )).answer
            parsed = [re.sub(r"^\s*\d+[.、]\s*", "", line).strip() for line in generated.splitlines()
                      if re.match(r"^\s*\d+[.、]\s*.+", line)]
            if len(parsed) >= 3:
                questions = [(item, excerpt) for item in parsed[:3]]
        except Exception:
            logger.info("review_question_ai_fallback chapter_id=%s", chapter_id)
        records = [ReviewPractice(user_id=user_id, course_id=chapter.course_id, chapter_id=chapter.id,
                                  question=question, choices=[], answer_index=-1, explanation=reference,
                                  source_position="当前专题教材与个人笔记") for question, reference in questions]
        self.db.add_all(records)
        self.db.commit()
        return records

    def submit_review_answer(self, user_id: int, practice_id: int, answer: str) -> dict[str, object]:
        practice = self.db.scalar(select(ReviewPractice).where(ReviewPractice.id == practice_id, ReviewPractice.user_id == user_id))
        if practice is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="复习题不存在")
        if practice.answered_at is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该题已提交")
        answer_words = self._keywords(answer)
        reference_words = self._keywords(practice.explanation)
        overlap = len(answer_words & reference_words)
        is_correct = len(answer.strip()) >= 40 and overlap >= 1
        practice.selected_index = 0
        practice.is_correct = is_correct
        practice.answered_at = datetime.now()
        self.db.commit()
        outstanding = self.db.scalar(select(ReviewPractice.id).where(
            ReviewPractice.user_id == user_id, ReviewPractice.chapter_id == practice.chapter_id,
            ReviewPractice.answered_at.is_(None),
        ))
        completed = outstanding is None
        next_interval: int | None = None
        if completed:
            next_interval = self.complete_review(user_id, practice.chapter_id).interval_days
        feedback = "回答已覆盖教材中的关键表述，可继续结合概念之间的逻辑关系完善。" if is_correct else "回答与教材依据的对应还不够充分。请围绕下方参考依据补充核心概念、主要观点和论证逻辑。"
        return {"id": practice.id, "is_correct": is_correct, "feedback": feedback,
                "reference_answer": practice.explanation, "source_position": practice.source_position,
                "completed": completed, "next_interval_days": next_interval}

    def activate_review(self, user_id: int, chapter_id: int) -> ReviewSchedule:
        chapter = self.require_chapter(chapter_id)
        record = self.db.scalar(select(ReviewSchedule).where(ReviewSchedule.user_id == user_id, ReviewSchedule.chapter_id == chapter_id))
        if record is None:
            record = ReviewSchedule(
                user_id=user_id,
                course_id=chapter.course_id,
                chapter_id=chapter.id,
                review_count=0,
                interval_days=1,
                next_review_at=datetime.now() + timedelta(days=1),
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
        return record

    def complete_review(self, user_id: int, chapter_id: int) -> ReviewSchedule:
        record = self.activate_review(user_id, chapter_id)
        now = datetime.now()
        record.review_count += 1
        record.interval_days = REVIEW_INTERVALS[min(record.review_count, len(REVIEW_INTERVALS) - 1)]
        record.last_reviewed_at = now
        record.next_review_at = now + timedelta(days=record.interval_days)
        self.db.commit()
        self.db.refresh(record)
        return record

    def due_reviews(self, user_id: int) -> list[dict[str, object]]:
        query = (
            select(ReviewSchedule, Course.name, Chapter.title)
            .join(Course, Course.id == ReviewSchedule.course_id)
            .join(Chapter, Chapter.id == ReviewSchedule.chapter_id)
            .where(ReviewSchedule.user_id == user_id, ReviewSchedule.next_review_at <= datetime.now())
            .order_by(ReviewSchedule.next_review_at)
        )
        return [
            {
                "id": record.id,
                "course_id": record.course_id,
                "chapter_id": record.chapter_id,
                "course_name": course_name,
                "chapter_title": chapter_title,
                "review_count": record.review_count,
                "interval_days": record.interval_days,
                "next_review_at": record.next_review_at,
                "last_reviewed_at": record.last_reviewed_at,
            }
            for record, course_name, chapter_title in self.db.execute(query).all()
        ]
