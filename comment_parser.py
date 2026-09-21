"""
Parses agent-written Trello comments into structured events.

Expected formats (agents are responsible for writing these exactly):

  [AGENT_DONE] agent=SeniorDeveloper ticket=#123 moved_to="Code Analyst"
  [BOUNCE] agent=CodeAnalyst ticket=#123 target="Senior Developer" reason="SQL injection risk, line 42"
  [MISMATCH] agent=SeniorDeveloper ticket=#123 expected="Senior Developer" actual="Solution Architect"
  [ESCALATION: bounce-cap] ticket=#123 bounces=4
  [ESCALATION: routing-mismatch] ticket=#123
  [ESCALATION: agent-stuck] agent=Deploy ticket=#123 reason="ambiguous rollback target"

Skips are written by people (through `sdlc skip`), and the router's record of
carrying one out is written by the router itself:

  [SKIP] ticket=#123 stages="UI/UX,Code Analyst" reason="backend-only change"
  [UNSKIP] ticket=#123 stages="UI/UX"
  [SKIPPED] agent="UI/UX" ticket=#123 moved_to="Solution Architect" reason="..."

Deliberately simple key="value" parsing — no need for a real grammar here, and a
strict parser means malformed comments fail loudly instead of silently misrouting.
"""

import re

KV_PATTERN = re.compile(r'(\w+)="([^"]*)"|(\w+)=([^\s]+)')


def _parse_kv(text):
    fields = {}
    for m in KV_PATTERN.finditer(text):
        if m.group(1) is not None:
            fields[m.group(1)] = m.group(2)
        else:
            fields[m.group(3)] = m.group(4)
    return fields


def parse_comment(text):
    """
    Returns a dict like {"type": "AGENT_DONE", ...fields} or None if the
    comment doesn't match any known prefix (i.e. it's a human comment, or
    free-form agent chatter — ignored by the orchestrator either way).
    """
    text = text.strip()

    if text.startswith("[AGENT_DONE]"):
        return {"type": "AGENT_DONE", **_parse_kv(text)}

    if text.startswith("[BOUNCE]"):
        return {"type": "BOUNCE", **_parse_kv(text)}

    if text.startswith("[MISMATCH]"):
        return {"type": "MISMATCH", **_parse_kv(text)}

    # "[SKIPPED]" never matches "[SKIP]" and vice versa: the closing bracket differs.
    if text.startswith("[SKIP]"):
        return {"type": "SKIP", **_parse_kv(text)}

    if text.startswith("[UNSKIP]"):
        return {"type": "UNSKIP", **_parse_kv(text)}

    if text.startswith("[SKIPPED]"):
        # the router's own record of a skip it carried out; nothing left to do
        return {"type": "SKIPPED", **_parse_kv(text)}

    if text.startswith("[ESCALATION"):
        # subtype is inside the brackets, e.g. "[ESCALATION: bounce-cap]"
        subtype_match = re.match(r"\[ESCALATION:\s*([\w-]+)\]", text)
        subtype = subtype_match.group(1) if subtype_match else "unknown"
        rest = text[text.index("]") + 1:]
        return {"type": "ESCALATION", "subtype": subtype, **_parse_kv(rest)}

    return None
