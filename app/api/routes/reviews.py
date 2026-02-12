"""
API routes for reviews and draft responses.

Endpoints:
- GET /api/reviews - List reviews with filters and pagination
- GET /api/reviews/{id} - Get review details
- PATCH /api/reviews/{id} - Update review (is_processed, notes)
- GET /api/reviews/{id}/drafts - Get draft responses for a review
- POST /api/reviews/{id}/drafts/regenerate - Regenerate draft responses
- GET /api/reviews/{id}/drafts/{draft_id} - Get specific draft response
"""
import logging
import math
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_active_user, PLAN_HIERARCHY
from app.database import get_async_session
from app.models.draft_response import DraftResponse
from app.models.email_account import EmailAccount
from app.models.enums import PlanType, PriorityType, SentimentType
from app.models.review import Review
from app.models.user import User
from app.schemas.response import (
    DraftResponseListResponse,
    DraftResponseResponse,
    RegenerateRequest,
)
from app.schemas.reviews import (
    ReviewDetail,
    ReviewListItem,
    ReviewListResponse,
    ReviewUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["reviews"])


async def verify_review_access(
    review_id: UUID,
    user: User,
    db: AsyncSession,
) -> Review:
    """
    Verify that the user has access to the review.

    Args:
        review_id: UUID of the review
        user: Current user
        db: Database session

    Returns:
        Review object if access is granted

    Raises:
        HTTPException: If review not found or access denied
    """
    # Get review
    result = await db.execute(
        select(Review).where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    # Verify ownership through email account
    account_result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == review.email_account_id)
    )
    email_account = account_result.scalar_one_or_none()

    if not email_account or email_account.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this review",
        )

    return review


async def get_user_email_account_ids(user_id: UUID, db: AsyncSession) -> List[UUID]:
    """Get all email account IDs for a user."""
    result = await db.execute(
        select(EmailAccount.id).where(EmailAccount.user_id == user_id)
    )
    return [row[0] for row in result.fetchall()]


def check_drafts_plan(user: User) -> int:
    """
    Check if user's plan supports draft generation.

    Args:
        user: Current user

    Returns:
        Number of variants allowed

    Raises:
        HTTPException: If plan doesn't support drafts
    """
    plan_variant_limits = {
        PlanType.FREE: 0,
        PlanType.STARTER: 1,
        PlanType.PROFESSIONAL: 3,
        PlanType.ENTERPRISE: 3,
    }

    user_plan = PlanType(user.plan)
    num_variants = plan_variant_limits.get(user_plan, 0)

    if num_variants == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Draft responses are not available on the FREE plan. Please upgrade to STARTER or higher.",
        )

    return num_variants


# ===== Reviews List and Details Endpoints =====

@router.get(
    "",
    response_model=ReviewListResponse,
    summary="List reviews with filters",
    description="Returns a paginated list of reviews with optional filters for sentiment, priority, date range, and search.",
)
async def list_reviews(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    sentiment: Optional[str] = Query(None, description="Filter by sentiment (positive/negative/neutral)"),
    priority: Optional[str] = Query(None, description="Filter by priority (critical/important/normal)"),
    date_from: Optional[datetime] = Query(None, description="Filter from date"),
    date_to: Optional[datetime] = Query(None, description="Filter to date"),
    search: Optional[str] = Query(None, description="Search in subject and sender"),
    is_processed: Optional[bool] = Query(None, description="Filter by processed status"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ReviewListResponse:
    """
    List reviews with filtering and pagination.

    Args:
        page: Page number (starting from 1)
        per_page: Number of items per page (max 100)
        sentiment: Filter by sentiment type
        priority: Filter by priority level
        date_from: Filter reviews received after this date
        date_to: Filter reviews received before this date
        search: Search term for subject and sender
        is_processed: Filter by processing status
        user: Current authenticated user
        db: Database session

    Returns:
        Paginated list of reviews
    """
    # Get user's email account IDs
    account_ids = await get_user_email_account_ids(user.id, db)
    if not account_ids:
        return ReviewListResponse(items=[], total=0, page=page, per_page=per_page, pages=0)

    # Build query conditions
    conditions = [Review.email_account_id.in_(account_ids)]

    if sentiment:
        if sentiment not in [s.value for s in SentimentType]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sentiment. Must be one of: {[s.value for s in SentimentType]}",
            )
        conditions.append(Review.sentiment == sentiment)

    if priority:
        if priority not in [p.value for p in PriorityType]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid priority. Must be one of: {[p.value for p in PriorityType]}",
            )
        conditions.append(Review.priority == priority)

    if date_from:
        conditions.append(Review.received_at >= date_from)

    if date_to:
        conditions.append(Review.received_at <= date_to)

    if is_processed is not None:
        conditions.append(Review.is_processed == is_processed)

    if search:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                Review.subject.ilike(search_term),
                Review.sender_email.ilike(search_term),
                Review.sender_name.ilike(search_term),
            )
        )

    # Get total count
    count_result = await db.execute(
        select(func.count(Review.id)).where(and_(*conditions))
    )
    total = count_result.scalar() or 0

    # Calculate pagination
    pages = math.ceil(total / per_page) if total > 0 else 0
    offset = (page - 1) * per_page

    # Get reviews
    result = await db.execute(
        select(Review)
        .where(and_(*conditions))
        .order_by(Review.received_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    reviews = result.scalars().all()

    # Convert to response
    items = [
        ReviewListItem(
            id=review.id,
            sender_email=review.sender_email,
            sender_name=review.sender_name,
            subject=review.subject,
            sentiment=review.sentiment,
            priority=review.priority,
            summary=review.summary,
            problems=review.problems or [],
            is_processed=review.is_processed,
            received_at=review.received_at,
            notes=review.notes,
        )
        for review in reviews
    ]

    return ReviewListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/{review_id}",
    response_model=ReviewDetail,
    summary="Get review details",
    description="Returns detailed information about a specific review including drafts.",
)
async def get_review(
    review_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ReviewDetail:
    """
    Get detailed review information.

    Args:
        review_id: UUID of the review
        user: Current authenticated user
        db: Database session

    Returns:
        Review details including drafts
    """
    # Verify access
    review = await verify_review_access(review_id, user, db)

    # Get email account for email address
    account_result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == review.email_account_id)
    )
    email_account = account_result.scalar_one()

    # Get draft responses
    drafts_result = await db.execute(
        select(DraftResponse)
        .where(DraftResponse.review_id == review.id)
        .order_by(DraftResponse.variant_number)
    )
    drafts = drafts_result.scalars().all()

    draft_responses = [
        DraftResponseResponse(
            id=draft.id,
            review_id=draft.review_id,
            content=draft.content,
            tone=draft.tone,
            variant_number=draft.variant_number,
            created_at=draft.created_at,
        )
        for draft in drafts
    ]

    return ReviewDetail(
        id=review.id,
        sender_email=review.sender_email,
        sender_name=review.sender_name,
        subject=review.subject,
        sentiment=review.sentiment,
        priority=review.priority,
        summary=review.summary,
        problems=review.problems or [],
        is_processed=review.is_processed,
        received_at=review.received_at,
        notes=review.notes,
        suggestions=review.suggestions or [],
        drafts=draft_responses,
        email_account_email=email_account.email,
        created_at=review.created_at,
        processed_at=review.processed_at,
    )


@router.patch(
    "/{review_id}",
    response_model=ReviewDetail,
    summary="Update review",
    description="Update review fields such as is_processed status and notes.",
)
async def update_review(
    review_id: UUID,
    data: ReviewUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ReviewDetail:
    """
    Update a review.

    Args:
        review_id: UUID of the review
        data: Update data
        user: Current authenticated user
        db: Database session

    Returns:
        Updated review details
    """
    # Verify access
    review = await verify_review_access(review_id, user, db)

    # Update fields
    if data.is_processed is not None:
        review.is_processed = data.is_processed
        if data.is_processed and not review.processed_at:
            review.processed_at = datetime.utcnow()

    if data.notes is not None:
        review.notes = data.notes

    await db.flush()

    # Get email account for email address
    account_result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == review.email_account_id)
    )
    email_account = account_result.scalar_one()

    # Get draft responses
    drafts_result = await db.execute(
        select(DraftResponse)
        .where(DraftResponse.review_id == review.id)
        .order_by(DraftResponse.variant_number)
    )
    drafts = drafts_result.scalars().all()

    draft_responses = [
        DraftResponseResponse(
            id=draft.id,
            review_id=draft.review_id,
            content=draft.content,
            tone=draft.tone,
            variant_number=draft.variant_number,
            created_at=draft.created_at,
        )
        for draft in drafts
    ]

    return ReviewDetail(
        id=review.id,
        sender_email=review.sender_email,
        sender_name=review.sender_name,
        subject=review.subject,
        sentiment=review.sentiment,
        priority=review.priority,
        summary=review.summary,
        problems=review.problems or [],
        is_processed=review.is_processed,
        received_at=review.received_at,
        notes=review.notes,
        suggestions=review.suggestions or [],
        drafts=draft_responses,
        email_account_email=email_account.email,
        created_at=review.created_at,
        processed_at=review.processed_at,
    )


# ===== Draft Response Endpoints =====

@router.get(
    "/{review_id}/drafts",
    response_model=DraftResponseListResponse,
    summary="Get draft responses for a review",
    description="Returns all generated draft responses for a specific review. Requires STARTER plan or higher.",
)
async def get_review_drafts(
    review_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> DraftResponseListResponse:
    """
    Get all draft responses for a review.

    Args:
        review_id: UUID of the review
        user: Current authenticated user
        db: Database session

    Returns:
        List of draft responses
    """
    # Check plan
    check_drafts_plan(user)

    # Verify access to review
    review = await verify_review_access(review_id, user, db)

    # Get draft responses
    result = await db.execute(
        select(DraftResponse)
        .where(DraftResponse.review_id == review.id)
        .order_by(DraftResponse.variant_number)
    )
    drafts = result.scalars().all()

    draft_responses = [
        DraftResponseResponse(
            id=draft.id,
            review_id=draft.review_id,
            content=draft.content,
            tone=draft.tone,
            variant_number=draft.variant_number,
            created_at=draft.created_at,
        )
        for draft in drafts
    ]

    return DraftResponseListResponse(
        drafts=draft_responses,
        total=len(draft_responses),
    )


@router.post(
    "/{review_id}/drafts/regenerate",
    response_model=dict,
    summary="Regenerate draft responses",
    description="Triggers regeneration of draft responses for a review. Requires STARTER plan or higher.",
)
async def regenerate_review_drafts(
    review_id: UUID,
    request: Optional[RegenerateRequest] = None,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> dict:
    """
    Regenerate draft responses for a review.

    Triggers an async task to regenerate drafts with optional tone override.

    Args:
        review_id: UUID of the review
        request: Optional regeneration parameters
        user: Current authenticated user
        db: Database session

    Returns:
        Status message with task info
    """
    # Check plan
    num_variants = check_drafts_plan(user)

    # Verify access to review
    review = await verify_review_access(review_id, user, db)

    if not review.is_processed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Review has not been analyzed yet. Please wait for analysis to complete.",
        )

    # Get override tone if provided
    override_tone = None
    if request and request.tone:
        override_tone = request.tone

    # Trigger regeneration task
    from app.tasks.response_tasks import regenerate_response_drafts

    task = regenerate_response_drafts.delay(str(review_id), override_tone)

    logger.info(f"Triggered regeneration task {task.id} for review {review_id}")

    return {
        "status": "regeneration_started",
        "task_id": task.id,
        "review_id": str(review_id),
        "tone": override_tone,
        "variants": num_variants,
        "message": f"Regenerating {num_variants} draft response(s). Check back shortly.",
    }


@router.get(
    "/{review_id}/drafts/{draft_id}",
    response_model=DraftResponseResponse,
    summary="Get a specific draft response",
    description="Returns a specific draft response by ID.",
)
async def get_draft(
    review_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> DraftResponseResponse:
    """
    Get a specific draft response.

    Args:
        review_id: UUID of the review
        draft_id: UUID of the draft response
        user: Current authenticated user
        db: Database session

    Returns:
        Draft response details
    """
    # Check plan
    check_drafts_plan(user)

    # Verify access to review
    await verify_review_access(review_id, user, db)

    # Get the draft
    result = await db.execute(
        select(DraftResponse).where(
            DraftResponse.id == draft_id,
            DraftResponse.review_id == review_id,
        )
    )
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft response not found",
        )

    return DraftResponseResponse(
        id=draft.id,
        review_id=draft.review_id,
        content=draft.content,
        tone=draft.tone,
        variant_number=draft.variant_number,
        created_at=draft.created_at,
    )
