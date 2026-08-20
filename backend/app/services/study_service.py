from datetime import datetime, timedelta
from html import unescape
from html import escape
import hashlib
import json
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
from app.schemas.ai import AiAssistRequest
from app.services.ai_service import AiService


REVIEW_INTERVALS = [1, 2, 4, 7, 15, 30]
REVIEW_REFERENCE_CACHE_VERSION = "chapter-only-v1"
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
        chapter_text = (chapter.content or "").strip()
        excerpt = chapter_text[:1200] or f"围绕《{chapter.title}》的教材核心内容进行复习。"
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

    def latest_review_result(self, user_id: int, chapter_id: int) -> list[dict[str, object]]:
        """Return the latest completed three-question round unless a round is still pending."""
        chapter = self.require_chapter(chapter_id)
        pending = self.db.scalar(select(ReviewPractice.id).where(
            ReviewPractice.user_id == user_id,
            ReviewPractice.chapter_id == chapter_id,
            ReviewPractice.answered_at.is_(None),
        ).limit(1))
        if pending is not None:
            return []
        practices = list(self.db.scalars(select(ReviewPractice).where(
            ReviewPractice.user_id == user_id,
            ReviewPractice.chapter_id == chapter_id,
            ReviewPractice.answered_at.is_not(None),
        ).order_by(ReviewPractice.answered_at.desc(), ReviewPractice.id.desc()).limit(3)).all())
        if len(practices) < 3:
            return []
        practices.reverse()
        return [{
            "practice_id": item.id,
            "question": item.question,
            "source_position": item.source_position,
            "student_answer": item.student_answer,
            "is_correct": bool(item.is_correct),
            "feedback": "回答已覆盖教材中的关键表述，可继续结合概念之间的逻辑关系完善。" if item.is_correct else "回答与教材依据的对应还不够充分，请对照参考答案检查核心概念和论证逻辑。",
            "ai_reference_answer": item.ai_reference_answer.strip() or item.explanation.strip(),
            "reference_knowledge_points": item.reference_knowledge_points or ["章节主旨", "核心概念与主要观点", "观点之间的逻辑关系"],
            "reference_generated": bool(
                item.ai_reference_answer.strip()
                and item.reference_cache_key == self._review_reference_cache_key(chapter, item)
            ),
        } for item in practices]

    def submit_review_answer(self, user_id: int, practice_id: int, answer: str) -> dict[str, object]:
        practice = self.db.scalar(select(ReviewPractice).where(ReviewPractice.id == practice_id, ReviewPractice.user_id == user_id))
        if practice is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="复习题不存在")
        if practice.answered_at is not None:
            completed = self.db.scalar(select(ReviewPractice.id).where(
                ReviewPractice.user_id == user_id,
                ReviewPractice.chapter_id == practice.chapter_id,
                ReviewPractice.answered_at.is_(None),
            )) is None
            fallback_answer, fallback_points = self._fallback_review_reference(practice)
            return {
                "id": practice.id,
                "is_correct": bool(practice.is_correct),
                "feedback": "该题已提交，已恢复本次练习进度。",
                "reference_answer": practice.explanation,
                "ai_reference_answer": fallback_answer,
                "reference_knowledge_points": fallback_points,
                "source_position": practice.source_position,
                "completed": completed,
                "next_interval_days": None,
            }
        answer_words = self._keywords(answer)
        reference_words = self._keywords(practice.explanation)
        overlap = len(answer_words & reference_words)
        is_correct = len(answer.strip()) >= 40 and overlap >= 1
        practice.selected_index = 0
        practice.is_correct = is_correct
        practice.student_answer = answer.strip()
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
        ai_reference_answer, reference_knowledge_points = self._fallback_review_reference(practice)
        return {"id": practice.id, "is_correct": is_correct, "feedback": feedback,
                "reference_answer": practice.explanation,
                "ai_reference_answer": ai_reference_answer,
                "reference_knowledge_points": reference_knowledge_points,
                "source_position": practice.source_position,
                "completed": completed, "next_interval_days": next_interval}

    @staticmethod
    def _fallback_review_reference(practice: ReviewPractice) -> tuple[str, list[str]]:
        evidence = practice.explanation.strip()[:700] or "当前章节教材正文"
        question = practice.question.strip()
        if any(term in question for term in ("主旨", "主要问题", "战略安排")):
            guidance = "应先概括本章核心主旨，再说明这一战略安排所回应的发展目标、基本路径和内在逻辑。"
            fallback_points = ["章节核心主旨", "战略目标与发展路径", "重大原则之间的逻辑关系"]
        elif any(term in question for term in ("概念", "观点", "内涵", "关系")):
            guidance = "应明确题目涉及的核心概念，解释其基本内涵，再分析概念或观点之间的逻辑联系。"
            fallback_points = ["核心概念的规范内涵", "主要观点", "概念与观点之间的逻辑关系"]
        elif any(term in question for term in ("现实意义", "实践", "如何理解", "为什么")):
            guidance = "应从理论依据、实践要求和现实意义三个层次展开，并把结论落实到当前章节的规范表述。"
            fallback_points = ["理论依据", "实践要求", "现实意义"]
        else:
            guidance = "应围绕题干给出明确结论，并使用本章核心概念、主要观点和教材依据进行分层论证。"
            fallback_points = ["题干中的核心命题", "教材主要观点", "结论与依据的逻辑关系"]
        fallback_answer = f"针对题目“{question}”，{guidance}\n\n教材依据：{evidence}"
        return fallback_answer, fallback_points

    @staticmethod
    def _review_reference_cache_key(chapter: Chapter, practice: ReviewPractice) -> str:
        payload = json.dumps({
            "version": REVIEW_REFERENCE_CACHE_VERSION,
            "chapter_id": chapter.id,
            "chapter_content": chapter.content or "",
            "question": practice.question,
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def review_references(self, user_id: int, chapter_id: int, practice_ids: list[int], *, force: bool = False) -> list[dict[str, object]]:
        """Generate all answer references in one grounded AI request after a practice round."""
        chapter = self.require_chapter(chapter_id)
        practices = list(self.db.scalars(select(ReviewPractice).where(
            ReviewPractice.user_id == user_id,
            ReviewPractice.chapter_id == chapter_id,
            ReviewPractice.id.in_(set(practice_ids)),
            ReviewPractice.answered_at.is_not(None),
        ).order_by(ReviewPractice.id)).all())
        if len(practices) != len(set(practice_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="尚未提交本轮练习")

        if not force and all(
            item.ai_reference_answer.strip()
            and item.reference_knowledge_points
            and item.reference_cache_key == self._review_reference_cache_key(chapter, item)
            for item in practices
        ):
            return [{
                "practice_id": item.id,
                "ai_reference_answer": item.ai_reference_answer,
                "reference_knowledge_points": item.reference_knowledge_points,
            } for item in practices]

        fallback = [
            {
                "practice_id": item.id,
                "ai_reference_answer": self._fallback_review_reference(item)[0],
                "reference_knowledge_points": self._fallback_review_reference(item)[1],
            }
            for item in practices
        ]
        question_payload = [{"practice_id": item.id, "question": item.question} for item in practices]
        try:
            generated = AiService(self.db).assist(AiAssistRequest(
                course_id=practices[0].course_id,
                chapter_id=chapter_id,
                learning_stage="exam",
                task_type="review_feedback",
                question=(
                    f"请为以下练习题逐题生成不同的参考答案和参考知识点：\n{json.dumps(question_payload, ensure_ascii=False)}\n"
                    "每个答案必须直接回应对应题干，不得复制其他题目的答案。"
                    "只输出 JSON 数组，每项格式为："
                    '{"practice_id":题目ID,"ai_reference_answer":"参考答案","reference_knowledge_points":["知识点"]}'
                ),
            )).answer.strip()
        except Exception:
            return fallback
        try:
            raw = generated.strip()
            start, end = raw.find("["), raw.rfind("]")
            if start < 0 or end <= start:
                raise ValueError("AI response did not contain a JSON array")
            payload = raw[start:end + 1]
            parsed = json.loads(payload)
            by_id = {int(item["practice_id"]): item for item in parsed if isinstance(item, dict)}
            output = []
            seen_answers: set[str] = set()
            for item, default in zip(practices, fallback, strict=True):
                generated_item = by_id.get(item.id, {})
                answer_text = str(generated_item.get("ai_reference_answer", "")).strip()
                normalized_answer = re.sub(r"\s+", "", answer_text)
                if not normalized_answer or normalized_answer in seen_answers:
                    answer_text = str(default["ai_reference_answer"])
                    normalized_answer = re.sub(r"\s+", "", answer_text)
                seen_answers.add(normalized_answer)
                points = generated_item.get("reference_knowledge_points", [])
                reference = {
                    "practice_id": item.id,
                    "ai_reference_answer": answer_text or default["ai_reference_answer"],
                    "reference_knowledge_points": [str(point).strip() for point in points if str(point).strip()][:8]
                    or default["reference_knowledge_points"],
                }
                item.ai_reference_answer = str(reference["ai_reference_answer"])
                item.reference_knowledge_points = list(reference["reference_knowledge_points"])
                item.reference_cache_key = self._review_reference_cache_key(chapter, item)
                output.append(reference)
            self.db.commit()
            return output
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def save_review_to_notes(self, user_id: int, chapter_id: int, practice_ids: list[int]) -> StudyNote:
        chapter = self.require_chapter(chapter_id)
        practices = list(self.db.scalars(select(ReviewPractice).where(
            ReviewPractice.user_id == user_id,
            ReviewPractice.chapter_id == chapter_id,
            ReviewPractice.id.in_(set(practice_ids)),
            ReviewPractice.answered_at.is_not(None),
        ).order_by(ReviewPractice.id)).all())
        if len(practices) != len(set(practice_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="本轮答题记录不完整或不属于当前用户")

        round_key = f"{min(practice_ids)}-{max(practice_ids)}"
        marker = f"练习记录编号：{round_key}"
        end_marker = f"练习记录结束：{round_key}"
        existing = self.get_note(user_id, chapter_id)
        existing_content = existing.content if existing else ""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        parts = [f"<hr><h2>本章练习记录 · {escape(timestamp)}</h2><p><em>{marker}</em></p>"]
        for index, practice in enumerate(practices, 1):
            answer_text = practice.ai_reference_answer.strip() or practice.explanation.strip() or "暂无参考答案"
            points = practice.reference_knowledge_points or ["章节主旨", "核心概念与主要观点", "观点之间的逻辑关系"]
            parts.extend([
                f"<h3>第 {index} 题：{escape(practice.question)}</h3>",
                f"<p><strong>我的作答：</strong>{escape(practice.student_answer or '未保存作答内容')}</p>",
                f"<p><strong>AI 参考答案：</strong>{escape(answer_text)}</p>",
                "<p><strong>参考知识点：</strong></p><ul>",
                *(f"<li>{escape(str(point))}</li>" for point in points),
                "</ul>",
            ])
        parts.append(f"<p><em>{end_marker}</em></p>")
        review_section = "".join(parts)
        if marker in existing_content and end_marker in existing_content:
            pattern = re.compile(
                rf"<hr><h2>本章练习记录[^<]*</h2><p><em>{re.escape(marker)}</em></p>.*?<p><em>{re.escape(end_marker)}</em></p>",
                flags=re.DOTALL,
            )
            combined = pattern.sub(review_section, existing_content, count=1)
        else:
            combined = f"{existing_content}{review_section}"
        if len(combined) > 30_000:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节笔记内容已接近上限，请先整理后再保存答题记录")
        return self.save_note(user_id, chapter.id, combined)

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
