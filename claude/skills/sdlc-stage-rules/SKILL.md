---
name: sdlc-stage-rules
description: Rules every SDLC pipeline stage agent follows, from sdlc-po through sdlc-deploy: checking the card's list, loading context, advance vs bounce vs escalate, event comments, the decision log, working unattended. Preloaded into those agents; not for direct use.
user-invocable: false
---

# SDLC stage rules

You are one stage of an automated pipeline. The orchestrator (plain code, not
a model) gave you one ticket because its Trello card sits in your stage's
list. When you finish, the card's list and your event comment are the record
the orchestrator and every later stage rely on.

Stages in order, with their exact list names: PO → BA → UI/UX → Solution
Architect → Knowledge Base Writer → Senior Developer → Code Analyst → Test
Scenario Writer → Automated QA → PO Tester → Deploy. `Human` is where people
take over.

## 1. Check you're the right stage
Call `get_ticket` first. If its `Current list` isn't your stage, do no work:
post the `[MISMATCH]` comment (below) and stop. Don't move the card.

## 2. Load context before working
- The written `product/` docs: `overview` always, plus the others your agent
  instructions name. If `product/overview` is still a template, escalate with
  reason `product knowledge base is empty; run /sdlc-kickoff`.
- The feature's docs from earlier stages (find the slug with `find_feature`,
  except PO, which creates it) and its `decisions.md`.
- The card's comment history. If the latest `[BOUNCE]` targets your stage,
  the ticket came back to you: fix what it and `decisions.md` describe
  before anything else.

## 3. End with exactly one outcome

| Outcome | When | Steps, in order |
|---|---|---|
| **Advance** | Your stage's Definition of Done is met | finish your stage's work (docs, code, or both — a stage that commits pushes first) → `append_decision` for anything later stages should know → `advance_ticket` to the next stage → post `[AGENT_DONE]` |
| **Bounce** | An earlier stage's doc blocks your work, and that stage can fix it from the ticket and the knowledge base | `append_decision` with each finding and a suggested fix → `advance_ticket` to that stage → post `[BOUNCE]` |
| **Escalate** | Only a person can unblock it: missing project knowledge, a business or architecture decision nobody has made, sources that contradict each other, or a problem already bounced once for the same reason | `append_decision` with what's needed (if the feature folder exists) → `advance_ticket` to `Human` → post `[ESCALATION: agent-stuck]` |

- Bounce only to an earlier stage, and only for problems that block you.
  Non-blocking notes go in `decisions.md`, and you advance.
- If `decisions.md` shows the same problem was bounced before, escalate
  instead of bouncing again.
- Don't leave partial or speculative work behind when you bounce or escalate —
  no half-written doc, no half-built feature pushed to a branch.
- A comment's `reason` is one line a person can act on; details go in
  `decisions.md`.

## 4. Event comments
The orchestrator parses these exactly. Put every value in double quotes, and
use no double quotes inside a value (use single quotes).

```
[AGENT_DONE] agent="<your stage>" ticket=#<ticket_id> moved_to="<list>"
[BOUNCE] agent="<your stage>" ticket=#<ticket_id> target="<list>" reason="<one line>"
[ESCALATION: agent-stuck] agent="<your stage>" ticket=#<ticket_id> reason="<one line>"
[MISMATCH] agent="<your stage>" ticket=#<ticket_id> expected="<your stage>" actual="<current list>"
```

Post exactly one event comment per run. Never move a card without its event
comment, and never post an event you didn't carry out.

## 5. Decision log
`append_decision(slug, entry)` adds a dated line to the feature's
`decisions.md`, signed with your stage. Write `entry` as
`<what happened> | <why>`. Use it for:
- bounce and escalation findings, one entry per finding
- judgment calls a later stage needs to know about
- proposals for project docs (a missing glossary term, a new convention, an
  architecture change) for the Knowledge Base Writer stage

## 6. Working unattended
No one can answer questions during your run. Decide with the judgment in your
role skill, or escalate with a reason specific enough that a person can fix
it in one pass. Don't stall.
