from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.time import utc_iso


T = TypeVar("T")


def api_json_value(value: Any) -> Any:
    """Recursively make SSE data JSON-safe without guessing naive timezones.

    A number of legacy columns contain local wall times while others contain
    UTC.  Only timezone-aware values can be normalized safely at this generic
    boundary; field-specific schemas handle columns with a known time basis.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat()
        return utc_iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return api_json_value(value.model_dump(mode="python", by_alias=True))
    if isinstance(value, Mapping):
        return {key: api_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [api_json_value(item) for item in value]
    return value


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "操作成功"
    data: T


class HealthData(BaseModel):
    status: str
    environment: str
