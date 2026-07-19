"""Gemini client with timeout handling, plus a mock for keyless development."""

import asyncio
import logging

from .config import get_settings
from .schemas import UIContext
from .system_prompt import SYSTEM_INSTRUCTION

logger = logging.getLogger("gemini_ui_assistant")


class AssistantUpstreamError(Exception):
    """Raised when Gemini fails or times out; carries a user-friendly message."""


def _build_contents(question: str, context_block: str) -> str:
    return (
        "Here is the UI context for the screen the user is currently viewing:\n\n"
        f"{context_block}\n\n"
        f"The user's question: {question}"
    )


async def ask_gemini(question: str, context_block: str) -> str:
    settings = get_settings()
    # Imported lazily so mock mode works without the google-genai package.
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=_build_contents(question, context_block),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    max_output_tokens=settings.max_output_tokens,
                    temperature=0.3,
                    # gemini-2.5-flash thinking can consume the whole token
                    # budget and truncate/empty the answer; disable it for these
                    # short, on-screen-grounded replies.
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            ),
            timeout=settings.gemini_timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("Gemini request timed out after %.0fs", settings.gemini_timeout_s)
        raise AssistantUpstreamError(
            "The assistant took too long to answer. Please try again."
        ) from None
    except Exception:
        logger.exception("Gemini request failed")
        raise AssistantUpstreamError(
            "The assistant is not available right now. Please try again in a moment."
        ) from None

    text = (response.text or "").strip()
    if not text:
        raise AssistantUpstreamError(
            "The assistant could not produce an answer. Please try rephrasing your question."
        )
    return text


def ask_mock(question: str, ctx: UIContext) -> str:
    """Deterministic, context-aware canned answers for local development."""
    q = question.lower()

    has_context = bool(
        ctx.page_title or ctx.visible_sections or ctx.visible_metrics or ctx.available_actions
    )
    if not has_context:
        return (
            "I cannot determine the answer from the current screen. "
            "Try opening a session first, then ask me again."
        )

    if "what does this page show" in q or ("what" in q and "page" in q):
        parts = [f"This screen is the {ctx.page_title or 'Praxis dashboard'}."]
        if ctx.visible_sections:
            labels = ", ".join(s.label or s.id for s in ctx.visible_sections if s.label or s.id)
            parts.append(f"It contains these sections: {labels}.")
        parts.append("You can ask me about any section, measurement, or button you see.")
        return " ".join(parts)

    for metric in ctx.visible_metrics:
        if metric.label and metric.label.lower() in q:
            answer = f"{metric.label} describes performance on the tracing task."
            if metric.help_text:
                answer += f" {metric.help_text}"
            if metric.value:
                answer += f" Right now it shows {metric.value}."
            answer += " A therapist can help interpret what this means."
            return answer

    for action in ctx.available_actions:
        if action.label and action.label.lower() in q:
            desc = action.description or "performs that action"
            return (
                f'To do this, click the "{action.label}" button. It {desc[0].lower() + desc[1:]}'
                if action.description
                else f'To do this, click the "{action.label}" button.'
            )

    if ctx.visible_sections or ctx.visible_metrics or ctx.available_actions:
        return (
            "I cannot determine the exact answer from the current screen, but here is what "
            "is visible: "
            + "; ".join(
                [s.label for s in ctx.visible_sections if s.label]
                + [m.label for m in ctx.visible_metrics if m.label]
            )
            + ". You can ask me about any of these, or ask your therapist about what the "
            "measurements mean."
        )

    return (
        "I cannot determine the answer from the current screen. "
        "Try opening a session first, then ask me again."
    )
