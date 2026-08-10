from datetime import datetime
import json
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TaskStatus = Literal["not_started", "in_progress", "completed"]


class LearningEventCreate(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: Literal["preview", "review", "exam"]
    event_type: Literal[
        "chapter_opened", "reading_progress", "ai_assist_used", "question_submitted",
        "note_saved", "activity_submitted", "quiz_completed"
    ]
    event_data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_data(self) -> "LearningEventCreate":
        try:
            encoded = json.dumps(self.event_data, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("学习行为数据必须是有效 JSON") from exc
        if len(encoded.encode("utf-8")) > 16 * 1024:
            raise ValueError("学习行为数据不能超过 16 KB")

        if self.event_type == "reading_progress":
            raw_percent = self.event_data.get("percent")
            if isinstance(raw_percent, bool):
                raise ValueError("阅读进度必须是 0 到 100 的数字")
            try:
                percent = float(raw_percent)
            except (TypeError, ValueError) as exc:
                raise ValueError("阅读进度必须是 0 到 100 的数字") from exc
            if not isfinite(percent) or not 0 <= percent <= 100:
                raise ValueError("阅读进度必须是 0 到 100 的数字")
            self.event_data = {"percent": round(percent, 2)}
        elif self.event_type in {"question_submitted", "activity_submitted", "quiz_completed"}:
            count = self.event_data.get("count", 1)
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
                raise ValueError("学习行为次数必须是 1 到 100 的整数")
        elif self.event_type == "note_saved":
            content = self.event_data.get("content")
            if not isinstance(content, str) or len(content) > 10_000:
                raise ValueError("笔记内容格式无效或超过 10000 字")
        elif self.event_type == "ai_assist_used":
            task_type = self.event_data.get("task_type")
            if task_type is not None and (
                not isinstance(task_type, str) or len(task_type) > 50
            ):
                raise ValueError("AI 任务类型格式无效")
        return self


class LearningTelemetryCreate(LearningEventCreate):
    """Only non-authoritative browser telemetry is accepted directly."""

    event_type: Literal["chapter_opened", "reading_progress"]


class LearningQuestionCreate(BaseModel):
    course_id: int = Field(gt=0)
    chapter_id: int = Field(gt=0)
    learning_stage: Literal["preview", "review", "exam"]
    content: str = Field(min_length=2, max_length=2000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("学习问题至少需要 2 个有效字符")
        return normalized


class TaskPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    chapter_id: int
    learning_stage: str
    task_type: str
    title: str
    description: str
    weight: int
    sort_order: int
    status: TaskStatus = "not_started"
    progress_value: int = 0
    evidence_summary: str = ""
    completed_time: datetime | None = None


class TaskProgressSummary(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: str
    completed_count: int
    total_count: int
    progress: int
    tasks: list[TaskPointRead]
