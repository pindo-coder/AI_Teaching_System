from datetime import timedelta
import hashlib
import secrets

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.core.time import utc_now
from app.models.admin_password_reset_audit import AdminPasswordResetAudit
from app.models.password_reset_token import PasswordResetToken
from app.models.password_reset_request import PasswordResetRequest
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService


_BLOCKED_TEACHER_MESSAGES = {
    "rejected": "教师账号审核未通过",
    "disabled": "教师账号已被禁用",
}


def teacher_authentication_block_reason(user: User) -> str | None:
    """Return the reason a teacher account must not receive or use a session."""
    if user.role != "teacher":
        return None
    return _BLOCKED_TEACHER_MESSAGES.get(user.approval_status)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def email_hash(email: str) -> str:
        return hashlib.sha256(email.encode("utf-8")).hexdigest()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def register(self, *, username: str, password: str, role: str = "student", identity_no: str = "",
                 email: str | None = None) -> User:
        normalized_username = username.strip()
        normalized_identity = identity_no.strip().upper()
        normalized_email = self.normalize_email(email) if email else None
        if self.users.get_by_username(normalized_username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
        if self.db.query(User).filter(User.identity_no == normalized_identity).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="学号或工号已注册")
        if normalized_email and self.db.query(User).filter(User.email_hash == self.email_hash(normalized_email)).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已注册")
        try:
            return self.users.create(
                username=normalized_username,
                password_hash=hash_password(password),
                role=role,
                identity_no=normalized_identity,
                email=normalized_email,
                email_hash=self.email_hash(normalized_email) if normalized_email else None,
                approval_status="pending" if role == "teacher" else "approved",
            )
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名、学号或工号已存在") from None

    def login(self, *, username: str, password: str) -> tuple[str, User]:
        user = self.users.get_by_username(username.strip())
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        blocked_reason = teacher_authentication_block_reason(user)
        if blocked_reason:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=blocked_reason)
        if user.email and not user.email_verified_at:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请先验证邮箱后再登录")
        return create_access_token(str(user.id), user.auth_version), user

    def _create_token(
        self,
        *,
        user: User,
        purpose: str,
        request_ip: str | None = None,
        raw_token: str | None = None,
    ) -> str:
        raw_token = raw_token or secrets.token_urlsafe(32)
        now = utc_now()
        self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.purpose == purpose,
                   PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        self.db.add(
            PasswordResetToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=self._token_hash(raw_token),
                # MySQL may run with a non-UTC session timezone while the
                # application consistently uses UTC-naive datetimes.  Set
                # this explicitly instead of relying on ``server_default``
                # (which would otherwise make created_at appear 8 hours in
                # the future and trigger the reset rate limiter forever).
                created_at=now,
                expires_at=now + timedelta(minutes=settings.password_reset_token_expire_minutes),
                request_ip=request_ip,
            )
        )
        self.db.commit()
        return raw_token

    def request_email_verification(self, *, user: User, email: str, request_ip: str | None = None) -> None:
        normalized = self.normalize_email(email)
        email_hash = self.email_hash(normalized)
        duplicate = self.db.scalar(select(User).where(User.email_hash == email_hash, User.id != user.id))
        if duplicate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已被其他账号使用")
        user.email = normalized
        user.email_hash = email_hash
        user.email_verified_at = None
        self.db.commit()
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._create_token(user=user, purpose="email_verification", request_ip=request_ip, raw_token=code)
        EmailService().send(
            recipient=normalized,
            subject="思政智教邮箱验证",
            text=EmailService.verification_code_message(code),
        )

    def confirm_email_verification(self, *, email: str, code: str) -> User:
        now = utc_now()
        user = self.db.scalar(select(User).where(User.email_hash == self.email_hash(self.normalize_email(email))))
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期")
        token_row = self.db.scalar(select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.purpose == "email_verification",
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        ).order_by(PasswordResetToken.created_at.desc()).limit(1))
        if token_row is None or token_row.attempts >= 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期")
        if token_row.token_hash != self._token_hash(code):
            token_row.attempts += 1
            self.db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期")
        changed = self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_row.id, PasswordResetToken.used_at.is_(None),
                   PasswordResetToken.expires_at > now)
            .values(used_at=now)
        ).rowcount
        if changed != 1:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期")
        user.email_verified_at = now
        self.db.commit()
        self.db.refresh(user)
        return user

    def request_password_reset(self, *, identifier: str, request_ip: str | None = None) -> str:
        value = identifier.strip()
        looks_like_email = "@" in value
        user = self.users.get_by_username(value)
        if user is None and looks_like_email:
            user = self.db.scalar(select(User).where(User.email_hash == self.email_hash(self.normalize_email(value))))
        if user is None:
            return "email" if looks_like_email else "admin"
        if not user.email or not user.email_verified_at:
            if looks_like_email and user.email and self.normalize_email(user.email) == self.normalize_email(value):
                self.request_email_verification(user=user, email=user.email, request_ip=request_ip)
                return "verify_email"
            pending = self.db.scalar(select(PasswordResetRequest).where(
                PasswordResetRequest.user_id == user.id, PasswordResetRequest.status == "pending",
            ).order_by(PasswordResetRequest.requested_at.desc()).limit(1))
            if pending is None:
                self.db.add(PasswordResetRequest(user_id=user.id, request_ip=request_ip))
                self.db.commit()
            return "email" if looks_like_email else "admin"
        now = utc_now()
        latest = self.db.scalar(select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.purpose == "password_reset",
        ).order_by(PasswordResetToken.expires_at.desc()).limit(1))
        # ``expires_at`` is assigned by the application in UTC and is
        # therefore safe for both SQLite and MySQL.  Derive the creation time
        # from it so legacy MySQL rows written with a local-time server
        # default do not look like future tokens.
        latest_created_at = (
            latest.expires_at - timedelta(minutes=settings.password_reset_token_expire_minutes)
            if latest else None
        )
        if latest_created_at and (now - latest_created_at).total_seconds() < settings.password_reset_rate_limit_seconds:
            return "email"
        hourly_cutoff = (
            now - timedelta(hours=1) + timedelta(minutes=settings.password_reset_token_expire_minutes)
        )
        hourly_count = self.db.scalar(select(func.count(PasswordResetToken.id)).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.purpose == "password_reset",
            PasswordResetToken.expires_at >= hourly_cutoff,
        )) or 0
        if hourly_count >= settings.password_reset_hourly_limit:
            return "email"
        if request_ip:
            ip_count = self.db.scalar(select(func.count(PasswordResetToken.id)).where(
                PasswordResetToken.request_ip == request_ip,
                PasswordResetToken.purpose == "password_reset",
                PasswordResetToken.expires_at >= hourly_cutoff,
            )) or 0
            if ip_count >= settings.password_reset_hourly_limit * 3:
                return "email"
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._create_token(user=user, purpose="password_reset", request_ip=request_ip, raw_token=code)
        EmailService().send(
            recipient=user.email,
            subject="思政智教密码重置",
            text=EmailService.password_reset_code_message(code),
        )
        return "email"

    def confirm_password_reset(
        self,
        *,
        token: str | None = None,
        identifier: str | None = None,
        code: str | None = None,
        new_password: str,
    ) -> None:
        now = utc_now()
        if token:
            token_row = self.db.scalar(select(PasswordResetToken).where(
                PasswordResetToken.token_hash == self._token_hash(token),
                PasswordResetToken.purpose == "password_reset",
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            ))
        else:
            user = None
            if identifier:
                value = identifier.strip()
                user = self.users.get_by_username(value)
                if user is None and "@" in value:
                    user = self.db.scalar(select(User).where(
                        User.email_hash == self.email_hash(self.normalize_email(value))
                    ))
            token_row = self.db.scalar(select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id if user else False,
                PasswordResetToken.purpose == "password_reset",
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            ).order_by(PasswordResetToken.created_at.desc()).limit(1))
            if token_row is not None and token_row.attempts >= 5:
                token_row = None
            if token_row is not None and token_row.token_hash != self._token_hash(code or ""):
                token_row.attempts += 1
                self.db.commit()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码无效或已过期")
        if token_row is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置验证码无效或已过期")
        changed = self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_row.id, PasswordResetToken.used_at.is_(None),
                   PasswordResetToken.expires_at > now)
            .values(used_at=now)
        ).rowcount
        if changed != 1:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置验证码无效或已过期")
        user = self.users.get_by_id(token_row.user_id)
        if user is None:
            self.db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置验证码无效或已过期")
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.auth_version += 1
        user.must_change_password = False
        self.db.execute(delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.purpose == "password_reset",
            PasswordResetToken.id != token_row.id,
        ))
        self.db.commit()

    def admin_temporary_password(self, *, user_id: int, admin_id: int, request_ip: str | None = None) -> str:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        temporary_password = settings.admin_temporary_password
        now = utc_now()
        user.password_hash = hash_password(temporary_password)
        user.password_changed_at = now
        user.auth_version += 1
        user.must_change_password = True
        self.db.add(AdminPasswordResetAudit(admin_id=admin_id, target_user_id=user.id, request_ip=request_ip))
        now_request = utc_now()
        self.db.execute(update(PasswordResetRequest).where(
            PasswordResetRequest.user_id == user.id, PasswordResetRequest.status == "pending",
        ).values(status="handled", handled_at=now_request, handled_by=admin_id))
        self.db.commit()
        return temporary_password

    def change_password(self, *, user: User, new_password: str) -> None:
        now = utc_now()
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.auth_version += 1
        user.must_change_password = False
        self.db.commit()
