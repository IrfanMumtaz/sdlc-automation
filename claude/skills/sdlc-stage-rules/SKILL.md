---
name: sdlc-stage-rules
description: Rules every SDLC pipeline stage agent follows, from sdlc-po through sdlc-deploy: checking the card's list, loading context, advance vs bounce vs escalate, event comments, the decision log, reviewing drafts with the person (design stages), working unattended. Preloaded into those agents; not for direct use.
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
- **Related features.** The knowledge base's features are the record of how
  the product already works and why. Call `list_features` with the ticket's
  key terms (the nouns and actions it's about, its tags), and read the docs
  of every feature it touches, extends or could contradict — the ones your
  stage needs (your agent instructions say which). Stay consistent with
  them: the same terms, actors, rules, screens and patterns. When your
  ticket changes how an existing feature works, say so explicitly in your
  doc and in `decisions.md`, naming the feature; never silently diverge.
  Name the related features you used in your doc, so later stages read the
  same ones.
- The card's comment history. If the latest `[BOUNCE]` targets your stage,
  the ticket came back to you: fix what it and `decisions.md` describe
  before anything else.

## 3. End with exactly one outcome

| Outcome | When | Steps, in order |
|---|---|---|
| **Advance** | Your stage's Definition of Done is met | finish your stage's work (docs, code, or both — a stage that commits pushes first) → `append_decision` for anything later stages should know → `advance_ticket` to the next stage → post `[AGENT_DONE]` |
| **Bounce** | An earlier stage's doc blocks your work, and that stage can fix it from the ticket and the knowledge base | `append_decision` with each finding and a suggested fix → `advance_ticket` to that stage → post `[BOUNCE]` |
| **Escalate** | Only a person can unblock it: missing project knowledge, a business or architecture decision nobody has made, sources that contradict each other, or a problem already bounced once for the same reason. For the design stages, only what a person's answer in `/sdlc` can't fix (the product docs are still templates, the ticket has no feature) | `append_decision` with what's needed (if the feature folder exists) → `advance_ticket` to `Human` → post `[ESCALATION: agent-stuck]` |

**PO, BA, UI/UX and Solution Architect never advance or bounce without a
person's approval.** Before either, they review their draft with the person
running `/sdlc` (§7), round after round, until the person approves it. The
Knowledge Base Writer asks the person the same way when it needs a decision
(§8).

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

Post exactly one event comment per run. A run paused for a review posts
none until it ends. Never move a card without its event comment, and
never post an event you didn't carry out.

### When the ticket and a project doc disagree
Project docs (`product/`, `architecture/`, `patterns/`) record what was
decided, but decisions change. When the ticket needs something a project doc
rules out — a business rule, a persona's access, a convention — don't block
on it, and don't silently follow either side. If you're a design stage
(PO through Knowledge Base Writer), ask the person whether the doc has
changed — a question in your review (§7, §8) quoting the doc's rule and what
the ticket needs, with options `Yes: the doc changes` and
`No: the ticket changes`:
- **Yes:** record it with `append_decision` as
  `APPROVED CHANGE: <section>/<doc>, <part> | now: <the new rule, in the
  person's words> | was: <the old rule> (approved by a person in /sdlc)`,
  and treat the new rule as fact for this ticket. The Knowledge Base Writer
  records it in the project doc, and from there it reaches every ticket.
- **No:** the ticket is what changes: PO fixes the spec, a later stage
  bounces to the stage whose doc relies on the old reading.

Before asking, check the doc is current: the router brings each ticket up to
date with the development branch before every run, so a change another
ticket already got approved and recorded is in the doc now. Don't ask again
about a change `decisions.md` already records as approved.

## 5. Decision log
`append_decision(slug, entry)` adds a dated line to the feature's
`decisions.md`, signed with your stage. Write `entry` as
`<what happened> | <why>`. Use it for:
- bounce and escalation findings, one entry per finding
- judgment calls a later stage needs to know about
- proposals for project docs (a missing glossary term, a new convention, an
  architecture change) for the Knowledge Base Writer stage, and approved
  changes to them (§4, "When the ticket and a project doc disagree")

## 6. Your ticket's branch
Other stages are working other tickets at the same time, so every ticket has
its own git branch, and its own workspace holding a worktree of each
repository on that branch. Your prompt names them (`worktree`,
`project_dir`, `branch`, `repos`). The router prepared them before your
run, with everything earlier stages pushed for this ticket and the latest
development branch merged in, so project docs and other features are
current.
- Your knowledge base tools already read and write that ticket's copy of the
  knowledge base. When you finish, the router commits your changes there and
  pushes the branch; you never commit knowledge base changes yourself.
- If you read code with `Read`, `Glob` or `Grep`, read it under `worktree`
  (each repository's path is in `repos`), never from your working directory: that's the person's own
  checkout, on whatever branch they left it.

## 7. Review with the person (PO, BA, UI/UX, Solution Architect)
You work the way the `/sdlc-kickoff` specialists do: you draft, the person
reads it, you discuss, you revise, and nothing goes forward until they
approve it. Never fill a gap quietly and carry on. The person running `/sdlc`
reviews every draft, and their approval is what lets the ticket move.

**1. Write the complete draft.** Do your stage's whole job first: every doc
your stage owns, written in full to its template and quality bar with
`write_feature_doc` (it's on the ticket's branch; nothing downstream reads
it until you advance). BA's draft is its findings and the outcome it
proposes. Wherever a source (the ticket, a person, the knowledge base, the
code, a related feature) states something, use it. Where none does:
- if a reasonable person would fill it the same way, fill it, and list it as
  an **assumption**;
- if it's a real decision (scope, a rule, a priority, who may do what, a
  trade-off), write `TBD (Q<n>)` in the doc and ask it as a **question**,
  with the options you'd accept, your recommendation first.

**2. Request the review.** Call `request_review` with the docs, every
assumption (one sentence each, saying where it is and what you assumed) and
the questions (at most 8 a round, the most important first). Then end your
turn with a message that starts `[REVIEW]` and holds:
- the draft: each doc you wrote this round in full, exactly as written (UI/UX
  adds the mockup file paths, which are on the card too; BA gives its
  findings, each with where it is, what's wrong and the fix, and the outcome
  it proposes). From round 2 on, first list what changed since the last
  round;
- `Assumptions:` numbered `A1.`, `A2.`, …;
- `Questions:` numbered `Q1.`, `Q2.`, …, each with why it matters and its
  options;
- the outcome you propose once it's approved (advance, or bounce to which
  stage and why).
Don't move the card or post an event comment.

**3. Read the response.** You're continued in this same conversation with a
`review:` block (or, if the person left it for later, a fresh run starts
with it in the prompt: reload your context first, §2, and read your drafts
back with `read_feature_doc`):

```
review:
  round: <n>
  verdict: approve | revise
  answers:
  - Q1: <question>
    A: <answer>
  changes: <what the person wants different, in their words>
```

- Record each answer with `append_decision`, as
  `Q: <question> | A: <answer> (answered by a person in /sdlc)`.
- `revise`: apply the answers and changes everywhere they reach, replace
  every `TBD` they settle, and go back to step 2 with the revised draft.
  Corrections to an assumption replace it; assumptions the person didn't
  question still stand but stay listed until the draft is approved. Ask
  again only about something new the response raised, never the same
  question.
- `approve`: the draft stands as written. Record
  `APPROVED: <docs or findings> (review round <n>) by a person in /sdlc |
  assumptions confirmed: <A1 …, in a few words each>` with
  `append_decision`, then end with the outcome you proposed (§3).

A draft with a `TBD` or an open question can't be approved: it goes round
again. If the person's response contradicts a project doc, that's an
`APPROVED CHANGE` (§4).

## 8. Working unattended
No one can answer questions during your run, except through `/sdlc`. Later
stages (Senior Developer onward) decide with the judgment in their role
skill, or escalate with a reason specific enough that a person can fix it
in one pass. Don't stall.

The Knowledge Base Writer doesn't review a draft, but asks the person instead
of escalating when it needs a decision: `request_review` with no docs and
just the questions, then end your turn with a `[REVIEW]` message listing
them. You're continued with a `review:` block: record the answers as in §7,
and carry on.

No stage ever puts its questions or drafts in card comments.
