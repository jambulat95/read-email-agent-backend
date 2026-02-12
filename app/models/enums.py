"""
Enum types for database models.
"""
from enum import Enum


class PlanType(str, Enum):
    """User subscription plan types."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SentimentType(str, Enum):
    """Sentiment analysis results for reviews."""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class PriorityType(str, Enum):
    """Priority levels for reviews."""
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"


class ResponseTone(str, Enum):
    """Tone options for auto-generated responses."""
    FORMAL = "formal"
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"


class SubscriptionStatus(str, Enum):
    """Stripe subscription status."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"
    INCOMPLETE = "incomplete"
