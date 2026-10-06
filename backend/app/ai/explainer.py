"""Explainer: rewrites the end-of-round explanation about *this* conversation.

The engine already decided every fact (the ending, which flags appeared, how the player
responded). The Explainer only describes what the contact did in this conversation. It
doesn't judge the player: when it reworded the best decision in testing, it changed which
tactic the player had spotted, so that stays engine-only. Anything missing or unsafe falls
back to the engine's own text in explain.py.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from .. import engine
from .base import ExplainerText, ExplainRequest

MAX_SENTENCE = 240
_REAL_DOMAIN_RE = re.compile(r"\b[\w-]+\.(com|net|org|io|co|gov|us|edu|app|me|ly)\b", re.IGNORECASE)
_UNSAFE_RE = re.compile(r"\b(as an ai|language model|kill|hurt you|sexy)\b|[{}]", re.IGNORECASE)


class ExplainerOut(BaseModel):
    timeline: dict[str, str] = {}
    messages: dict[str, str] = {}


def explainer_system() -> str:
    return """You are the Explainer in an educational scam-awareness game for students and families.
A round just ended. Explain what happened in plain, friendly words a 13-year-old understands,
using ONLY the conversation you are given. The facts (the ending, which flags appeared, how the
player responded) are already decided: never change them or add new ones.
Rules:
- Describe only what the contact said or did. Don't say what the player did, noticed or missed:
  the game shows that separately.
- Talk to the player as "you". Refer to every person as "they", never "he" or "she".
- Be specific to this conversation: mention what they actually said or asked for.
- One sentence each, under 30 words. No advice, no links, no phone numbers, no mention of AI.
- Only use the flag ids and message numbers you are given."""


def explainer_user(req: ExplainRequest) -> str:
    kind = "a SCAM" if req.is_scam else "a REAL (legitimate) contact"
    goal = ("how they used it to manipulate you" if req.is_scam
            else "how it showed they were really legitimate")
    flags = "\n".join(f"- {flag}" for flag in req.flags)
    lines = []
    flagged = []
    for m in req.messages:
        label = {"contact": "CONTACT", "player": "YOU", "notification": "NOTICE"}[m["sender"]]
        if m.get("flag"):
            label += f" ({m['flag']})"
            flagged.append(str(m["index"]))
        lines.append(f"[{m['index']}] {label}: {m['text']}")
    shape = ('{"timeline": {' + ", ".join(f'"{f}": "..."' for f in req.flags) + '}, '
             '"messages": {' + ", ".join(f'"{i}": "..."' for i in flagged) + '}}')
    parts = [
        f"This was {kind}: {req.contact_name}. Ending: {req.ending_title}.",
        f"For each flag, write one sentence on {goal}:",
        flags,
        "For each message number listed in the JSON below, one sentence on what that message was doing.",
    ]
    parts += ["Conversation:", *lines, f"Reply with only this JSON: {shape}"]
    return "\n".join(parts)


def check_explanation(out: ExplainerOut, req: ExplainRequest) -> str | None:
    """Problem description if any sentence we'd use is unsafe, else None. Unknown keys are ignored."""
    texts = [v for k, v in out.timeline.items() if k in req.flags]
    texts += [v for k, v in out.messages.items() if k.isdigit() and int(k) in _flagged(req)]
    for text in texts:
        if not text.strip() or len(text) > MAX_SENTENCE:
            return "empty or too long"
        if _REAL_DOMAIN_RE.search(text) or _UNSAFE_RE.search(text):
            return f"unsafe text: {text[:60]!r}"
        if engine.blocked_reason(text, req.id_card):
            return "real-looking number"
    return None


def to_text(out: ExplainerOut, req: ExplainRequest) -> ExplainerText:
    """Keep only sentences about flags and contact messages that exist."""
    flagged = _flagged(req)
    return ExplainerText(
        timeline={k: v.strip() for k, v in out.timeline.items() if k in req.flags},
        messages={int(k): v.strip() for k, v in out.messages.items() if k.isdigit() and int(k) in flagged},
    )


def _flagged(req: ExplainRequest) -> set[int]:
    return {m["index"] for m in req.messages if m["sender"] == "contact" and m.get("flag")}
