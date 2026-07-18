"""集中导入模型，使 SQLAlchemy metadata 注册全部数据表。"""

from app.models.chapter import Chapter
from app.models.course import Course
from app.models.knowledge_document import KnowledgeDocument
from app.models.learning_progress import LearningProgress
from app.models.user import User
from app.models.news_item import NewsItem
from app.models.classroom import ClassroomActivity, ClassroomResponse
from app.models.study_note import StudyNote
from app.models.review_schedule import ReviewSchedule
from app.models.learning_task import LearningTaskPoint, UserTaskProgress, LearningEvent
from app.models.study_chat_message import StudyChatMessage
from app.models.review_practice import ReviewPractice
from app.models.news_study_note import NewsStudyNote
from app.models.teacher_assignment import AssignmentRecipient, TeacherAssignment
from app.models.teaching_class import (
    AcademicTerm, ClassGroup, ClassGroupMember, ClassJoinRequest, ClassMembership,
    ClassRosterEntry, ClassTransferLog, CourseSubject, StudentCourseSeat, TeachingClass,
    TeachingClassMaterial, TeachingClassTeacher,
)
from app.models.citation import (
    CitationFeedback, DocumentOutlineNode, DocumentPage, IndexVersion, KnowledgeChunk,
    PageNumberRange, TextbookVersion,
)
from app.models.material_scope import (
    DocumentChapterScope, DocumentClassScope, DocumentCourseScope, DocumentKnowledgeTag,
)

__all__ = ["User", "Course", "Chapter", "LearningProgress", "KnowledgeDocument", "NewsItem", "ClassroomActivity", "ClassroomResponse", "StudyNote", "ReviewSchedule", "ReviewPractice", "LearningTaskPoint", "UserTaskProgress", "LearningEvent", "StudyChatMessage", "NewsStudyNote", "TeacherAssignment", "AssignmentRecipient", "CourseSubject", "AcademicTerm", "TeachingClass", "TeachingClassTeacher", "TeachingClassMaterial", "ClassRosterEntry", "ClassMembership", "StudentCourseSeat", "ClassGroup", "ClassGroupMember", "ClassJoinRequest", "ClassTransferLog", "TextbookVersion", "DocumentPage", "PageNumberRange", "DocumentOutlineNode", "KnowledgeChunk", "IndexVersion", "CitationFeedback", "DocumentCourseScope", "DocumentChapterScope", "DocumentClassScope", "DocumentKnowledgeTag"]
