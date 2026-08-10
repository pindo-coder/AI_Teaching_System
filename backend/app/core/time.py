"""Helpers for timestamps whose UTC or business-time basis is known.

Legacy ``DateTime`` columns are not globally assumed to be UTC: some contain
local wall time and have no marker.  Call these helpers only at boundaries
where the field contract or a per-row marker establishes its time basis.
"""

from datetime import UTC, datetime, timedelta, timezone, tzinfo


# 当前权威 RSS 均为中国大陆业务来源。固定 UTC+8 不依赖宿主机的
# zoneinfo/tzdata 安装状态，也不会受服务器本地时区影响。
BUSINESS_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def utc_now() -> datetime:
    """Return the current UTC time without ``tzinfo`` for database storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_naive(value: datetime, *, naive_timezone: tzinfo = UTC) -> datetime:
    """Normalize a datetime to UTC naive.

    Callers must only use the default for fields known to store UTC. Sources or
    marked legacy values with another basis must pass that timezone explicitly.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=naive_timezone)
    return value.astimezone(UTC).replace(tzinfo=None)


def utc_iso(value: datetime) -> str:
    """Return an unambiguous UTC ISO-8601 timestamp for HTTP/SSE protocols."""
    normalized = to_utc_naive(value).replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def to_business_time(value: datetime) -> datetime:
    """Convert a stored UTC datetime to the configured Chinese business time."""
    normalized = to_utc_naive(value).replace(tzinfo=UTC)
    return normalized.astimezone(BUSINESS_TIMEZONE)
