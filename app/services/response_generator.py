"""
Response Generator service using Mistral AI.

Generates draft responses to customer reviews with:
- Tone customization (formal, friendly, professional)
- Personalization with customer name
- Problem acknowledgment
- Template-based fallbacks
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mistralai import ChatMistralAI

from app.config import get_settings
from app.models.company_settings import CompanySettings
from app.models.review import Review
from app.schemas.response import DraftResponseCreate

logger = logging.getLogger(__name__)
settings = get_settings()


# Tone descriptions for prompt construction
TONE_DESCRIPTIONS = {
    "formal": "Официальный, деловой стиль. Обращение на Вы.",
    "friendly": "Дружелюбный, тёплый стиль. Можно на ты, если уместно.",
    "professional": "Профессиональный, но не сухой. Обращение на Вы.",
}


# Base templates for typical situations
TEMPLATES = {
    "delivery_issue": """Здравствуйте{name_greeting}!

Благодарим за обратную связь. Приносим извинения за задержку доставки.
Мы уже связались с логистической службой для выяснения причин.
{custom_text}

С уважением, {company_name}""",

    "quality_issue": """Здравствуйте{name_greeting}!

Благодарим за обратную связь и сожалеем, что качество товара не оправдало Ваших ожиданий.
Мы относимся к качеству очень серьёзно и хотели бы разобраться в ситуации.
{custom_text}

С уважением, {company_name}""",

    "positive_feedback": """Здравствуйте{name_greeting}!

Большое спасибо за Ваш тёплый отзыв! Мы очень рады, что Вам понравилось.
Ваши слова вдохновляют нас становиться ещё лучше.
{custom_text}

С уважением, {company_name}""",

    "general_inquiry": """Здравствуйте{name_greeting}!

Благодарим Вас за обращение. Мы ценим Вашу обратную связь.
{custom_text}

С уважением, {company_name}""",
}


# System prompt for response generation
SYSTEM_PROMPT = """Ты - опытный специалист по работе с клиентами.
Твоя задача - написать ответ на отзыв клиента от лица компании.
Ответ должен быть вежливым, эмпатичным и конструктивным.
Всегда отвечай в запрошенном формате JSON."""


# Main generation prompt
GENERATION_PROMPT = """Ты - представитель компании "{company_name}".
Напиши ответ на отзыв клиента.

Тон ответа: {tone_description}

Отзыв клиента:
{review_text}

Анализ отзыва:
- Тональность: {sentiment}
- Проблемы: {problems}
- Имя клиента: {customer_name}

Требования к ответу:
1. Поблагодарить за обратную связь
2. Признать проблему (если есть)
3. Предложить решение или извиниться
4. Закончить позитивно
5. Длина: 3-5 предложений

Ответь в формате JSON:
{{"response": "текст ответа"}}"""


# Variant generation prompt
VARIANT_PROMPT = """Напиши ещё один вариант ответа на тот же отзыв.
Ответ должен отличаться формулировками, но сохранять тот же смысл и тон.

Предыдущий вариант:
{previous_response}

Требования:
- Другие формулировки
- Тот же тон: {tone_description}
- Длина: 3-5 предложений

Ответь в формате JSON:
{{"response": "текст ответа"}}"""


class ResponseGenerator:
    """
    AI-powered response generator for customer reviews.

    Uses Mistral AI to generate personalized response drafts
    based on review analysis and company tone settings.
    """

    def __init__(self):
        """Initialize the response generator with Mistral AI."""
        if not settings.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY is not configured")

        self.llm = ChatMistralAI(
            api_key=settings.mistral_api_key,
            model=settings.ai_model,
            max_tokens=settings.ai_max_tokens,
            temperature=0.7,  # Higher temperature for more creative responses
        )

    def _call_llm(self, prompt: str) -> str:
        """
        Call the LLM with a prompt.

        Args:
            prompt: The prompt to send

        Returns:
            LLM response text
        """
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = self.llm.invoke(messages)
        return response.content

    def _parse_json_response(self, response: str, default: str = "") -> str:
        """
        Parse JSON from LLM response and extract the response text.

        Args:
            response: LLM response text
            default: Default value if parsing fails

        Returns:
            Extracted response text or default
        """
        try:
            # Try to extract JSON from response
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result.get("response", default)
            # Try parsing the whole response as JSON
            result = json.loads(response)
            return result.get("response", default)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            # Return raw response if JSON parsing fails
            return response.strip() if response else default

    def _get_template_response(
        self,
        template_key: str,
        customer_name: Optional[str],
        company_name: str,
        custom_text: str = "",
    ) -> str:
        """
        Generate a response using a template.

        Args:
            template_key: Key of the template to use
            customer_name: Customer name for personalization
            company_name: Company name
            custom_text: Additional custom text

        Returns:
            Formatted template response
        """
        template = TEMPLATES.get(template_key, TEMPLATES["general_inquiry"])

        name_greeting = f", {customer_name}" if customer_name else ""

        return template.format(
            name_greeting=name_greeting,
            company_name=company_name or "Наша команда",
            custom_text=custom_text,
        )

    def _detect_issue_type(self, problems: List[str], sentiment: str) -> str:
        """
        Detect the type of issue from problems list.

        Args:
            problems: List of identified problems
            sentiment: Sentiment of the review

        Returns:
            Template key for the issue type
        """
        if not problems and sentiment == "positive":
            return "positive_feedback"

        problems_lower = " ".join(problems).lower() if problems else ""

        if any(word in problems_lower for word in ["доставк", "курьер", "задержк", "опоздан"]):
            return "delivery_issue"

        if any(word in problems_lower for word in ["качеств", "брак", "дефект", "сломан", "не работа"]):
            return "quality_issue"

        if sentiment == "positive":
            return "positive_feedback"

        return "general_inquiry"

    async def generate_responses(
        self,
        review: Review,
        review_text: str,
        settings: CompanySettings,
        num_variants: int = 1,
    ) -> List[DraftResponseCreate]:
        """
        Generate response drafts for a review.

        Args:
            review: Review model instance
            review_text: Text of the review
            settings: Company settings with tone preferences
            num_variants: Number of variants to generate (1 for STARTER, 3 for PRO+)

        Returns:
            List of DraftResponseCreate objects
        """
        logger.info(f"Generating {num_variants} response variants for review {review.id}")

        # Prepare context
        company_name = settings.company_name or "Наша команда"
        tone = settings.response_tone or "professional"
        tone_description = TONE_DESCRIPTIONS.get(tone, TONE_DESCRIPTIONS["professional"])

        # Extract customer name from analysis or sender
        customer_name = "не указано"
        if review.sender_name:
            customer_name = review.sender_name

        # Format problems
        problems_text = ", ".join(review.problems) if review.problems else "не указаны"

        # Get sentiment
        sentiment = review.sentiment or "neutral"

        drafts: List[DraftResponseCreate] = []
        previous_responses: List[str] = []

        for variant_num in range(1, num_variants + 1):
            try:
                if variant_num == 1:
                    # Generate first variant
                    prompt = GENERATION_PROMPT.format(
                        company_name=company_name,
                        tone_description=tone_description,
                        review_text=review_text[:2000],  # Limit length
                        sentiment=sentiment,
                        problems=problems_text,
                        customer_name=customer_name,
                    )
                else:
                    # Generate alternative variant
                    prompt = VARIANT_PROMPT.format(
                        previous_response=previous_responses[-1][:500],
                        tone_description=tone_description,
                    )

                response_text = self._call_llm(prompt)
                parsed_response = self._parse_json_response(response_text)

                if not parsed_response:
                    # Fallback to template
                    issue_type = self._detect_issue_type(
                        review.problems or [],
                        sentiment,
                    )
                    parsed_response = self._get_template_response(
                        issue_type,
                        review.sender_name,
                        company_name,
                    )

                previous_responses.append(parsed_response)

                draft = DraftResponseCreate(
                    content=parsed_response,
                    tone=tone,
                    variant_number=variant_num,
                )
                drafts.append(draft)

                logger.info(f"Generated variant {variant_num} for review {review.id}")

            except Exception as e:
                logger.error(f"Error generating variant {variant_num}: {e}")

                # Fallback to template on error
                issue_type = self._detect_issue_type(
                    review.problems or [],
                    sentiment,
                )
                fallback_response = self._get_template_response(
                    issue_type,
                    review.sender_name,
                    company_name,
                )

                draft = DraftResponseCreate(
                    content=fallback_response,
                    tone=tone,
                    variant_number=variant_num,
                )
                drafts.append(draft)

        return drafts

    def generate_from_template(
        self,
        template_key: str,
        customer_name: Optional[str],
        company_name: str,
        tone: str = "professional",
        custom_text: str = "",
    ) -> DraftResponseCreate:
        """
        Generate a response directly from a template.

        Args:
            template_key: Template to use
            customer_name: Customer name for personalization
            company_name: Company name
            tone: Response tone
            custom_text: Additional text to include

        Returns:
            DraftResponseCreate with template response
        """
        response = self._get_template_response(
            template_key,
            customer_name,
            company_name,
            custom_text,
        )

        return DraftResponseCreate(
            content=response,
            tone=tone,
            variant_number=1,
        )


# Singleton instance
_generator_instance: Optional[ResponseGenerator] = None


def get_response_generator() -> ResponseGenerator:
    """Get or create ResponseGenerator singleton."""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = ResponseGenerator()
    return _generator_instance
