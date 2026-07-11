"""集中导入模型，使 SQLAlchemy metadata 注册全部数据表。"""

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.learning_progress import LearningProgress
from app.models.user import User

__all__ = ["User", "Course", "Chapter", "LearningProgress", "KnowledgeDocument"]
