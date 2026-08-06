from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.learning import LearningStage


AiTaskType = Literal[
    "question_answer",
    "chapter_summary",
    "preview_questions",
    "review_outline",
    "mock_questions",
    "note_polish",
    "note_expand",
    "note_outline",
    "note_knowledge_structure",
    "note_real_significance",
    "note_concept_compare",
    "news_study_note",
]

AiWorkspaceMode = Literal["chat", "agent"]
AiWorkspaceRole = Literal["student", "teacher", "admin"]


class AiAssistRequest(BaseModel):
    course_id: int
    chapter_id: int
    learning_stage: LearningStage
    task_type: AiTaskType = "question_answer"
    question: str = Field(min_length=1, max_length=2000)
    # 工作台助手使用这两个字段切换 Chat / Agent 和角色化提示；
    # 普通章节助手保持默认值即可，不影响现有接口。
    assistant_mode: AiWorkspaceMode = "chat"
    assistant_role: AiWorkspaceRole = "student"


class AiWorkspaceAssistRequest(BaseModel):
    mode: AiWorkspaceMode = "chat"
    role: AiWorkspaceRole = "student"
    course_id: int | None = Field(default=None, ge=1)
    chapter_id: int | None = Field(default=None, ge=1)
    learning_stage: LearningStage = "preview"
    task_type: AiTaskType = "question_answer"
    question: str = Field(min_length=1, max_length=2000)


class AiWorkspaceContextCandidate(BaseModel):
    """一个可由用户一键确认的教学范围候选项。"""

    course_id: int
    course_name: str
    teaching_class_id: int | None = None
    teaching_class_name: str | None = None


class AiWorkspaceContextData(BaseModel):
    """Agent 工作台可见的上下文，不把推断过程隐藏在模型黑盒中。"""

    course_id: int | None = None
    course_name: str | None = None
    chapter_id: int | None = None
    chapter_title: str | None = None
    teaching_class_id: int | None = None
    teaching_class_name: str | None = None
    learning_stage: LearningStage = "preview"
    source: Literal["page", "manual", "recent_learning", "default_class", "assignment", "none"] = "none"
    confidence: Literal["high", "medium", "low"] = "low"
    requires_chapter_selection: bool = False
    chapters: list[dict[str, object]] = Field(default_factory=list)
    candidates: list[AiWorkspaceContextCandidate] = Field(default_factory=list)
    state_summary: list[str] = Field(default_factory=list)


class AiWorkspaceContextRequest(BaseModel):
    course_id: int | None = Field(default=None, ge=1)
    chapter_id: int | None = Field(default=None, ge=1)
    teaching_class_id: int | None = Field(default=None, ge=1)
    learning_stage: LearningStage = "preview"
    page_name: str | None = Field(default=None, max_length=100)


class AiWorkspaceAgentRequest(AiWorkspaceContextRequest):
    """面向可执行教学任务的 Agent 请求；创建草稿不等于发布。"""

    role: AiWorkspaceRole = "student"
    question: str = Field(min_length=1, max_length=2000)
    # 重试/继续时复用已持久化的范围快照，避免刷新页面后误切换到其他教材。
    execution_id: int | None = Field(default=None, ge=1)


class AiAgentExecutionResolveRequest(BaseModel):
    resolution: Literal["confirmed", "cancelled"]
    note: str | None = Field(default=None, max_length=500)


class AiSource(BaseModel):
    source_type: str
    source_title: str
    course_id: int
    chapter_id: int
    excerpt: str
    position: str = "当前专题正文"
    document_id: int | None = None
    vector_id: str | None = None
    section_path: str | None = None
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    paragraph_index: int | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    evidence_type: str = "教材直接依据"
    material_type: str = "textbook"
    publisher: str | None = None
    published_date: str | None = None
    source_url: str | None = None


class AiAssistData(BaseModel):
    answer: str
    grounded: bool
    model: str
    sources: list[AiSource] = Field(default_factory=list)
