from email.message import EmailMessage
import smtplib
from urllib.parse import quote

from app.core.config import settings


class EmailService:
    """Small mail adapter with a console backend for local development/tests."""

    def send(self, *, recipient: str, subject: str, text: str) -> None:
        if settings.mail_backend == "console":
            if settings.app_env == "production":
                raise RuntimeError("Console mail backend is not allowed in production")
            print(f"[mail:console] to={recipient} subject={subject}\n{text}")
            return
        if settings.mail_backend != "smtp":
            raise RuntimeError("MAIL_BACKEND must be console or smtp")
        if not settings.mail_host or not settings.mail_from:
            raise RuntimeError("SMTP mail configuration is incomplete")

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.mail_from
        message["To"] = recipient
        message.set_content(text)
        if settings.mail_use_ssl:
            with smtplib.SMTP_SSL(settings.mail_host, settings.mail_port, timeout=15) as smtp:
                if settings.mail_username and settings.mail_password:
                    smtp.login(settings.mail_username, settings.mail_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.mail_host, settings.mail_port, timeout=15) as smtp:
                smtp.starttls()
                if settings.mail_username and settings.mail_password:
                    smtp.login(settings.mail_username, settings.mail_password)
                smtp.send_message(message)

    @staticmethod
    def reset_link(token: str) -> str:
        return f"{settings.password_reset_url}?token={quote(token)}"

    @staticmethod
    def verification_code_message(code: str) -> str:
        return f"你的邮箱验证码是：{code}\n验证码有效期 {settings.password_reset_token_expire_minutes} 分钟，请勿转发给他人。"

    @staticmethod
    def password_reset_code_message(code: str) -> str:
        return f"你的密码重置验证码是：{code}\n验证码有效期 {settings.password_reset_token_expire_minutes} 分钟，请勿转发给他人。"
