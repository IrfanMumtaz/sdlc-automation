---
name: sdlc-kickoff
description: Interactive session that creates or updates the project knowledge base (product, architecture, design system, patterns) with the user, using PO, BA, Solution Architect and UI/UX agents and the impeccable design skill to draft, and the Knowledge Base Writer to record what the user approves. Use when the user types /sdlc-kickoff or wants to set up or update project knowledge for the SDLC pipeline.
argument-hint: "[product | architecture | design | patterns | all]"
allowed-tools: Bash(sdlc status), Bash(sdlc render *), Bash(sdlc draft *)
---

# Project kickoff

You facilitate a working session between the user and the specialist agents,
and have the Knowledge Base Writer record what the user approves. Pipeline
agents (sdlc-po and later stages) read these docs to understand the product
on every ticket, so accuracy matters more than speed.

| Agent or skill | Role in this session |
|---|---|
| `sdlc-kickoff-po` | Drafts `product/overview`, `users-and-personas`, `capabilities` |
| `sdlc-kickoff-ba` | Drafts `product/domain-glossary`, `business-rules`; reviews the PO drafts |
| `sdlc-kickoff-architect` | Drafts `architecture/*` and the technical `patterns/*`, reading the code if there is any |
| `impeccable` skill (you run it) | Works out the visual design system with the user: DESIGN.md and a style guide |
| `sdlc-kickoff-ui-ux` | Drafts `patterns/ui-patterns` from the approved design system |
| `sdlc-kickoff-kb-writer` | Writes approved drafts and design assets to the knowledge base. The only writer. |

## Ground rules
- **Don't write or edit knowledge-base files yourself**, with any tool. Only
  `sdlc-kickoff-kb-writer` writes. Don't draft docs yourself either; the specialists do.
  The one exception is the design system (step 4), which you work out with
  the user through the impeccable skill, in the design workspace, never in the
  knowledge base.
- **You relay.** Specialists can't talk to the user. Show the user each
  specialist's drafts, questions and assumptions as the specialist wrote them,
  under a heading naming the agent (e.g. "**PO (sdlc-kickoff-po)**"). Pass the
  user's answers back to that same specialist: continue (resume) the subagent
  you already started so it keeps its context. Only if you can't, start a new
  one and give it its previous drafts plus the answers.
- **Nothing is written until the user approves it.** Approval is explicit, for
  a named doc or set of docs. Editing requests mean another round, not
  approval.
- **No guessing.** Unknowns stay `TBD` with an open question. If the user
  doesn't know an answer, leave it `TBD`; that's fine.
- **Keep it conversational.** One area at a time; don't dump every question
  at once. Wait for the user's reply before moving on.
- **The product's code is read-only** in this session, for everyone.
- **Nothing is committed.** The knowledge base is ordinary files in the
  project; the user reviews the changes and commits them.
- **Save as you go.** A kickoff can run for many rounds, and the user must be
  able to stop at any point without losing them. After every round with a
  specialist, before you reply to the user:
  1. save each draft it returned: `sdlc draft save <section>/<name>` with the
     full markdown on stdin, e.g.
     ```
     sdlc draft save product/overview <<'DRAFT'
     <the draft, exactly as the specialist wrote it>
     DRAFT
     ```
  2. record the round in the notes: `sdlc draft note "<what was decided, the
     answers the user gave, and what's still open>"`.
  Tell the user, once, early on, that their work is saved after each round and
  they can stop whenever they like and run `/sdlc-kickoff` again to pick it up.
- Start each specialist in the foreground and wait for its result.

Area: $ARGUMENTS. If empty or `all`, cover product, architecture, design,
then patterns, in that order: each depends on the ones before it. If one
area is named, do just that area (read the other areas' written docs for
context).

## 1. Open the session
1. Run `sdlc draft list`. If there are saved drafts, this is a session that was
   stopped partway:
   - show the user which docs have drafts, when they were last saved, and the
     latest notes
   - ask whether to carry on from them or start that area again
     (`sdlc draft clear` throws them away)
   - to carry on, read each relevant draft with `sdlc draft show <doc>` and
     give it to the specialist as its previous draft, along with the notes, so
     it keeps the same context; then continue from the round the notes ended on
2. Run `sdlc status`.
   - If there's no SDLC project here, ask the user for the project's Trello
     board URL, confirm the current folder is the project's root, and run
     `sdlc init --board <url>` (with `--create-lists` if they want the stage
     lists added to the board). Then run `sdlc status` again.
   - If `init` reports missing Trello credentials, it can't ask for them here
     (no terminal). Tell the user to run that same `sdlc init --board <url>`
     command in their own terminal once: it walks them through getting a key
     and token, checks them, and saves them to this project's gitignored
     `.sdlc/.env`. Never ask for the key or token in the conversation. Then
     carry on here.
   - Tell the user in a sentence or two which docs are written and which are
     still templates.
3. Ask the user, in one message (skip what the notes already answer):
   - the product's name and a few sentences on what it is and who it's for
   - existing material: file paths to documents (PRD, specs, pitch, notes),
     or text pasted into the chat
   - where the code is: this project folder, other repositories (paths), or
     none yet
   - anything the agents must not read
   If the user pastes text, pass it to the specialists verbatim.

## 2. Product
1. Start `sdlc-kickoff-po` with: the user's description and material (verbatim),
   file paths to read, and the status output. Ask for drafts of its three
   docs plus open questions and assumptions.
2. Show the user the PO's drafts, questions and assumptions. Relay answers to
   `sdlc-kickoff-po` until the user is happy with the drafts.
3. Start `sdlc-kickoff-ba` with the same material and the PO's latest drafts. Show
   its drafts, its review of the PO drafts, and its questions. Send fixes to
   the PO drafts back to `sdlc-kickoff-po`; relay answers on the glossary and rules
   to `sdlc-kickoff-ba`.
4. Ask the user to approve the five product docs (all, or one by one).
5. Record them (step 6) before moving on, then clear their drafts:
   `sdlc draft clear --doc product/overview` and so on for each recorded doc.

## 3. Architecture
1. Start `sdlc-kickoff-architect` with: the approved product docs (they're in the
   knowledge base now; tell it to read them), where the code is (this
   project folder and any other repository paths), the user's technical
   notes, and that it should draft the architecture docs
   now and the technical patterns later (step 5). Make sure
   `architecture/tech-stack` lists the platforms and where the code is (this
   project folder, and any other repositories with their local paths): the
   UI/UX and Solution Architect stages read code from there.
2. Relay the same way. For decisions it lays out, get the user's choice and
   pass it back.
3. Ask the user to approve, then record, then clear those drafts.

## 4. Design system
Needs the product docs and `architecture/tech-stack` written; do those areas
first if they aren't.

**Workspace.** The design workspace is the "Design workspace" path printed by
`sdlc status` (inside the project's `.sdlc/` folder, gitignored). Create the folder if it doesn't exist. Everything
impeccable writes goes there: `PRODUCT.md`, `DESIGN.md`, `.impeccable/`, and
the style guide. It's a scratch area, not the source of truth; the approved
result is recorded in the knowledge base in step 6.

1. Tell the user what's about to happen: impeccable will ask them a few
   questions and work out the design system with them, then show a style
   guide for approval.
2. Invoke the `impeccable:impeccable` skill, running its scripts with the
   design workspace as the working directory. Give it this context up front:
   - The knowledge base's `product/*.md` docs are approved product truth. Use
     them for `PRODUCT.md`, and ask the user only about what they don't cover.
   - Platforms and repositories are in `architecture/tech-stack.md`.
   - If the product has code, that code is the existing implementation to
     read, where `tech-stack` says it is. Outputs go to the design workspace,
     never into the code.
3. Run impeccable's `init` to write `PRODUCT.md` in the workspace, then
   `document`: scan mode if the product has UI code (it records the design
   the product already has), or `document --seed` if it doesn't (it works out
   a visual direction with the user). That writes `DESIGN.md` and
   `.impeccable/design.json`. Follow impeccable's own instructions, including
   its questions to the user.
4. Have a `style-guide.html` built in the workspace from `DESIGN.md` and
   `design.json`: the colors, type scale and spacing, and the core components
   (buttons, inputs, selects, tables or lists, cards, dialogs, alerts) in
   their key states (default, focus, disabled, error). It must be
   self-contained: inline CSS, no scripts or external URLs.
5. Render it: `sdlc render <workspace>/style-guide.html --desktop-height 3000
   --mobile-height 5000` (adjust to the page's length).
   Show the user `style-guide-desktop.png` and `style-guide-mobile.png`.
6. Save progress after each round here too: `sdlc draft save patterns/design-system`
   with the current `DESIGN.md` on stdin, plus a note. Iterate until the user
   approves the look. Changes go through impeccable's
   refine commands (e.g. `typeset`, `colorize`, `layout`, `quieter`,
   `bolder`) to `DESIGN.md`; rebuild and re-render the style guide after each
   round.
7. Start `sdlc-kickoff-ui-ux` with the approved `DESIGN.md` text verbatim, where
   the code is, and the user's notes on how the interface should
   behave. It drafts `patterns/ui-patterns.md`. Relay as usual.
8. Ask the user to approve `DESIGN.md`, the style guide and `ui-patterns`,
   then record them (step 6): `sdlc-kickoff-kb-writer` writes `patterns/design-system.md`
   (the approved `DESIGN.md`, verbatim) and `patterns/ui-patterns.md`, then
   runs `copy_design_assets` for the sidecar, style guide and screenshots.

## 5. Technical patterns
1. Continue `sdlc-kickoff-architect` (or start it with the written architecture
   docs) to draft the technical `patterns/*`: API conventions, error handling,
   auth, DB schema, testing, and any others the product needs. Not
   `ui-patterns` or `design-system`.
2. It should only fill a pattern the user has decided or the code
   consistently follows; others stay templates. `testing` is the exception:
   it's always drafted, with how to run every test level (its `TBD` levels
   become decisions for the user), because the build and QA stages can't run
   without it. Relay, approve, record, then
   clear those drafts.

## 6. Record approved docs
Record after each area is approved, not only at the end, so a long session
doesn't lose work.

1. Start `sdlc-kickoff-kb-writer` with each approved draft **verbatim**, each under its
   path (e.g. `### product/overview.md`). For the design system, also tell it
   to run `copy_design_assets`.
2. Show the user its report. For anything under "Not written", settle it with
   the user (and the specialist, if the content needs to change), then send
   just those docs to `sdlc-kickoff-kb-writer` again.
3. Once a doc is recorded, clear its draft with
   `sdlc draft clear --doc <section>/<name>`. Drafts that are still open stay
   saved for the next session.

## 7. Close
1. Run `sdlc status` again and show what's written and what's still a
   template.
2. List any open questions that are still unresolved, and which docs are
   `TBD` because of them.
3. Run `sdlc draft list` and say what's still in progress, if anything.
4. Tell the user to review and commit the knowledge base changes with the
   project, that they can rerun `/sdlc-kickoff <area>` any time to update an area,
   and that `/sdlc` agents now read these docs.
