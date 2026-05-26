"""Import order matters for SQLAlchemy relationship resolution."""
from app.models.tenant import Tenant                    # noqa
from app.models.user import User, UserRole              # noqa
from app.models.topic import Topic                      # noqa
from app.models.question import Question, QuestionOption, Difficulty, QuestionType  # noqa
from app.models.exam_set import ExamSet, ExamSetQuestion              # noqa
from app.models.exam_session import ExamSession, ExamAttemptAnswer    # noqa
from app.models.quiz_attempt import QuizAttempt                       # noqa
from app.models.plan import Plan, PlanExamSet, PlanCourse              # noqa
from app.models.subscription import Subscription                     # noqa
from app.models.offer import OfferCode, OfferRedemption                # noqa
from app.models.payment import Payment, WebhookEvent                 # noqa
from app.models.lead import Lead, LeadSource                         # noqa
from app.models.audit_log import AuditLog                            # noqa
from app.models.journey_event import JourneyEvent                    # noqa
from app.models.visitor_insights_daily import VisitorInsightsDaily   # noqa
from app.models.system_setting import SystemSetting                  # noqa
from app.models.llm_provider import LLMProviderConfig                # noqa
from app.models.assistant_log import AssistantLog                    # noqa
from app.models.assistant_flagged_turn import AssistantFlaggedTurn    # noqa
from app.models.rag_chunk import RagChunk                            # noqa
from app.models.rag_document import RagDocument                      # noqa
from app.models.payment_provider import PaymentProviderConfig    # noqa
from app.models.faq import FaqItem                                # noqa
from app.models.content_page import ContentPage                   # noqa
from app.models.lms import (                                       # noqa
    Course, Chapter, Lesson, LessonFile,
    Enrollment, LessonProgress,
    CourseCategory, CourseCategoryLink, CourseAnnouncement,
    LessonNote, CourseReview,
    LmsQuiz, LmsQuizQuestion, LmsQuizQuestionOption,
    LmsQuizAttempt, LmsQuizAttemptAnswer,
)
from app.models.zoom import ZoomSession, Recording                  # noqa
from app.models.social import Campaign, CampaignRun                  # noqa
