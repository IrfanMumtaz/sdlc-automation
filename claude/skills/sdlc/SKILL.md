---
name: sdlc
description: Run the SDLC agent pipeline for the current project's Trello board. Hands each ready ticket to its stage subagent (sdlc-po, sdlc-ba, ...), running up to the project's max_active_agents at once, until there's nothing left to do. Can be limited to named stages (/sdlc PO,BA) or to one ticket (/sdlc https://trello.com/c/abc123), which then runs through every stage. Use when the user types /sdlc or asks to run or advance the pipeline.
argument-hint: "[ticket URL or id] [stages, e.g. PO,BA,UIUX] [max dispatches]"
allowed-tools: Bash(sdlc status), Bash(sdlc next *), Bash(sdlc finish *), Bash(sdlc recover *), Bash(sdlc skip *), Bash(sdlc review *)
---

# Run the SDLC pipeline

You are the dispatcher only. The `sdlc` command decides which ticket goes to
which agent; you carry out its decisions. Don't choose tickets, read the
board, or do a stage's work yourself, and don't touch Trello or the knowledge
base with any other tool (including a claude.ai Trello connector).

Run every `sdlc` command one at a time, never two at once.

## 0. Start a session
Run `python3 -c "import uuid; print(uuid.uuid4().hex[:12])"` and
`echo $PPID` (two separate commands). Save both values as `SESSION_ID` and
`SESSION_PID`. Pass `--session <SESSION_ID> --session-pid <SESSION_PID>` to
every `sdlc next`, `sdlc finish` and `sdlc recover` call in this run. This
tags your dispatches so that another person's `/sdlc` session on the same
project won't kill your running agents, and vice versa.

## 1. Check the project
Run `sdlc status`.
- If it says there's no SDLC project here, stop and tell the user to set one
  up from the project's root folder: `sdlc init --board <Trello board URL>`
  (add `--create-lists` if the board doesn't have the stage lists yet), then
  run `/sdlc-kickoff`.
- If Trello credentials are missing, stop and tell the user to run
  `sdlc init --board <their board URL>` once in their own terminal, in the
  project's root folder: it asks for a Trello key and token, checks them and
  saves them to the project's gitignored `.sdlc/.env`. Never ask for the key or
  token in the conversation, and never read or write `.sdlc/.env` yourself.
- If it prints a `Model versions: ... RESTART NEEDED` line, it just wrote,
  changed or removed the project's copy of a stage agent pinned to a model
  version, and this session still has the old one. Show the line and stop:
  the user restarts Claude Code and runs `/sdlc` again.
- Note `max_active_agents` and `max_dispatches_per_run` from the settings
  line, and which stages this project runs.

**Arguments.** `$ARGUMENTS` may hold, in any order:
- **a ticket**: a Trello card URL (`https://trello.com/c/...`), a short link
  or a card id. This run then works **only that ticket**, through every stage
  it still has to pass, and ignores every other card on the board. Pass it as
  `sdlc next --ticket "<what the user typed>"` on every call in the loop.
  Stage names don't apply to a ticket run — the point is to move that one
  card — so don't pass `--only` as well; if the user gave both, say you're
  ignoring the stage names and why.
- **a number**: the dispatch limit for this run. Otherwise use
  `max_dispatches_per_run` — except in a ticket run, where the default is
  **15**, since one ticket takes eleven dispatches to cross the board and a
  bounce costs more.
- **stage names**, comma-separated (`PO,BA,UIUX`, `ui/ux`, `solution architect`;
  case, spaces, slashes and dashes don't matter): run only those stages this
  time, **in the order given**, which the router rotates through so each
  named stage gets a turn. Pass them through unchanged, order intact, as
  `sdlc next --only "<what the user typed>"`; the command validates them and
  names the valid stages if one is wrong. Without stage names, don't pass
  `--only`, and stages run in pipeline order.

A ticket is anything that looks like a Trello card URL, short link or id;
anything else that isn't a number is a stage name.

Say in your first message what this run covers — the ticket, or which stages
— and what the dispatch limit is.

**Which ticket runs first.** You don't choose; `sdlc next` does. Within a
stage it takes the highest priority label (`P0`, then `P1`, then `P2`,
unlabelled last), and among equals the card nearest the top of the list.
People set those labels by hand — never add, change or suggest changing a
card's labels yourself.

**Skipped stages.** `sdlc next` also moves cards past stages they skip,
before it picks anything, and reports them under `skipped` in its output. No
agent runs for a skipped stage, so there's nothing to dispatch or finish —
just report them (see step 4). If the user asks to skip a stage, run it and
say what changed:

```
sdlc skip --ticket "<url or id>" --stages "UI/UX" --reason "<why>"   # this ticket
sdlc skip --project --stages "UI/UX"                                 # every ticket
sdlc skip --ticket "<url or id>" --clear                             # stop skipping
sdlc skip --show                                                     # what's skipped now
```

Never skip a stage on your own judgment, and never to get past a stage that
bounced or escalated a ticket — a person decides that.

## 2. Recover
Run `sdlc recover --session <SESSION_ID> --session-pid <SESSION_PID>` once.
It closes out runs from sessions that are no longer alive (interrupted or
exited), while leaving another person's active `/sdlc` session alone. Mention
any it recovered in your report; if it reports `active_in_other_sessions`,
tell the user those agents belong to another live session.

## 3. Dispatch loop
Keep a list of the runs you've started and not yet finished. Repeat:

1. Run `sdlc next --session <SESSION_ID> --session-pid <SESSION_PID>` — with
   `--ticket "..."` when the user named a ticket, or `--only "..."` when they
   named stages. Its stdout is one JSON object.
2. **`dispatch`**: start the subagent named in `subagent` with exactly this
   prompt, filled in from the output. If the output has a `model` field,
   start it with that model; without one, don't pass a model: the agent uses
   the one in its file (a stage pinned to a model version has it there).

   ```
   ticket_id: <ticket_id>
   worktree: <worktree>
   project_dir: <project_dir>
   branch: <branch>
   compose_project: <compose_project>
   repos:
   - <name>: <path> (base <base>)
   <one line per entry in `repos`>

   Process this ticket per your role instructions.
   ```

   If the output has `review` (the user responded to this stage's review in
   an earlier session), put the review block (step 3a) before the last line,
   filled in from it exactly as recorded.

   Every ticket has its own branch and its own workspace (`worktree`), which
   `sdlc next` has already created or brought up to date: one git worktree
   per repository the stage needs, all on that branch. That's what lets
   agents on different tickets run at once without sharing a checkout. Never
   switch branches, create worktrees or run git yourself. Show any
   `git_warnings` in the output to the user.

   If `max_active_agents` is 1, run it in the foreground and go straight to
   step 4 when it returns. Otherwise start it in the background, add it to
   your list, and go back to step 1 so another agent can start, unless you've
   reached the dispatch limit.
3. **`wait`**: agents are still running and nothing else can start. Wait for
   the next background subagent to finish, then do step 4 for it.
4. **A subagent finished**, whatever its outcome (done, error, turn limit,
   refusal). If its final message starts with `[REVIEW]`, it hasn't
   finished: it's waiting for the user to review its draft. Don't run
   `sdlc finish`; keep it in your list and go to step 3a. Otherwise run `sdlc finish --agent "<agent>" --ticket <ticket_id> --session <SESSION_ID> --session-pid <SESSION_PID>`
   for that run and remove it from your list. It records what the agent did,
   escalates the card to Human if the agent left no event comment, and
   commits the stage's knowledge base changes on the ticket's branch and
   pushes it (the `git` field). Don't resume or retry the subagent yourself,
   except to give it the user's review (step 3a). Then go back to step 1.
5. **`idle`**: nothing is running and nothing is ready. If the output has
   `reviews` you haven't put to the user this run, do them (step 3a, saved
   reviews) and go back to step 1; otherwise stop. In a ticket run
   the output also carries `reason` and the ticket's current `list` — the
   ticket reached `Human`, sits in a list no stage owns, or isn't on the
   board. Report that reason; don't try to move the card yourself.

When you reach the dispatch limit, stop starting agents, but still wait for
every running one and `finish` it before you stop.

If a background subagent asks for a permission, the user answers it in this
session; keep waiting for it.

## 3a. Reviews with the design stages
PO, BA, UI/UX and Solution Architect work with the user the way the
`/sdlc-kickoff` specialists do: each writes a complete draft, lists its
assumptions and questions, and goes round with the user until the user
approves it. Nothing advances on assumptions. You relay, exactly as kickoff
does: the agents can't talk to the user, and you never review, answer or
approve for the user. The Knowledge Base Writer uses the same route for the
odd question. None of this goes on the card.

**A live agent's review.** Its final message starts with `[REVIEW]`: the
draft (the docs it wrote this round in full, or BA's findings; from round 2,
what changed first), `Assumptions:` (`A1.` …), `Questions:` (`Q1.` …, each
with why and options) and the outcome it proposes. It's still running as far
as the router is concerned: its stage stays busy and the card stays in its
list, while other agents carry on in the background.

1. Show the user the whole message as the agent wrote it, under a heading
   naming the agent and ticket, e.g. "**PO (sdlc-po): Export CSV — review
   round 2**". Don't summarise or trim the draft: reading it is the review.
2. Ask, with AskUserQuestion (up to 4 per call, more calls if needed):
   - each question: `question` is `<question>`, then the agent's why in
     brackets; `header` the stage and id (`PO Q1`, 12 characters at most);
     `options` the agent's options in its order, the first labelled
     `(Recommended)`. The user can always type their own with "Other".
   - then the verdict, `header` `Verdict`: options `Approve` (only when the
     round has no questions), `Change something`, `Answer later`,
     `Send to Human`. Approving means the draft and every listed assumption
     stand as written.
   If the user picks `Change something` without typing what, ask them in
   plain text what should change, and wait for their reply. Take their
   words as they are, including any corrections to assumptions (`A3 is
   wrong: …`).
3. Then:
   - **Approve, or answers and changes:** continue that same subagent
     (SendMessage to it) with only the review block below. It revises and
     comes back with another `[REVIEW]` round, or, once approved, finishes.
     Each time it returns, do step 4 of the loop for it again.
   - **Answer later:** run `sdlc finish` for the run (step 4). Its result is
     `review`: the router keeps the review, the drafts stay on the ticket's
     branch, and the card waits until a later `/sdlc` run puts it to the user
     again.
   - **Send to Human:** run `sdlc finish` for the run, then
     `sdlc review respond --ticket <ticket_id> --escalate`. The card goes to
     Human with the questions and assumptions on it.

   If you can't continue the subagent (the session restarted, the agent is
   gone), run `sdlc finish` for it and record the response as for a saved
   review below.

The review block, exactly as the user gave each answer (an option's label
without `(Recommended)`, or their own words); leave out `answers` or
`changes` when there are none:

```
review:
  round: <n>
  verdict: approve | revise
  answers:
  - Q1: <question>
    A: <answer>
  changes: <what the user wants different, in their words>
```

`verdict` is `approve` only when the user chose `Approve`; any answer or
change is `revise`, and the agent brings the revised draft back for
approval.

**Saved reviews.** Any `sdlc next` output can carry `reviews`: tickets whose
agent asked in an earlier session and the user didn't respond, each with
`ticket_id`, `ticket_name`, `stage`, `round`, `docs`, `assumptions` and
`questions`. There's no agent to continue. Run
`sdlc review show --ticket <ticket_id>` to print the draft docs from the
ticket's branch with the assumptions and questions, show that to the user,
and ask as in step 2. Then record the response:
- `sdlc review respond --ticket <ticket_id> --approve`
- `sdlc review respond --ticket <ticket_id> --answers '{"Q1": "<answer>"}' --changes '<their words>'`
  (either or both; inside single quotes, write a `'` as `'\''`)
- `sdlc review respond --ticket <ticket_id> --escalate`
- Answer later: record nothing.
The ticket's next dispatch starts its stage with the response as a review
block. `sdlc review list` shows every review still waiting.

Put each ticket's review to the user at most once per run.

## 4. Report
- Each run: ticket name, agent, `result` from `finish` (`recorded` or
  `escalated`), the list the card ended in, the branch, and a one-line summary
  of what the subagent said it did.
- Project docs from `finish` after a Knowledge Base Writer run (`git` →
  `project_docs`): the docs published to the development branch, or why
  nothing was (`conflicts`, `reason`). Published docs reach every other
  ticket on its next dispatch; a `note` saying the user's checkout has the
  development branch checked out means they should pull.
- Git trouble from `finish`, per repository under `repos`: a `pushed` value
  that says `failed`, a `commit_error`, or `uncommitted` files the stage left
  in its worktree.
- Tickets under `escalated` in a `next` output: their branch needs a person
  (it diverged from the pushed one, or is checked out elsewhere).
- Runs recovered in step 2.
- **Reviews:** each ticket that was reviewed, the rounds it took and how it
  ended (approved, sent to Human, or left for later), and which tickets are
  still waiting for the user's review.
- **Stages skipped** (any `skipped` entries across the run): ticket, the stage
  skipped, and where it went. Say whether it was the project's setting or that
  ticket's own mark, and that no agent ran.
- **A ticket run** ends with where that card now sits and what has to happen
  next: the stage it's waiting for, the person it's waiting on in `Human`, or
  the stages it still has to pass. Don't list the rest of the board.
- The `waiting` cards from the final `next` output, grouped by list, with any
  priority label shown in brackets. Cards wait when their stage has no agent
  built yet, or when this run left that stage out; cards in `Human` need a
  person. If stages were left out, say so, and that `/sdlc` without arguments
  covers them all.
- Anything under `no_agent_built` in the output: the user asked for those
  stages, but no agent exists for them yet, so nothing ran there.
- If you stopped at the dispatch limit rather than at idle, say so.
- Each ticket's work, docs and code, is committed on its own branch and
  pushed, in every repository it changed. The only merge is Deploy's, into
  the ticket's release branch; a person reviews and merges the release's
  pull request. `sdlc worktree list` shows every ticket's worktree and
  whether its work is pushed.
