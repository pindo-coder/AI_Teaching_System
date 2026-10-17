"""Versioned, bounded content contract for the SVG presentation workflow."""
from __future__ import annotations

from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from typing_extensions import Annotated

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PptVisualBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["illustration", "diagram", "none"]
    purpose: Text = Field(min_length=8, max_length=240)
    content_anchors: list[Annotated[Text, Field(min_length=2, max_length=40)]] = Field(min_length=1, max_length=4)
    scene_family: str = Field(default="", max_length=60)
    key_elements: list[Annotated[Text, Field(max_length=80)]] = Field(default_factory=list, max_length=6)
    difference: str = Field(default="", max_length=200)
    avoid: list[Annotated[Text, Field(max_length=80)]] = Field(default_factory=list, max_length=6)


class PptPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layout: Literal["title", "agenda", "question", "content", "concept", "process", "comparison", "timeline", "discussion", "summary"]
    title: Text = Field(max_length=60)
    takeaway: Text = Field(max_length=140)
    bullets: list[Annotated[Text, Field(max_length=160)]] = Field(min_length=1, max_length=5)
    speaker_notes: Text = Field(max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=10)
    visual_prompt: str = Field(default="", max_length=1200)
    visual_brief: PptVisualBrief | None = None
    diagram_labels: list[Annotated[Text, Field(min_length=2, max_length=32)]] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def grounded_labels(self):
        compact = lambda value: re.sub(r"\s+", "", value)
        sources = [compact(value) for value in [self.title, self.takeaway, *self.bullets]]
        labels = [compact(value) for value in self.diagram_labels]
        if len(labels) != len(set(labels)):
            raise ValueError("图解标签不能重复")
        if any(not any(label in source for source in sources) for label in labels):
            raise ValueError("图解标签必须逐字来自本页已确认标题、结论或正文，不能新增事实")
        if self.visual_brief:
            brief = self.visual_brief
            if any(not any(compact(anchor) in source for source in sources) for anchor in brief.content_anchors):
                raise ValueError("配图依据必须逐字来自本页已确认文字")
            if brief.kind == "illustration":
                if not self.visual_prompt.strip() or not brief.scene_family.strip() or len(brief.key_elements) < 2 or not brief.difference.strip():
                    raise ValueError("插图须有场景描述、场景类型、至少两个可见元素及与其他配图的区别")
            elif self.visual_prompt.strip():
                raise ValueError("图解或纯文字页不能安排生成插图")
            if brief.kind == "diagram" and len(self.diagram_labels) < 2:
                raise ValueError("图解至少需要两个已确认的短标签")
        return self

    @field_validator("title", "takeaway", "bullets")
    @classmethod
    def visible_copy(cls, value):
        for text in value if isinstance(value, list) else [value]:
            if re.search(r"[\[【]\s*资料\s*\d+\s*[\]】]", text):
                raise ValueError("资料编号只能放在引用字段和讲稿中，不可写进可见正文")
        return value


class PptTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text = Field(max_length=80)
    concept: Text = Field(max_length=300)
    topic_keywords: list[Annotated[Text, Field(max_length=30)]] = Field(default_factory=list, max_length=5)
    visual_motif: str = Field(default="", max_length=200)
    image_style: str = Field(default="", max_length=120)
    image_frame_shape: Literal["roundRect", "circle"] = "roundRect"
    background: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    primary: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")
    text: str = Field(pattern=r"^[0-9A-Fa-f]{6}$")


class PptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Text = Field(max_length=100)
    subtitle: str = Field(default="", max_length=200)
    design: PptTheme
    slides: list[PptPage] = Field(min_length=6, max_length=30)
