from collections.abc import Sequence
from datetime import datetime, timedelta
from hashlib import sha256
import logging
from math import isfinite
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.core.time import utc_now
from app.models.ai_media_asset import AiMediaAsset
from app.models.chapter import Chapter
from app.models.course import Course
from app.models.user import User


DEFAULT_IMAGE_MAX_MB = 5
DEFAULT_AUDIO_MAX_MB = 10
DEFAULT_AUDIO_MAX_SECONDS = 60.0
DEFAULT_MEDIA_RETENTION_HOURS = 24
DEFAULT_USER_QUOTA_MB = 50
UPLOAD_CHUNK_BYTES = 1024 * 1024

logger = logging.getLogger(__name__)

SUPPORTED_MEDIA: dict[str, tuple[str, str]] = {
    "image/jpeg": ("image", ".jpg"),
    "image/png": ("image", ".png"),
    "image/webp": ("image", ".webp"),
    "audio/webm": ("audio", ".webm"),
    "audio/wav": ("audio", ".wav"),
    "audio/mpeg": ("audio", ".mp3"),
    "audio/mp4": ("audio", ".mp4"),
    "audio/ogg": ("audio", ".ogg"),
}


class AiMediaError(RuntimeError):
    """Base error for media asset operations."""


class AiMediaValidationError(AiMediaError):
    pass


class AiMediaTooLargeError(AiMediaError):
    def __init__(self, media_kind: str, max_bytes: int) -> None:
        self.media_kind = media_kind
        self.max_bytes = max_bytes
        super().__init__(f"{media_kind} exceeds {max_bytes} bytes")


class AiMediaQuotaExceededError(AiMediaError):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"media quota exceeds {max_bytes} bytes")


class AiMediaNotFoundError(AiMediaError):
    pass


class AiMediaStorageError(AiMediaError):
    pass


class AiMediaRuntimeUnavailableError(AiMediaError):
    pass


def _normalized_mime_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _detected_mime_type(header: bytes) -> str | None:
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"ID3") or _looks_like_mpeg_audio_frame(header):
        return "audio/mpeg"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "audio/mp4"
    if header.startswith(b"OggS"):
        return "audio/ogg"
    return None


def _looks_like_mpeg_audio_frame(header: bytes) -> bool:
    if len(header) < 3 or header[0] != 0xFF or header[1] & 0xE0 != 0xE0:
        return False
    version_bits = (header[1] >> 3) & 0x03
    layer_bits = (header[1] >> 1) & 0x03
    bitrate_index = (header[2] >> 4) & 0x0F
    sample_rate_index = (header[2] >> 2) & 0x03
    return (
        version_bits != 0x01
        and layer_bits != 0
        and bitrate_index not in {0, 0x0F}
        and sample_rate_index != 0x03
    )


def _safe_original_filename(filename: str | None) -> str:
    basename = (filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(char for char in basename if char >= " " and char != "\x7f").strip()
    return (cleaned or "upload")[:255]


def image_max_bytes() -> int:
    configured = int(getattr(settings, "ai_media_max_image_mb", DEFAULT_IMAGE_MAX_MB))
    return configured * 1024 * 1024


def audio_max_bytes() -> int:
    configured = int(getattr(settings, "ai_media_max_audio_mb", DEFAULT_AUDIO_MAX_MB))
    return configured * 1024 * 1024


def audio_max_duration_seconds() -> float:
    configured = float(
        getattr(settings, "ai_media_max_audio_seconds", DEFAULT_AUDIO_MAX_SECONDS)
    )
    return configured


def media_retention_hours() -> int:
    return int(
        getattr(settings, "ai_media_retention_hours", DEFAULT_MEDIA_RETENTION_HOURS)
    )


def media_user_quota_bytes() -> int:
    configured = int(
        getattr(settings, "ai_media_user_quota_mb", DEFAULT_USER_QUOTA_MB)
    )
    return configured * 1024 * 1024


def audio_probe_binary() -> str | None:
    configured = str(getattr(settings, "ai_media_ffprobe_binary", "ffprobe") or "ffprobe")
    discovered = shutil.which(configured)
    if discovered:
        return discovered
    candidate = Path(configured)
    return str(candidate) if candidate.is_file() else None


def audio_probe_available() -> bool:
    return audio_probe_binary() is not None


def probe_audio_duration_seconds(path: Path) -> float:
    """Read duration from the stored media stream; never trust the form field."""

    binary = audio_probe_binary()
    if binary is None:
        raise AiMediaRuntimeUnavailableError("服务器缺少 ffprobe，语音上传已安全禁用")
    try:
        result = subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AiMediaRuntimeUnavailableError("服务器暂时无法验证音频时长") from exc
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise AiMediaValidationError("无法从音频文件验证真实时长") from exc
    if result.returncode != 0 or not isfinite(duration) or duration <= 0:
        raise AiMediaValidationError("无法从音频文件验证真实时长")
    return duration


class AiMediaService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def media_root() -> Path:
        configured = getattr(settings, "ai_media_directory", "../knowledge_base/ai_media")
        raw_path = Path(str(configured or "../knowledge_base/ai_media"))
        return raw_path.resolve() if raw_path.is_absolute() else (BACKEND_DIR / raw_path).resolve()

    @classmethod
    def path_for(cls, asset: AiMediaAsset) -> Path:
        root = cls.media_root()
        candidate = (root / asset.storage_key).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise AiMediaStorageError("媒体文件路径无效") from exc
        return candidate

    async def create(
        self,
        *,
        owner_user_id: int,
        upload: UploadFile,
        course_id: int | None = None,
        chapter_id: int | None = None,
        duration_seconds: float | None = None,
    ) -> AiMediaAsset:
        mime_type = _normalized_mime_type(upload.content_type)
        media_spec = SUPPORTED_MEDIA.get(mime_type)
        if media_spec is None:
            raise AiMediaValidationError(
                "仅支持 JPEG、PNG、WebP 图片和 WebM、WAV、MP3、MP4、OGG 音频"
            )
        media_kind, suffix = media_spec
        if media_kind == "image" and duration_seconds is not None:
            raise AiMediaValidationError("图片不能设置音频时长")

        course_id, chapter_id = self._validated_context(course_id, chapter_id)
        self.cleanup_expired(owner_user_id=owner_user_id)
        max_bytes = image_max_bytes() if media_kind == "image" else audio_max_bytes()
        storage_key = f"{owner_user_id}/{uuid4().hex}{suffix}"
        final_path = self.media_root() / storage_key
        temporary_path = final_path.with_name(f".{final_path.name}.{uuid4().hex}.part")
        try:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            byte_size, content_hash = await self._stream_upload(
                upload=upload,
                target=temporary_path,
                declared_mime=mime_type,
                media_kind=media_kind,
                max_bytes=max_bytes,
            )
            if media_kind == "audio":
                # The browser-reported value is only a UX hint.  The persisted
                # value and the hard limit both use the server-side probe.
                duration_seconds = probe_audio_duration_seconds(temporary_path)
                max_duration = audio_max_duration_seconds()
                if duration_seconds > max_duration:
                    raise AiMediaValidationError(
                        f"音频真实时长不能超过 {max_duration:g} 秒"
                    )
            # Serialize quota decisions for one owner.  Docker runs one API
            # worker by default, but the database lock also protects parallel
            # requests and future multi-worker deployments from oversubscription.
            self.db.scalar(
                select(User.id)
                .where(User.id == owner_user_id)
                .with_for_update()
            )
            used_bytes = int(
                self.db.scalar(
                    select(func.coalesce(func.sum(AiMediaAsset.byte_size), 0)).where(
                        AiMediaAsset.owner_user_id == owner_user_id
                    )
                )
                or 0
            )
            quota_bytes = media_user_quota_bytes()
            if used_bytes + byte_size > quota_bytes:
                raise AiMediaQuotaExceededError(quota_bytes)
            temporary_path.replace(final_path)
        except (
            AiMediaQuotaExceededError,
            AiMediaRuntimeUnavailableError,
            AiMediaValidationError,
            AiMediaTooLargeError,
        ):
            self.db.rollback()
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            self.db.rollback()
            temporary_path.unlink(missing_ok=True)
            raise AiMediaStorageError("媒体文件保存失败") from exc

        asset = AiMediaAsset(
            owner_user_id=owner_user_id,
            course_id=course_id,
            chapter_id=chapter_id,
            media_kind=media_kind,
            original_filename=_safe_original_filename(upload.filename),
            mime_type=mime_type,
            byte_size=byte_size,
            sha256=content_hash,
            storage_key=storage_key,
            duration_seconds=duration_seconds,
            status="ready",
            created_time=utc_now(),
            updated_time=utc_now(),
        )
        try:
            self.db.add(asset)
            self.db.commit()
            self.db.refresh(asset)
        except Exception:
            self.db.rollback()
            final_path.unlink(missing_ok=True)
            raise
        return asset

    def list_owned(
        self,
        owner_user_id: int,
        *,
        media_kind: str | None = None,
        course_id: int | None = None,
        chapter_id: int | None = None,
        limit: int = 100,
    ) -> list[AiMediaAsset]:
        self.cleanup_expired(owner_user_id=owner_user_id)
        query = select(AiMediaAsset).where(AiMediaAsset.owner_user_id == owner_user_id)
        if media_kind is not None:
            query = query.where(AiMediaAsset.media_kind == media_kind)
        if course_id is not None:
            query = query.where(AiMediaAsset.course_id == course_id)
        if chapter_id is not None:
            query = query.where(AiMediaAsset.chapter_id == chapter_id)
        return list(
            self.db.scalars(
                query.order_by(AiMediaAsset.created_time.desc(), AiMediaAsset.id.desc()).limit(limit)
            )
        )

    def get_owned(self, asset_id: int, owner_user_id: int) -> AiMediaAsset:
        self.cleanup_expired(owner_user_id=owner_user_id)
        asset = self.db.scalar(
            select(AiMediaAsset).where(
                AiMediaAsset.id == asset_id,
                AiMediaAsset.owner_user_id == owner_user_id,
            )
        )
        if asset is None:
            # Return the same result for a missing asset and another user's asset.
            raise AiMediaNotFoundError("媒体资产不存在")
        return asset

    def get_owned_many(
        self, asset_ids: Sequence[int], owner_user_id: int
    ) -> list[AiMediaAsset]:
        self.cleanup_expired(owner_user_id=owner_user_id)
        ordered_ids = list(dict.fromkeys(asset_ids))
        if not ordered_ids:
            return []
        rows = self.db.scalars(
            select(AiMediaAsset).where(
                AiMediaAsset.id.in_(ordered_ids),
                AiMediaAsset.owner_user_id == owner_user_id,
            )
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(ordered_ids):
            raise AiMediaNotFoundError("一个或多个媒体资产不存在")
        return [by_id[asset_id] for asset_id in ordered_ids]

    def delete_owned(self, asset_id: int, owner_user_id: int) -> AiMediaAsset:
        asset = self.get_owned(asset_id, owner_user_id)
        stored_path = self.path_for(asset)
        try:
            stored_path.unlink(missing_ok=True)
        except OSError as exc:
            raise AiMediaStorageError("媒体文件删除失败") from exc
        try:
            self.db.delete(asset)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return asset

    def cleanup_expired(
        self,
        *,
        owner_user_id: int | None = None,
        now: datetime | None = None,
    ) -> int:
        """Delete expired private media rows and files.

        Cleanup runs on startup and on media access, so abandoned browser
        uploads cannot remain indefinitely even when client-side deletion fails.
        """

        cutoff = (now or utc_now()) - timedelta(hours=media_retention_hours())
        query = select(AiMediaAsset).where(AiMediaAsset.created_time < cutoff)
        if owner_user_id is not None:
            query = query.where(AiMediaAsset.owner_user_id == owner_user_id)
        expired = list(self.db.scalars(query).all())
        deleted = 0
        for asset in expired:
            try:
                self.path_for(asset).unlink(missing_ok=True)
            except (AiMediaStorageError, OSError):
                logger.exception("expired_ai_media_file_cleanup_failed asset_id=%s", asset.id)
                continue
            self.db.delete(asset)
            deleted += 1
        if deleted:
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return deleted

    def _validated_context(
        self, course_id: int | None, chapter_id: int | None
    ) -> tuple[int | None, int | None]:
        course = self.db.get(Course, course_id) if course_id is not None else None
        if course_id is not None and course is None:
            raise AiMediaValidationError("课程不存在")
        if chapter_id is None:
            return course_id, None
        chapter = self.db.get(Chapter, chapter_id)
        if chapter is None:
            raise AiMediaValidationError("专题不存在")
        if course_id is not None and chapter.course_id != course_id:
            raise AiMediaValidationError("专题与课程不匹配")
        return chapter.course_id, chapter_id

    @staticmethod
    async def _stream_upload(
        *,
        upload: UploadFile,
        target: Path,
        declared_mime: str,
        media_kind: str,
        max_bytes: int,
    ) -> tuple[int, str]:
        digest = sha256()
        byte_size = 0
        first_chunk = True
        with target.open("xb") as output:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                if first_chunk:
                    first_chunk = False
                    if _detected_mime_type(chunk[:64]) != declared_mime:
                        raise AiMediaValidationError("文件内容与声明的媒体类型不一致")
                byte_size += len(chunk)
                if byte_size > max_bytes:
                    raise AiMediaTooLargeError(media_kind, max_bytes)
                digest.update(chunk)
                output.write(chunk)
        if byte_size == 0:
            raise AiMediaValidationError("媒体文件不能为空")
        return byte_size, digest.hexdigest()


def cleanup_expired_media_assets(bind: Engine) -> int:
    """Startup hook for media abandoned before the normal request cleanup."""

    with Session(bind) as db:
        return AiMediaService(db).cleanup_expired()
