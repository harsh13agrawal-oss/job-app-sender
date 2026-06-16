"""Keyword-based classifier for inbound reply emails.

Lightweight — no LLM needed. Pattern: rank candidate categories by how many
strong/weak signals match in (subject + snippet), tie-broken by priority.
Returns ("Category", confidence_int) where higher confidence = more signals.
"""

from __future__ import annotations

import re

# Order matters: earlier categories win on ties.
CATEGORIES_ORDERED = [
    "Auto-reply",       # vacation / OOO — catch first so it doesn't get tagged Rejection
    "Interview",        # most actionable
    "Info request",     # next most actionable
    "Rejection",
    "Forwarded",        # "I've forwarded to X" — useful signal
    "Other",
]

# Each tuple: (regex pattern, weight). Compiled lazily.
_RAW_RULES: dict[str, list[tuple[str, int]]] = {
    "Auto-reply": [
        (r"\bout of (the )?office\b", 5),
        (r"\bauto[- ]?reply\b", 5),
        (r"\bautomatic reply\b", 5),
        (r"\bvacation\b", 4),
        (r"\bon leave\b", 4),
        (r"\baway from (the )?office\b", 4),
        (r"\blimited access\b", 3),
        (r"\bwill (be )?back\b", 2),
        (r"\bdo not reply\b|\bno[- ]?reply\b", 3),
    ],
    "Interview": [
        (r"\b(call|chat|conversation|meeting|interview)\b", 2),
        (r"\bwould you (be )?available\b", 4),
        (r"\bcalendly|\bschedule (a|the)? (call|meeting|chat|interview)\b", 5),
        (r"\bcalendar invite\b", 5),
        (r"\bdoes (the )?(\d+(?:st|nd|rd|th)? |[a-z]+(day)?,? )?(\d{1,2}(?::\d{2})?\s*(am|pm)|\d{1,2}\s*o[' ]?clock)\b", 4),
        (r"\bfree (to )?(chat|talk|connect|catch up)\b", 4),
        (r"\bnext steps?\b", 3),
        (r"\bnext round\b", 5),
        (r"\bset up a (call|meeting|chat|time)\b", 5),
        (r"\bsend across (your )?cv|resume\b", 2),
        (r"\bhappy to (chat|connect|discuss|talk)\b", 4),
        (r"\bzoom|google meet|teams|gmeet\b", 3),
        (r"\b(tomorrow|today)\b", 2),
        (r"\b(monday|tuesday|wednesday|thursday|friday)\b", 2),
        (r"\bwhat time(s)? work\b", 5),
    ],
    "Info request": [
        (r"\b(share|send|provide) (your |the )?(cv|resume|portfolio|samples?|references?|transcripts?)\b", 4),
        (r"\bcould you (share|send|tell|let me know|elaborate|explain)\b", 3),
        (r"\bmore (detail|context|information|info)\b", 3),
        (r"\b(notice|joining) period\b", 4),
        (r"\bcurrent (CTC|salary|package)\b", 4),
        (r"\bexpected (CTC|salary|package)\b", 4),
        (r"\bwhich (location|city|office)\b", 3),
        (r"\b(tell|let me know) (a bit |more )?about (yourself|your background)\b", 4),
        (r"\bwhat (drew|interests|attracts) you\b", 4),
        (r"\bquick question\b", 3),
    ],
    "Rejection": [
        (r"\bunfortunately\b", 4),
        (r"\bnot (a )?(good )?(right )?fit\b", 5),
        (r"\bwe (have )?decided to (move|go) (forward |ahead )?with (other|another)\b", 5),
        (r"\bwe[' ]?ll (not|won[' ]?t) be (moving|proceeding|going)\b", 5),
        (r"\bnot (proceeding|moving forward)\b", 5),
        (r"\bunable to (proceed|move forward|consider)\b", 5),
        (r"\bother (candidates?|applicants?) (whose|that)\b", 4),
        (r"\bbest of luck\b", 3),
        (r"\bwish you (all the )?best\b", 3),
        (r"\bkeep your (cv|resume|profile) on file\b", 4),
        (r"\bno (current )?openings?\b", 4),
        (r"\bdoes not match\b", 4),
        (r"\bwe regret\b", 5),
    ],
    "Forwarded": [
        (r"\bforwarded (your |the )?(cv|resume|email|application|note|details?)\b", 5),
        (r"\b(passing|shared) (this |your )(on|along)\b", 4),
        (r"\blooped in\b", 4),
        (r"\b(cc[' ]?d|cc[' ]?ing|cc-ing)\b", 3),
        (r"\b(reaching out|connecting you) with\b", 3),
        (r"\bplease (reach out|connect) (with|to)\b", 4),
    ],
}

_COMPILED: dict[str, list[tuple[re.Pattern, int]]] | None = None


def _compile_rules() -> dict[str, list[tuple[re.Pattern, int]]]:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = {
            cat: [(re.compile(p, re.IGNORECASE), w) for p, w in rules]
            for cat, rules in _RAW_RULES.items()
        }
    return _COMPILED


def classify(subject: str, snippet: str) -> tuple[str, int]:
    """Return (category, total_signal_weight).

    Higher weight = stronger evidence. If no signals match, returns ("Other", 0).
    """
    text = f"{subject or ''}\n{snippet or ''}"
    if not text.strip():
        return ("Other", 0)

    scores: dict[str, int] = {cat: 0 for cat in CATEGORIES_ORDERED if cat != "Other"}
    for cat, rules in _compile_rules().items():
        for pat, weight in rules:
            if pat.search(text):
                scores[cat] += weight

    best_cat: str | None = None
    best_score = 0
    for cat in CATEGORIES_ORDERED:
        if cat == "Other":
            continue
        s = scores.get(cat, 0)
        if s > best_score:
            best_score = s
            best_cat = cat

    if not best_cat or best_score < 3:
        return ("Other", best_score)
    return (best_cat, best_score)
