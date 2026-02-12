"""
Weekly report service for generating, storing, and delivering weekly analytics reports.

Includes:
- Report data aggregation
- AI-powered recommendations via Mistral
- PDF generation via WeasyPrint
- Email delivery via SendGrid
"""
import json
import logging
import os
import tempfile
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.email_account import EmailAccount
from app.models.enums import PlanType, PriorityType, SentimentType
from app.models.review import Review
from app.models.user import User
from app.models.weekly_report import WeeklyReport
from app.schemas.analytics import AnalyticsSummary, ProblemStat

logger = logging.getLogger(__name__)
settings = get_settings()

# Plans with access to weekly reports
REPORT_PLANS = {PlanType.PROFESSIONAL, PlanType.ENTERPRISE}

RECOMMENDATIONS_SYSTEM_PROMPT = """Ты - AI-консультант по работе с клиентами.
Анализируй статистику отзывов и давай конкретные, actionable рекомендации на русском языке."""

RECOMMENDATIONS_PROMPT = """На основе данных за неделю предложи 3-5 конкретных рекомендаций
для улучшения работы с клиентами.

Статистика:
- Всего отзывов: {total}
- Позитивных: {positive} ({positive_percent}%)
- Негативных: {negative} ({negative_percent}%)
- Нейтральных: {neutral} ({neutral_percent}%)
- Изменение vs прошлая неделя: {change}%

Топ проблем:
{problems_list}

Формат ответа: JSON массив строк.
{{"recommendations": ["рекомендация 1", "рекомендация 2", ...]}}"""

PDF_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <style>
        @page {{ size: A4; margin: 2cm; }}
        body {{ font-family: sans-serif; color: #333; line-height: 1.5; }}
        .header {{ text-align: center; border-bottom: 2px solid #0d6efd; padding-bottom: 16px; margin-bottom: 24px; }}
        .header h1 {{ color: #0d6efd; margin: 0; font-size: 24px; }}
        .header .dates {{ color: #666; font-size: 14px; margin-top: 8px; }}
        .stats-grid {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }}
        .stat-card {{ flex: 1; min-width: 120px; background: #f8f9fa; border-radius: 8px;
                      padding: 16px; text-align: center; }}
        .stat-card .value {{ font-size: 28px; font-weight: bold; color: #212529; }}
        .stat-card .label {{ font-size: 12px; color: #666; margin-top: 4px; }}
        .stat-positive .value {{ color: #28a745; }}
        .stat-negative .value {{ color: #dc3545; }}
        .stat-critical .value {{ color: #fd7e14; }}
        .section {{ margin-bottom: 24px; }}
        .section h2 {{ color: #495057; font-size: 18px; border-bottom: 1px solid #dee2e6;
                       padding-bottom: 8px; }}
        .problems-table {{ width: 100%; border-collapse: collapse; }}
        .problems-table th, .problems-table td {{ padding: 8px 12px; text-align: left;
                                                    border-bottom: 1px solid #dee2e6; }}
        .problems-table th {{ background: #f8f9fa; font-weight: 600; }}
        .recommendation {{ background: #e7f5ff; border-left: 4px solid #0d6efd;
                          padding: 12px 16px; margin-bottom: 8px; border-radius: 0 4px 4px 0; }}
        .change-up {{ color: #dc3545; }}
        .change-down {{ color: #28a745; }}
        .footer {{ text-align: center; color: #999; font-size: 11px; margin-top: 32px;
                   padding-top: 16px; border-top: 1px solid #dee2e6; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Еженедельный отчёт</h1>
        <div class="dates">{week_start} — {week_end}</div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="value">{total_reviews}</div>
            <div class="label">Всего отзывов</div>
        </div>
        <div class="stat-card stat-positive">
            <div class="value">{positive}</div>
            <div class="label">Позитивных</div>
        </div>
        <div class="stat-card stat-negative">
            <div class="value">{negative}</div>
            <div class="label">Негативных</div>
        </div>
        <div class="stat-card stat-critical">
            <div class="value">{critical}</div>
            <div class="label">Критических</div>
        </div>
    </div>

    {change_section}

    {problems_section}

    {critical_section}

    {recommendations_section}

    <div class="footer">
        Сгенерировано автоматически — Email Agent © {year}
    </div>
</body>
</html>
"""


class WeeklyReportService:
    """Service for generating and delivering weekly reports."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_week_range(self, ref_date: Optional[date] = None) -> tuple[date, date]:
        """Get Monday-Sunday range for the previous week."""
        today = ref_date or date.today()
        # Previous Monday
        week_start = today - timedelta(days=today.weekday() + 7)
        week_end = week_start + timedelta(days=6)
        return week_start, week_end

    async def _get_user_account_ids(self, user_id: UUID) -> List[UUID]:
        result = await self.db.execute(
            select(EmailAccount.id).where(EmailAccount.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]

    async def generate_report(self, user_id: UUID) -> WeeklyReport:
        """
        Generate a weekly report for a user.

        Steps:
        1. Aggregate data for the week
        2. Compare with previous week
        3. Generate AI recommendations
        4. Save report to DB
        """
        week_start, week_end = self._get_week_range()

        # Check if report already exists
        existing = await self.db.execute(
            select(WeeklyReport).where(
                and_(
                    WeeklyReport.user_id == user_id,
                    WeeklyReport.week_start == week_start,
                )
            )
        )
        existing_report = existing.scalar_one_or_none()
        if existing_report:
            logger.info(f"Report for user {user_id} week {week_start} already exists")
            return existing_report

        account_ids = await self._get_user_account_ids(user_id)

        # Current week data
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        week_end_dt = datetime.combine(week_end, datetime.max.time())

        conditions = [
            Review.email_account_id.in_(account_ids),
            Review.received_at >= week_start_dt,
            Review.received_at <= week_end_dt,
        ]

        reviews_result = await self.db.execute(
            select(Review).where(and_(*conditions))
        )
        reviews = list(reviews_result.scalars().all())

        total_reviews = len(reviews)

        # Sentiment breakdown
        sentiment_breakdown = {"positive": 0, "negative": 0, "neutral": 0}
        critical_review_ids = []
        all_problems: List[str] = []

        for review in reviews:
            sentiment = review.sentiment
            if sentiment == SentimentType.POSITIVE.value:
                sentiment_breakdown["positive"] += 1
            elif sentiment == SentimentType.NEGATIVE.value:
                sentiment_breakdown["negative"] += 1
            elif sentiment == SentimentType.NEUTRAL.value:
                sentiment_breakdown["neutral"] += 1

            if review.priority == PriorityType.CRITICAL.value:
                critical_review_ids.append(str(review.id))

            if review.problems:
                all_problems.extend(review.problems)

        # Top problems
        problem_counter = Counter(all_problems)
        top_problems = [
            {"name": name, "count": count}
            for name, count in problem_counter.most_common(10)
        ]

        # Previous week comparison
        prev_start = week_start - timedelta(days=7)
        prev_end = week_start - timedelta(days=1)
        prev_start_dt = datetime.combine(prev_start, datetime.min.time())
        prev_end_dt = datetime.combine(prev_end, datetime.max.time())

        prev_conditions = [
            Review.email_account_id.in_(account_ids),
            Review.received_at >= prev_start_dt,
            Review.received_at <= prev_end_dt,
        ]
        prev_result = await self.db.execute(
            select(Review.sentiment).where(and_(*prev_conditions))
        )
        prev_reviews = prev_result.fetchall()
        prev_total = len(prev_reviews)

        prev_sentiments = {"positive": 0, "negative": 0, "neutral": 0}
        for row in prev_reviews:
            s = row[0]
            if s in prev_sentiments:
                prev_sentiments[s] += 1

        total_change_percent = 0.0
        if prev_total > 0:
            total_change_percent = round(((total_reviews - prev_total) / prev_total) * 100, 1)

        sentiment_change = {}
        for key in ["positive", "negative", "neutral"]:
            curr = sentiment_breakdown[key]
            prev = prev_sentiments[key]
            if prev > 0:
                sentiment_change[key] = round(((curr - prev) / prev) * 100, 1)
            elif curr > 0:
                sentiment_change[key] = 100.0
            else:
                sentiment_change[key] = 0.0

        # AI recommendations
        recommendations = await self.generate_recommendations(
            total_reviews=total_reviews,
            sentiment_breakdown=sentiment_breakdown,
            top_problems=top_problems,
            total_change_percent=total_change_percent,
        )

        # Save report
        report = WeeklyReport(
            id=uuid.uuid4(),
            user_id=user_id,
            week_start=week_start,
            week_end=week_end,
            total_reviews=total_reviews,
            sentiment_breakdown=sentiment_breakdown,
            top_problems=top_problems,
            critical_reviews=critical_review_ids,
            total_change_percent=total_change_percent,
            sentiment_change=sentiment_change,
            recommendations=recommendations,
        )

        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)

        logger.info(f"Generated weekly report {report.id} for user {user_id}")
        return report

    async def generate_recommendations(
        self,
        total_reviews: int,
        sentiment_breakdown: Dict[str, int],
        top_problems: List[Dict],
        total_change_percent: float,
    ) -> List[str]:
        """Generate AI recommendations using Mistral."""
        if not settings.mistral_api_key:
            logger.warning("Mistral API key not configured, skipping recommendations")
            return ["Настройте API ключ Mistral для получения AI-рекомендаций"]

        try:
            llm = ChatMistralAI(
                api_key=settings.mistral_api_key,
                model=settings.ai_model,
                max_tokens=settings.ai_max_tokens,
                temperature=0.5,
            )

            positive_pct = round(sentiment_breakdown["positive"] / max(total_reviews, 1) * 100, 1)
            negative_pct = round(sentiment_breakdown["negative"] / max(total_reviews, 1) * 100, 1)
            neutral_pct = round(sentiment_breakdown["neutral"] / max(total_reviews, 1) * 100, 1)

            problems_list = "\n".join(
                f"- {p['name']}: {p['count']} случаев"
                for p in top_problems[:5]
            ) or "- Нет выявленных проблем"

            prompt = RECOMMENDATIONS_PROMPT.format(
                total=total_reviews,
                positive=sentiment_breakdown["positive"],
                positive_percent=positive_pct,
                negative=sentiment_breakdown["negative"],
                negative_percent=negative_pct,
                neutral=sentiment_breakdown["neutral"],
                neutral_percent=neutral_pct,
                change=total_change_percent,
                problems_list=problems_list,
            )

            messages = [
                SystemMessage(content=RECOMMENDATIONS_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = llm.invoke(messages)

            import re
            json_match = re.search(r"\{[^{}]*\}", response.content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                recs = result.get("recommendations", [])
                if isinstance(recs, list) and recs:
                    return recs[:5]

            return ["Продолжайте мониторить отзывы для накопления достаточной статистики"]

        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            return ["Не удалось сгенерировать рекомендации. Попробуйте позже."]

    async def generate_pdf(self, report: WeeklyReport) -> str:
        """
        Generate PDF from a weekly report.

        Returns:
            Path to the generated PDF file
        """
        try:
            from weasyprint import HTML
        except ImportError:
            logger.error("weasyprint not installed")
            raise RuntimeError("weasyprint is required for PDF generation")

        sentiment = report.sentiment_breakdown or {}
        total = report.total_reviews or 0

        # Change section
        change_section = ""
        if report.total_change_percent is not None:
            change_class = "change-up" if report.total_change_percent > 0 else "change-down"
            change_sign = "+" if report.total_change_percent > 0 else ""
            change_section = f"""
            <div class="section">
                <h2>Сравнение с прошлой неделей</h2>
                <p>Изменение количества отзывов:
                <span class="{change_class}"><strong>{change_sign}{report.total_change_percent}%</strong></span></p>
            </div>
            """

        # Problems section
        problems_section = ""
        if report.top_problems:
            rows = ""
            for p in report.top_problems[:10]:
                rows += f"<tr><td>{p['name']}</td><td>{p['count']}</td></tr>\n"
            problems_section = f"""
            <div class="section">
                <h2>Топ проблем</h2>
                <table class="problems-table">
                    <thead><tr><th>Проблема</th><th>Количество</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            """

        # Critical reviews section
        critical_section = ""
        if report.critical_reviews:
            count = len(report.critical_reviews)
            critical_section = f"""
            <div class="section">
                <h2>Критические отзывы</h2>
                <p>За неделю получено <strong>{count}</strong> критических отзывов, требующих немедленного внимания.</p>
            </div>
            """

        # Recommendations section
        recommendations_section = ""
        if report.recommendations:
            recs_html = ""
            for i, rec in enumerate(report.recommendations, 1):
                recs_html += f'<div class="recommendation"><strong>{i}.</strong> {rec}</div>\n'
            recommendations_section = f"""
            <div class="section">
                <h2>AI Рекомендации</h2>
                {recs_html}
            </div>
            """

        html_content = PDF_HTML_TEMPLATE.format(
            week_start=report.week_start.strftime("%d.%m.%Y"),
            week_end=report.week_end.strftime("%d.%m.%Y"),
            total_reviews=total,
            positive=sentiment.get("positive", 0),
            negative=sentiment.get("negative", 0),
            critical=len(report.critical_reviews or []),
            change_section=change_section,
            problems_section=problems_section,
            critical_section=critical_section,
            recommendations_section=recommendations_section,
            year=datetime.now().year,
        )

        # Generate PDF
        pdf_dir = os.path.join(tempfile.gettempdir(), "email_agent_reports")
        os.makedirs(pdf_dir, exist_ok=True)

        filename = f"report_{report.user_id}_{report.week_start}.pdf"
        pdf_path = os.path.join(pdf_dir, filename)

        HTML(string=html_content).write_pdf(pdf_path)

        # Update report with PDF path
        report.pdf_url = pdf_path
        await self.db.commit()

        logger.info(f"Generated PDF for report {report.id}: {pdf_path}")
        return pdf_path

    async def send_report(self, user: User, report: WeeklyReport) -> bool:
        """Send weekly report email to user."""
        from app.services.notifications.email import get_email_channel
        from sendgrid.helpers.mail import Attachment, FileContent, FileName, FileType, Disposition
        import base64

        email_channel = get_email_channel()
        if not email_channel.is_configured():
            logger.warning("Email channel not configured, cannot send report")
            return False

        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Content, To

            sentiment = report.sentiment_breakdown or {}
            total = report.total_reviews or 0
            positive = sentiment.get("positive", 0)
            negative = sentiment.get("negative", 0)

            recs_html = ""
            if report.recommendations:
                recs_list = "".join(f"<li>{r}</li>" for r in report.recommendations)
                recs_html = f"<h3>AI Рекомендации:</h3><ul>{recs_list}</ul>"

            html = f"""
            <html><body style="font-family: sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
                <div style="background: #0d6efd; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                    <h1 style="margin: 0;">Еженедельный отчёт</h1>
                    <p style="margin: 8px 0 0;">{report.week_start.strftime('%d.%m.%Y')} — {report.week_end.strftime('%d.%m.%Y')}</p>
                </div>
                <div style="padding: 20px; background: #f8f9fa; border-radius: 0 0 8px 8px;">
                    <div style="display: flex; gap: 12px; margin-bottom: 20px;">
                        <div style="flex:1; text-align:center; background:white; padding:12px; border-radius:8px;">
                            <div style="font-size:24px; font-weight:bold;">{total}</div>
                            <div style="font-size:12px; color:#666;">Всего</div>
                        </div>
                        <div style="flex:1; text-align:center; background:white; padding:12px; border-radius:8px;">
                            <div style="font-size:24px; font-weight:bold; color:#28a745;">{positive}</div>
                            <div style="font-size:12px; color:#666;">Позитивных</div>
                        </div>
                        <div style="flex:1; text-align:center; background:white; padding:12px; border-radius:8px;">
                            <div style="font-size:24px; font-weight:bold; color:#dc3545;">{negative}</div>
                            <div style="font-size:12px; color:#666;">Негативных</div>
                        </div>
                    </div>
                    {recs_html}
                    <div style="text-align: center; margin-top: 20px;">
                        <a href="{settings.dashboard_url}/analytics"
                           style="display:inline-block; background:#0d6efd; color:white; padding:12px 24px;
                                  text-decoration:none; border-radius:4px;">
                            Открыть аналитику
                        </a>
                    </div>
                </div>
                <div style="text-align:center; color:#999; font-size:11px; padding:16px;">
                    Email Agent — автоматический еженедельный отчёт
                </div>
            </body></html>
            """

            client = SendGridAPIClient(settings.sendgrid_api_key)
            message = Mail(
                from_email=settings.notification_from_email,
                to_emails=To(user.email),
                subject=f"Еженедельный отчёт: {report.week_start.strftime('%d.%m')} — {report.week_end.strftime('%d.%m.%Y')}",
            )
            message.add_content(Content("text/html", html))

            # Attach PDF if available
            if report.pdf_url and os.path.exists(report.pdf_url):
                with open(report.pdf_url, "rb") as f:
                    pdf_data = base64.b64encode(f.read()).decode()
                attachment = Attachment(
                    FileContent(pdf_data),
                    FileName(f"report_{report.week_start}.pdf"),
                    FileType("application/pdf"),
                    Disposition("attachment"),
                )
                message.attachment = attachment

            response = client.send(message)

            if response.status_code in (200, 201, 202):
                report.sent_at = datetime.utcnow()
                await self.db.commit()
                logger.info(f"Sent weekly report to {user.email}")
                return True
            else:
                logger.error(f"Failed to send report: status {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending weekly report to {user.email}: {e}")
            return False
