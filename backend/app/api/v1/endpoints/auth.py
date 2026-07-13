from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.user import TokenData, UserCreate, UserLogin, UserRead
from app.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[UserRead], status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> ApiResponse[UserRead]:
    user = AuthService(db).register(
        username=payload.username,
        password=payload.password,
        role=payload.role,
        identity_no=payload.identity_no,
    )
    return ApiResponse(message="注册成功", data=UserRead.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenData])
def login(payload: UserLogin, db: Session = Depends(get_db)) -> ApiResponse[TokenData]:
    token, user = AuthService(db).login(username=payload.username, password=payload.password)
    return ApiResponse(message="登录成功", data=TokenData(access_token=token, user=UserRead.model_validate(user)))


@router.get("/me", response_model=ApiResponse[UserRead])
def me(current_user: User = Depends(get_current_user)) -> ApiResponse[UserRead]:
    return ApiResponse(data=UserRead.model_validate(current_user))
