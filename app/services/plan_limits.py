"""
Plan limits and feature restrictions by subscription tier.
"""
from app.models.enums import PlanType

PLAN_LIMITS = {
    PlanType.FREE: {
        "emails_per_month": 50,
        "email_accounts": 1,
        "notification_channels": ["email"],
        "drafts_per_review": 0,
        "custom_templates": 0,
        "weekly_reports": False,
        "api_access": False,
    },
    PlanType.STARTER: {
        "emails_per_month": 500,
        "email_accounts": 1,
        "notification_channels": ["email", "telegram"],
        "drafts_per_review": 1,
        "custom_templates": 0,
        "weekly_reports": False,
        "api_access": False,
    },
    PlanType.PROFESSIONAL: {
        "emails_per_month": 2000,
        "email_accounts": 3,
        "notification_channels": ["email", "telegram", "sms"],
        "drafts_per_review": 3,
        "custom_templates": 5,
        "weekly_reports": True,
        "api_access": False,
    },
    PlanType.ENTERPRISE: {
        "emails_per_month": 10000,
        "email_accounts": 10,
        "notification_channels": ["email", "telegram", "sms"],
        "drafts_per_review": 3,
        "custom_templates": -1,  # unlimited
        "weekly_reports": True,
        "api_access": True,
    },
}


def get_plan_limit(plan: PlanType, feature: str):
    """Get the limit for a specific feature on a given plan."""
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS[PlanType.FREE])
    return limits.get(feature)
