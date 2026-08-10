import json
from datetime import UTC, datetime, timedelta, timezone

from pydantic import BaseModel

from app.core.time import BUSINESS_TIMEZONE, to_business_time, to_utc_naive, utc_iso, utc_now
from app.schemas.common import ApiResponse, api_json_value


def test_utc_now_returns_naive_utc_time() -> None:
    before = datetime.now(UTC).replace(tzinfo=None)
    actual = utc_now()
    after = datetime.now(UTC).replace(tzinfo=None)

    assert actual.tzinfo is None
    assert before <= actual <= after


def test_to_utc_naive_converts_aware_offset() -> None:
    china_time = datetime(2026, 8, 10, 16, 30, tzinfo=timezone(timedelta(hours=8)))

    assert to_utc_naive(china_time) == datetime(2026, 8, 10, 8, 30)


def test_to_utc_naive_treats_naive_input_as_utc() -> None:
    stored_time = datetime(2026, 8, 10, 8, 30)

    assert to_utc_naive(stored_time) == stored_time
    assert to_utc_naive(stored_time).tzinfo is None


def test_utc_iso_and_business_time_are_protocol_explicit() -> None:
    stored_time = datetime(2026, 8, 10, 8, 30)

    assert utc_iso(stored_time) == "2026-08-10T08:30:00Z"
    assert to_business_time(stored_time).isoformat() == "2026-08-10T16:30:00+08:00"


def test_generic_api_response_does_not_guess_naive_datetime_basis() -> None:
    class NestedTime(BaseModel):
        created_time: datetime

    response = ApiResponse(data={
        "direct": datetime(2026, 8, 10, 8, 30),
        "nested": NestedTime(created_time=datetime(2026, 8, 10, 16, 30, tzinfo=BUSINESS_TIMEZONE)),
    })
    payload = json.loads(response.model_dump_json())

    assert payload["data"]["direct"] == "2026-08-10T08:30:00"
    assert payload["data"]["nested"]["created_time"] == "2026-08-10T16:30:00+08:00"


def test_sse_json_helper_only_normalizes_timezone_aware_values() -> None:
    payload = api_json_value({
        "legacy": datetime(2026, 8, 10, 16, 30),
        "explicit": datetime(2026, 8, 10, 16, 30, tzinfo=BUSINESS_TIMEZONE),
    })

    assert payload == {
        "legacy": "2026-08-10T16:30:00",
        "explicit": "2026-08-10T08:30:00Z",
    }
