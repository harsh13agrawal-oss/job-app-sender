"""Thin wrapper around the Anthropic SDK for drafting/polishing email bodies.

Used by the Quick Send tab. The user supplies (a) their Anthropic API key
and (b) a system prompt copied from their Claude.ai Project's "Custom
instructions". We can't reach the Project directly, but the system prompt
plus the same model reproduces most of the Project's behaviour.
"""

from __future__ import annotations

import re
from typing import Optional

try:
    from anthropic import Anthropic
    HAVE_ANTHROPIC = True
except ImportError:
    Anthropic = None  # type: ignore
    HAVE_ANTHROPIC = False


DEFAULT_MODEL = "claude-opus-4-8"
MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

OUTPUT_GUIDANCE = (
    "\n\nFormat your response as clean HTML using only <p>, <strong>, <em>, "
    "<u>, <br>, <ul>, <ol>, <li>, and <a href=\"...\"> tags. Do NOT use "
    "markdown. Do NOT wrap in <html>, <body>, or <head>. Preserve any "
    "placeholders like {name}, {company}, {role}, {custom1}, {custom2} "
    "exactly as written. Return ONLY the email body — no greeting/preamble "
    "from you, no explanation."
)


def _ensure_html(text: str) -> str:
    """If the model returned plain text, wrap it in <p> tags."""
    if not text:
        return ""
    if re.search(r"<(p|br|strong|em|u|ul|ol|li|a)\b", text, re.IGNORECASE):
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def call_claude(
    api_key: str,
    system_prompt: str,
    user_message: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2000,
) -> tuple[bool, str]:
    """Returns (ok, html_or_error)."""
    if not HAVE_ANTHROPIC:
        return False, "Anthropic SDK not installed."
    if not api_key:
        return False, "No Anthropic API key set."

    full_system = (system_prompt or "") + OUTPUT_GUIDANCE

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=max_tokens,
            system=full_system,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        return False, f"Anthropic API error: {e}"

    text_parts = []
    for block in (resp.content or []):
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", ""))
    text = "".join(text_parts).strip()
    if not text:
        return False, "Claude returned an empty response."

    return True, _ensure_html(text)


def draft_from_context(
    api_key: str,
    system_prompt: str,
    context: str,
    model: str = DEFAULT_MODEL,
) -> tuple[bool, str]:
    user_msg = (
        "Draft a new job-application email body using the context below. "
        "Address the recipient as {name} and reference {company} and {role} "
        "(use those placeholders verbatim). If a firm-specific hook is "
        "obvious from the context, put it where {custom1} normally goes, "
        "but keep {custom1} as a fallback placeholder.\n\n"
        f"CONTEXT:\n{context}"
    )
    return call_claude(api_key, system_prompt, user_msg, model=model)


def polish_existing(
    api_key: str,
    system_prompt: str,
    current_html: str,
    instructions: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> tuple[bool, str]:
    extra = f"\n\nAdditional instructions: {instructions}" if instructions else ""
    user_msg = (
        "Refine the email body below. Preserve any {placeholders} exactly. "
        "Keep the same general meaning unless a clear improvement is "
        "warranted. Tighten language; remove anything stilted." + extra
        + "\n\nCURRENT DRAFT:\n" + (current_html or "")
    )
    return call_claude(api_key, system_prompt, user_msg, model=model)
