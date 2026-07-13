import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.ai import AiAssistData, AiAssistRequest
from app.schemas.common import ApiResponse
from app.services.ai_service import AiService


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/assist", response_model=ApiResponse[AiAssistData])
def assist(
    payload: AiAssistRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AiAssistData]:
    return ApiResponse(message="AI 辅助内容生成成功", data=AiService(db).assist(payload))


@router.post("/assist/stream")
def assist_stream(
    payload: AiAssistRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    chunks, sources, grounded, model = AiService(db).stream(payload)

    def event_stream():
        try:
            yield f"event: meta\ndata: {json.dumps({'grounded': grounded, 'model': model}, ensure_ascii=False)}\n\n"
            for chunk in chunks:
                yield f"event: chunk\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
            yield f"event: sources\ndata: {json.dumps([source.model_dump() for source in sources], ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
