"""Template storage and placeholder rendering.

Templates are JSON on disk. Each template has a `subject` and `body_html`.
Placeholders are `{name}`, `{company}`, `{role}`, `{sector}`, `{custom1}`,
`{custom2}`. Missing placeholders are intentionally left as `{key}` in the
output so the user spots them in preview rather than mailing a blank.
"""

from __future__ import annotations

import json
import os
from typing import Any


DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "Finance / PE / IB": {
        "subject": "Application: {role} – CA Harsh Agarwal",
        "body_html": (
            "<p>Dear {name},</p>"
            "<p>I am writing to express my interest in the <strong>{role}</strong> opportunity at "
            "<strong>{company}</strong>. As a Chartered Accountant with hands-on experience in "
            "valuation, financial modelling, and transaction support, I was drawn to {company}'s "
            "approach to active ownership and the calibre of the platforms in your portfolio "
            "across the {sector} space.</p>"
            "<p>{custom1}</p>"
            "<p>In my recent work I have built three-statement and LBO models, run sensitivity and "
            "returns analyses, and partnered with management teams on diligence and post-deal "
            "value creation. I would welcome the opportunity to bring that toolkit to {company}, "
            "and I have attached my CV and cover letter for your review.</p>"
            "<p>I would be grateful for the chance to discuss how I could contribute. {custom2}</p>"
            "<p>Warm regards,<br>"
            "<strong>CA Harsh Agarwal</strong></p>"
        ),
    },
    "Consulting": {
        "subject": "Application: {role} – CA Harsh Agarwal",
        "body_html": (
            "<p>Dear {name},</p>"
            "<p>I am writing to apply for the <strong>{role}</strong> role at "
            "<strong>{company}</strong>. {company}'s reputation for structured, hypothesis-led "
            "problem solving in the {sector} sector is what drew me in, and I believe my "
            "background as a Chartered Accountant complements that approach well.</p>"
            "<p>{custom1}</p>"
            "<p>I have led engagements that move from issue tree to recommendation under tight "
            "timelines — financial diagnostics, cost benchmarking, and operating-model reviews — "
            "translating analysis into decisions that clients can act on. I have attached my CV "
            "and cover letter, both tailored to the consulting profile.</p>"
            "<p>I would welcome a conversation about how my profile maps to your team's needs. "
            "{custom2}</p>"
            "<p>Warm regards,<br>"
            "<strong>CA Harsh Agarwal</strong></p>"
        ),
    },
    "Tech / Corporate Finance": {
        "subject": "Application: {role} – CA Harsh Agarwal",
        "body_html": (
            "<p>Hi {name},</p>"
            "<p>I'd like to put my name forward for the <strong>{role}</strong> opening at "
            "<strong>{company}</strong>. The thing that pulled me toward {company} is the chance "
            "to help scale a finance function alongside the product — closing the books cleanly "
            "while the underlying business is still moving fast.</p>"
            "<p>{custom1}</p>"
            "<p>As a CA, I have set up reporting cadences, built FP&amp;A models from scratch, "
            "automated close workflows, and worked closely with founders and ops on unit "
            "economics. I have attached my CV and cover letter (both tailored to a tech / corp-fin "
            "context) for your review.</p>"
            "<p>Happy to jump on a quick call whenever suits you. {custom2}</p>"
            "<p>Best,<br>"
            "<strong>CA Harsh Agarwal</strong></p>"
        ),
    },
    "General / Other": {
        "subject": "Application: {role} – CA Harsh Agarwal",
        "body_html": (
            "<p>Dear {name},</p>"
            "<p>I am writing to express my interest in the <strong>{role}</strong> position at "
            "<strong>{company}</strong>. {custom1}</p>"
            "<p>As a Chartered Accountant, I bring a foundation in financial reporting, audit, "
            "tax, and analysis, paired with experience working across {sector}-adjacent mandates. "
            "I have attached my CV and a cover letter for your review.</p>"
            "<p>I would value the opportunity to discuss how I could contribute to {company}. "
            "{custom2}</p>"
            "<p>Warm regards,<br>"
            "<strong>CA Harsh Agarwal</strong></p>"
        ),
    },
}


def load_templates(path: str) -> dict[str, dict[str, str]]:
    if not os.path.exists(path):
        save_templates(DEFAULT_TEMPLATES, path)
        return {k: dict(v) for k, v in DEFAULT_TEMPLATES.items()}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not data:
            raise ValueError("Empty or invalid templates file.")
        cleaned: dict[str, dict[str, str]] = {}
        for name, tmpl in data.items():
            if not isinstance(tmpl, dict):
                continue
            cleaned[name] = {
                "subject": str(tmpl.get("subject", "")),
                "body_html": str(tmpl.get("body_html", "")),
            }
        if not cleaned:
            raise ValueError("No usable templates after cleaning.")
        return cleaned
    except (json.JSONDecodeError, OSError, ValueError):
        save_templates(DEFAULT_TEMPLATES, path)
        return {k: dict(v) for k, v in DEFAULT_TEMPLATES.items()}


def save_templates(templates: dict[str, dict[str, str]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(templates, f, indent=2, ensure_ascii=False)


def render(template_text: str, context: dict[str, Any]) -> str:
    if not template_text:
        return ""
    out = template_text
    for key, val in (context or {}).items():
        out = out.replace("{" + str(key) + "}", "" if val is None else str(val))
    return out
