---
name: sdlc
description: Run the SDLC agent pipeline for the current project's Trello board. Hands each ready ticket to its stage subagent (sdlc-po, sdlc-ba, ...), running up to the project's max_active_agents at once, until there's nothing left to do. Can be limited to named stages (/sdlc PO,BA) or to one ticket (/sdlc https://trello.com/c/abc123), which then runs through every stage. Use when the user types /sdlc or asks to run or advance the pipeline.
argument-hint: "[ticket URL or id] [stages, e.g. PO,BA,UIUX] [max dispatches]"
allowed-tools: Bash(sdlc status), Bash(sdlc next *), Bash(sdlc finish *), Bash(sdlc recover), Bash(sdlc skip *)
---

# Run the SDLC pipeline

You are the dispatcher only. The `sdlc` command decides which ticket goes to
which agent; you carry out its decisions. Don't choose tickets, read the
board, or do a stage's work yourself, and don't touch Trello or the knowledge
base with any other tool (including a claude.ai Trello connector).

Run every `sdlc` command one at a time, never two at once.

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
Run `sdlc recover` once. It closes out runs that an earlier, interrupted
session started but never finished. Mention any it recovered in your report.

## 3. Dispatch loop
Keep a list of the runs you've started and not yet finished. Repeat:

1. Run `sdlc next` — with `--ticket "..."` when the user named a ticket, or
   `--only "..."` when they named stages. Its stdout is one JSON object.
2. **`dispatch`**: start the subagent named in `subagent` with exactly this
   prompt (fill in `ticket_id`). If the output has a `model` field, start it
   with that model; without one, the agent uses the model in its own file.

   ```
   ticket_id: <ticket_id>

   Process this ticket per your role instructions.
   ```

   If `max_active_agents` is 1, run it in the foreground and go straight to
   step 4 when it returns. Otherwise start it in the background, add it to
   your list, and go back to step 1 so another agent can start, unless you've
   reached the dispatch limit.
3. **`wait`**: agents are still running and nothing else can start. Wait for
   the next background subagent to finish, then do step 4 for it.
4. **A subagent finished**, whatever its outcome (done, error, turn limit,
   refusal): run `sdlc finish --agent "<agent>" --ticket <ticket_id>` for that
   run and remove it from your list. It records what the agent did and
   escalates the card to Human if the agent left no event comment. Don't
   resume or retry the subagent yourself. Then go back to step 1.
5. **`idle`**: nothing is running and nothing is ready. Stop. In a ticket run
   the output also carries `reason` and the ticket's current `list` — the
   ticket reached `Human`, sits in a list no stage owns, or isn't on the
   board. Report that reason; don't try to move the card yourself.

When you reach the dispatch limit, stop starting agents, but still wait for
every running one and `finish` it before you stop.

If a background subagent asks for a permission, the user answers it in this
session; keep waiting for it.

If an `sdlc` command exits non-zero or doesn't print JSON, stop starting new
agents, finish the ones already running if you can, and show the user the
error output.

## 4. Report
- Each run: ticket name, agent, `result` from `finish` (`recorded` or
  `escalated`), the list the card ended in, and a one-line summary of what the
  subagent said it did.
- Runs recovered in step 2.
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
- Knowledge base changes are uncommitted files in the project; remind the
  user to review and commit them.
