"""
Email message schemas for Gmail API integration.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GmailMessage(BaseModel):
    """Gmail message structure from API."""

    message_id: str = Field(..., description="Unique Gmail message ID")
    thread_id: str = Field(..., description="Gmail thread ID")
    sender_email: str = Field(..., description="Sender's email address")
    sender_name: Optional[str] = Field(None, description="Sender's display name")
    subject: str = Field(..., description="Email subject")
    body_text: str = Field("", description="Plain text email body")
    received_at: datetime = Field(..., description="When the email was received")
    labels: List[str] = Field(default_factory=list, description="Gmail labels")

    model_config = {"from_attributes": True}


class MessageDetails(BaseModel):
    """Detailed message information from Gmail API."""

    message_id: str
    thread_id: str
    sender_email: str
    sender_name: Optional[str] = None
    subject: str
    body_text: str = ""
    body_html: Optional[str] = None
    received_at: datetime
    labels: List[str] = Field(default_factory=list)
    snippet: Optional[str] = None
    attachments: List[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class EmailCheckResult(BaseModel):
    """Result of email check operation."""

    account_id: str
    emails_checked: int
    new_emails: int
    errors: List[str] = Field(default_factory=list)
    last_checked_at: datetime
