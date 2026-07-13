from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.study import ReviewRead, StudyChatHistorySave, StudyChatMessageRead, StudyNoteListItem, StudyNoteRead, StudyNoteUpdate
from app.services.study_service import StudyService


router = APIRouter(prefix="/study", tags=["study"])


@router.get("/chat-history/{chapter_id}", response_model=ApiResponse[list[StudyChatMessageRead]])
def chat_history(chapter_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[StudyChatMessageRead]]:
    return ApiResponse(data=StudyService(db).list_chat_history(user.id, chapter_id))


@router.post("/chat-history", response_model=ApiResponse[list[StudyChatMessageRead]])
def save_chat_history(payload: StudyChatHistorySave, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[StudyChatMessageRead]]:
    return ApiResponse(message="AI 对话已保存", data=StudyService(db).save_chat_history(user.id, payload))


@router.get("/notes", response_model=ApiResponse[list[StudyNoteListItem]])
def list_notes(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[StudyNoteListItem]]:
    return ApiResponse(data=StudyService(db).list_notes(user.id))


@router.get("/notes/{chapter_id}", response_model=ApiResponse[StudyNoteRead | None])
def get_note(chapter_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[StudyNoteRead | None]:
    return ApiResponse(data=StudyService(db).get_note(user.id, chapter_id))


@router.put("/notes/{chapter_id}", response_model=ApiResponse[StudyNoteRead])
def save_note(chapter_id: int, payload: StudyNoteUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[StudyNoteRead]:
    return ApiResponse(message="学习笔记已保存", data=StudyService(db).save_note(user.id, chapter_id, payload.content))


@router.delete("/notes/{note_id}", response_model=ApiResponse[dict[str, int]])
def delete_note(note_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[dict[str, int]]:
    StudyService(db).delete_note(user.id, note_id)
    return ApiResponse(message="学习笔记已删除", data={"id": note_id})


@router.get("/reviews/today", response_model=ApiResponse[list[ReviewRead]])
def today_reviews(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[list[ReviewRead]]:
    return ApiResponse(data=StudyService(db).due_reviews(user.id))


@router.post("/reviews/{chapter_id}/activate", response_model=ApiResponse[dict[str, int]])
def activate_review(chapter_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[dict[str, int]]:
    record = StudyService(db).activate_review(user.id, chapter_id)
    return ApiResponse(message="已加入间隔复习计划", data={"id": record.id, "interval_days": record.interval_days})


@router.post("/reviews/{chapter_id}/complete", response_model=ApiResponse[dict[str, int]])
def complete_review(chapter_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ApiResponse[dict[str, int]]:
    record = StudyService(db).complete_review(user.id, chapter_id)
    return ApiResponse(message="本次复习已完成", data={"id": record.id, "interval_days": record.interval_days})
