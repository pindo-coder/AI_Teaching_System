from fastapi import APIRouter, Depends
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
