# Pydantic schemas
from app.schemas.auth import (
    RefreshTokenRequest,
    Token,
    TokenPayload,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.schemas.email import (
    EmailCheckResult,
    GmailMessage,
    MessageDetails,
)
from app.schemas.gmail import (
    EmailAccountListResponse,
    EmailAccountResponse,
    EmailAccountUpdate,
    OAuthCallbackResponse,
    OAuthConnectResponse,
)
from app.schemas.analysis import (
    AnalysisState,
    ReviewAnalysis,
)
from app.schemas.response import (
    DraftResponseCreate,
    DraftResponseListResponse,
    DraftResponseResponse,
    RegenerateRequest,
)
from app.schemas.reviews import (
    PaginatedResponse,
    ReviewDetail,
    ReviewListItem,
    ReviewListResponse,
    ReviewUpdate,
)
from app.schemas.analytics import (
    AnalyticsSummary,
    ProblemStat,
    TrendPoint,
)
from app.schemas.settings import (
    CompanySettingsResponse,
    CompanySettingsUpdate,
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
    ProfileResponse,
    ProfileUpdate,
)

__all__ = [
    # Auth
    "UserCreate",
    "UserLogin",
    "Token",
    "TokenPayload",
    "RefreshTokenRequest",
    "UserResponse",
    # Gmail
    "EmailAccountResponse",
    "EmailAccountUpdate",
    "EmailAccountListResponse",
    "OAuthConnectResponse",
    "OAuthCallbackResponse",
    # Email
    "GmailMessage",
    "MessageDetails",
    "EmailCheckResult",
    # Analysis
    "ReviewAnalysis",
    "AnalysisState",
    # Response
    "DraftResponseCreate",
    "DraftResponseResponse",
    "DraftResponseListResponse",
    "RegenerateRequest",
    # Reviews
    "ReviewListItem",
    "ReviewDetail",
    "ReviewUpdate",
    "PaginatedResponse",
    "ReviewListResponse",
    # Analytics
    "AnalyticsSummary",
    "TrendPoint",
    "ProblemStat",
    # Settings
    "NotificationSettingsResponse",
    "NotificationSettingsUpdate",
    "CompanySettingsResponse",
    "CompanySettingsUpdate",
    "ProfileResponse",
    "ProfileUpdate",
]
