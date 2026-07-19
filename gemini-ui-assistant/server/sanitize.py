"""Context sanitization.

Even though the Pydantic models already act as an allowlist, this module adds
a second layer that strips anything resembling secrets or personal data from
the text fields before the context is serialized into the Gemini prompt.
"""

import re

from .schemas import UIContext

# Long unbroken token-like strings (API keys, JWTs, session tokens).
_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-\.]{24,}\b")
# Bearer/authorization fragments.
_AUTH_RE = re.compile(r"(?i)\b(bearer|authorization|api[_-]?key|token)\b\s*[:=]?\s*\S*")
# Email addresses.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

REDACTED = "[removed]"
ANON_PARTICIPANT = "the participant"


def scrub_text(text: str) -> str:
    """Remove token-like strings, auth fragments, and emails from free text."""
    if not text:
        return ""
    text = _AUTH_RE.sub(REDACTED, text)
    text = _TOKEN_RE.sub(REDACTED, text)
    text = _EMAIL_RE.sub(REDACTED, text)
    return text.strip()


def anonymize_participant(text: str, usernames: set[str]) -> str:
    """Replace known participant usernames with an anonymous label."""
    for name in usernames:
        if not name:
            continue
        text = re.sub(re.escape(name), ANON_PARTICIPANT, text, flags=re.IGNORECASE)
    return text


def sanitize_context(ctx: UIContext, usernames: set[str] | None = None) -> UIContext:
    """Return a copy of the context with all text fields scrubbed."""
    usernames = usernames or set()

    def clean(text: str) -> str:
        return anonymize_participant(scrub_text(text), usernames)

    return UIContext(
        page=clean(ctx.page),
        page_title=clean(ctx.page_title),
        visible_sections=[
            s.model_copy(
                update={
                    "id": clean(s.id),
                    "label": clean(s.label),
                    "description": clean(s.description),
                }
            )
            for s in ctx.visible_sections
        ],
        visible_metrics=[
            m.model_copy(
                update={
                    "label": clean(m.label),
                    "value": clean(m.value),
                    "help_text": clean(m.help_text),
                }
            )
            for m in ctx.visible_metrics
        ],
        available_actions=[
            a.model_copy(update={"label": clean(a.label), "description": clean(a.description)})
            for a in ctx.available_actions
        ],
    )


def context_to_prompt_block(ctx: UIContext) -> str:
    """Serialize the sanitized context into a readable prompt block."""
    lines: list[str] = []
    lines.append(f"Page: {ctx.page or 'unknown'}")
    if ctx.page_title:
        lines.append(f"Page title: {ctx.page_title}")

    if ctx.visible_sections:
        lines.append("Visible sections:")
        for s in ctx.visible_sections:
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"- {s.label or s.id}{desc}")

    if ctx.visible_metrics:
        lines.append("Visible measurements:")
        for m in ctx.visible_metrics:
            value = f": {m.value}" if m.value else ""
            help_text = f" ({m.help_text})" if m.help_text else ""
            lines.append(f"- {m.label}{value}{help_text}")

    if ctx.available_actions:
        lines.append("Available actions (buttons/controls):")
        for a in ctx.available_actions:
            desc = f" — {a.description}" if a.description else ""
            lines.append(f"- {a.label}{desc}")

    return "\n".join(lines)
