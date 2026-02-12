"""
AI Analysis service using LangChain + LangGraph + Mistral AI.

Provides intelligent analysis of customer reviews with:
- Sentiment classification
- Problem extraction
- Suggestion extraction
- Priority determination
- Summary generation
"""
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_mistralai import ChatMistralAI
from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.schemas.analysis import AnalysisState, ReviewAnalysis

logger = logging.getLogger(__name__)
settings = get_settings()


# Prompts in Russian
SYSTEM_PROMPT = """Ты - AI-ассистент для анализа отзывов клиентов.
Анализируй отзывы на русском языке, выделяя ключевую информацию.
Всегда отвечай в запрошенном формате JSON."""

SENTIMENT_PROMPT = """Определи тональность отзыва клиента:
- positive: клиент доволен, благодарит, хвалит
- negative: жалоба, недовольство, претензия
- neutral: информационный запрос, нейтральное сообщение

Тема письма: {subject}

Текст отзыва:
{text}

Ответь в формате JSON:
{{"sentiment": "positive" | "negative" | "neutral"}}"""

PROBLEMS_PROMPT = """Выдели конкретные проблемы, о которых упоминает клиент.
Категории: доставка, качество товара, обслуживание, цена, упаковка, возврат, коммуникация, другое.

Тема письма: {subject}

Текст отзыва:
{text}

Ответь в формате JSON:
{{"problems": ["проблема 1", "проблема 2", ...]}}

Если проблем нет, верни пустой список."""

SUGGESTIONS_PROMPT = """Выдели предложения и пожелания клиента из отзыва.
Это могут быть: улучшения, новые функции, изменения в сервисе.

Тема письма: {subject}

Текст отзыва:
{text}

Ответь в формате JSON:
{{"suggestions": ["предложение 1", "предложение 2", ...]}}

Если предложений нет, верни пустой список."""

SUMMARY_PROMPT = """Создай краткое содержание отзыва (2-3 предложения).
Укажи основную суть обращения клиента.

Тема письма: {subject}

Текст отзыва:
{text}

Ответь в формате JSON:
{{"summary": "краткое содержание"}}"""

PRIORITY_PROMPT = """Определи приоритет обработки отзыва:
- critical: срочные проблемы, угроза потери клиента, юридические вопросы, массовая проблема
- important: значительные жалобы, требующие внимания, негативные отзывы
- normal: обычные запросы, положительные отзывы, информационные сообщения

Тональность: {sentiment}
Проблемы: {problems}

Тема письма: {subject}

Текст отзыва:
{text}

Ответь в формате JSON:
{{"priority": "critical" | "important" | "normal"}}"""

EXTRACT_NAME_PROMPT = """Извлеки имя клиента из текста отзыва, если оно указано.
Ищи подписи, приветствия, упоминания имени.

Текст отзыва:
{text}

Ответь в формате JSON:
{{"customer_name": "имя" или null}}"""

REQUIRES_RESPONSE_PROMPT = """Определи, требует ли отзыв ответа от компании:
- true: вопрос, жалоба, просьба, негативный отзыв, запрос информации
- false: благодарность без вопросов, информационное сообщение без запроса

Тональность: {sentiment}
Приоритет: {priority}

Текст отзыва:
{text}

Ответь в формате JSON:
{{"requires_response": true | false}}"""


class ReviewAnalyzer:
    """
    AI-powered review analyzer using LangGraph workflow.

    Workflow:
    1. preprocess -> Clean and normalize text
    2. classify_sentiment -> Determine sentiment
    3. extract_problems -> Extract problems
    4. extract_suggestions -> Extract suggestions
    5. summarize -> Create summary
    6. prioritize -> Determine priority
    7. extract_name -> Extract customer name
    8. decide_response -> Decide if response needed
    9. aggregate -> Compile final result
    """

    def __init__(self):
        """Initialize the analyzer with Mistral AI."""
        if not settings.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY is not configured")

        self.llm = ChatMistralAI(
            api_key=settings.mistral_api_key,
            model=settings.ai_model,
            max_tokens=settings.ai_max_tokens,
            temperature=settings.ai_temperature,
        )
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(AnalysisState)

        # Add nodes
        workflow.add_node("preprocess", self._preprocess)
        workflow.add_node("classify_sentiment", self._classify_sentiment)
        workflow.add_node("extract_problems", self._extract_problems)
        workflow.add_node("extract_suggestions", self._extract_suggestions)
        workflow.add_node("summarize", self._summarize)
        workflow.add_node("prioritize", self._prioritize)
        workflow.add_node("extract_name", self._extract_name)
        workflow.add_node("decide_response", self._decide_response)

        # Define edges
        workflow.set_entry_point("preprocess")
        workflow.add_edge("preprocess", "classify_sentiment")
        workflow.add_edge("classify_sentiment", "extract_problems")
        workflow.add_edge("extract_problems", "extract_suggestions")
        workflow.add_edge("extract_suggestions", "summarize")
        workflow.add_edge("summarize", "prioritize")
        workflow.add_edge("prioritize", "extract_name")
        workflow.add_edge("extract_name", "decide_response")
        workflow.add_edge("decide_response", END)

        return workflow.compile()

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

    def _parse_json_response(self, response: str, default: Any = None) -> Any:
        """
        Parse JSON from LLM response.

        Args:
            response: LLM response text
            default: Default value if parsing fails

        Returns:
            Parsed JSON or default
        """
        try:
            # Try to extract JSON from response
            # Handle cases where LLM wraps JSON in markdown code blocks
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return default

    def _preprocess(self, state: AnalysisState) -> Dict[str, Any]:
        """
        Preprocess and clean the review text.

        Removes excessive whitespace, normalizes encoding.
        """
        text = state.review_text

        # Clean whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Remove HTML tags if any
        text = re.sub(r"<[^>]+>", "", text)

        # Limit text length to prevent token overflow
        max_chars = 4000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        return {"cleaned_text": text}

    def _classify_sentiment(self, state: AnalysisState) -> Dict[str, Any]:
        """Classify the sentiment of the review."""
        try:
            prompt = SENTIMENT_PROMPT.format(
                subject=state.subject,
                text=state.cleaned_text,
            )
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"sentiment": "neutral"})
            sentiment = result.get("sentiment", "neutral")

            # Validate sentiment
            if sentiment not in ["positive", "negative", "neutral"]:
                sentiment = "neutral"

            return {"sentiment": sentiment}
        except Exception as e:
            logger.error(f"Error classifying sentiment: {e}")
            return {"sentiment": "neutral", "error": str(e)}

    def _extract_problems(self, state: AnalysisState) -> Dict[str, Any]:
        """Extract problems mentioned in the review."""
        try:
            prompt = PROBLEMS_PROMPT.format(
                subject=state.subject,
                text=state.cleaned_text,
            )
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"problems": []})
            problems = result.get("problems", [])

            # Ensure it's a list
            if not isinstance(problems, list):
                problems = []

            return {"problems": problems}
        except Exception as e:
            logger.error(f"Error extracting problems: {e}")
            return {"problems": []}

    def _extract_suggestions(self, state: AnalysisState) -> Dict[str, Any]:
        """Extract suggestions from the review."""
        try:
            prompt = SUGGESTIONS_PROMPT.format(
                subject=state.subject,
                text=state.cleaned_text,
            )
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"suggestions": []})
            suggestions = result.get("suggestions", [])

            # Ensure it's a list
            if not isinstance(suggestions, list):
                suggestions = []

            return {"suggestions": suggestions}
        except Exception as e:
            logger.error(f"Error extracting suggestions: {e}")
            return {"suggestions": []}

    def _summarize(self, state: AnalysisState) -> Dict[str, Any]:
        """Create a summary of the review."""
        try:
            prompt = SUMMARY_PROMPT.format(
                subject=state.subject,
                text=state.cleaned_text,
            )
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"summary": ""})
            summary = result.get("summary", "")

            # Fallback summary if empty
            if not summary:
                summary = state.cleaned_text[:200] + "..." if len(state.cleaned_text) > 200 else state.cleaned_text

            return {"summary": summary}
        except Exception as e:
            logger.error(f"Error creating summary: {e}")
            return {"summary": state.cleaned_text[:200] + "..." if len(state.cleaned_text) > 200 else state.cleaned_text}

    def _prioritize(self, state: AnalysisState) -> Dict[str, Any]:
        """Determine the priority of the review."""
        try:
            prompt = PRIORITY_PROMPT.format(
                sentiment=state.sentiment,
                problems=", ".join(state.problems) if state.problems else "нет",
                subject=state.subject,
                text=state.cleaned_text,
            )
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"priority": "normal"})
            priority = result.get("priority", "normal")

            # Validate priority
            if priority not in ["critical", "important", "normal"]:
                priority = "normal"

            # Auto-escalate negative reviews to at least important
            if state.sentiment == "negative" and priority == "normal":
                priority = "important"

            return {"priority": priority}
        except Exception as e:
            logger.error(f"Error determining priority: {e}")
            # Default: negative -> important, others -> normal
            priority = "important" if state.sentiment == "negative" else "normal"
            return {"priority": priority}

    def _extract_name(self, state: AnalysisState) -> Dict[str, Any]:
        """Extract customer name from the review."""
        try:
            prompt = EXTRACT_NAME_PROMPT.format(text=state.cleaned_text)
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"customer_name": None})
            name = result.get("customer_name")

            # Clean up name
            if name and isinstance(name, str):
                name = name.strip()
                if len(name) < 2 or len(name) > 100:
                    name = None

            return {"customer_name": name}
        except Exception as e:
            logger.error(f"Error extracting name: {e}")
            return {"customer_name": None}

    def _decide_response(self, state: AnalysisState) -> Dict[str, Any]:
        """Decide if the review requires a response."""
        try:
            prompt = REQUIRES_RESPONSE_PROMPT.format(
                sentiment=state.sentiment,
                priority=state.priority,
                text=state.cleaned_text,
            )
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"requires_response": True})
            requires_response = result.get("requires_response", True)

            # Ensure boolean
            if not isinstance(requires_response, bool):
                requires_response = True

            # Always respond to negative/critical
            if state.sentiment == "negative" or state.priority == "critical":
                requires_response = True

            return {"requires_response": requires_response}
        except Exception as e:
            logger.error(f"Error deciding response: {e}")
            # Default: always respond to negative
            return {"requires_response": state.sentiment == "negative"}

    def analyze(self, review_text: str, subject: str = "") -> ReviewAnalysis:
        """
        Analyze a review using the LangGraph workflow.

        Args:
            review_text: The text of the review to analyze
            subject: The subject/title of the review (e.g., email subject)

        Returns:
            ReviewAnalysis with complete analysis results
        """
        logger.info(f"Starting analysis for review: {subject[:50]}...")

        # Initialize state
        initial_state = AnalysisState(
            review_text=review_text,
            subject=subject,
        )

        # Run the graph
        final_state = self.graph.invoke(initial_state)

        # Convert to ReviewAnalysis
        result = ReviewAnalysis(
            sentiment=final_state.get("sentiment", "neutral"),
            priority=final_state.get("priority", "normal"),
            summary=final_state.get("summary", ""),
            problems=final_state.get("problems", []),
            suggestions=final_state.get("suggestions", []),
            customer_name=final_state.get("customer_name"),
            requires_response=final_state.get("requires_response", True),
        )

        logger.info(
            f"Analysis complete: sentiment={result.sentiment}, "
            f"priority={result.priority}, requires_response={result.requires_response}"
        )

        return result

    def analyze_basic(self, review_text: str, subject: str = "") -> ReviewAnalysis:
        """
        Basic analysis for FREE tier - only sentiment and priority.

        Args:
            review_text: The text of the review
            subject: The subject/title

        Returns:
            ReviewAnalysis with basic fields only
        """
        logger.info(f"Starting basic analysis for review: {subject[:50]}...")

        # Clean text
        text = re.sub(r"\s+", " ", review_text).strip()
        text = re.sub(r"<[^>]+>", "", text)
        if len(text) > 4000:
            text = text[:4000] + "..."

        # Classify sentiment
        try:
            prompt = SENTIMENT_PROMPT.format(subject=subject, text=text)
            response = self._call_llm(prompt)
            result = self._parse_json_response(response, {"sentiment": "neutral"})
            sentiment = result.get("sentiment", "neutral")
            if sentiment not in ["positive", "negative", "neutral"]:
                sentiment = "neutral"
        except Exception as e:
            logger.error(f"Error in basic sentiment: {e}")
            sentiment = "neutral"

        # Determine priority based on sentiment
        priority = "important" if sentiment == "negative" else "normal"

        # Basic summary (truncate text)
        summary = text[:200] + "..." if len(text) > 200 else text

        return ReviewAnalysis(
            sentiment=sentiment,
            priority=priority,
            summary=summary,
            problems=[],
            suggestions=[],
            customer_name=None,
            requires_response=sentiment == "negative",
        )


# Singleton instance
_analyzer_instance: Optional[ReviewAnalyzer] = None


def get_review_analyzer() -> ReviewAnalyzer:
    """Get or create ReviewAnalyzer singleton."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = ReviewAnalyzer()
    return _analyzer_instance
