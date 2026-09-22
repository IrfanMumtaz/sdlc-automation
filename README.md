# SDLC Pipeline

An agent pipeline that carries Trello tickets through PO, BA, design,
architecture, development, QA and deployment. It runs inside Claude Code on
your Claude subscription, for any project: you install this engine once, set
up each project with `sdlc init`, then type `/sdlc-kickoff` and `/sdlc` in Claude
Code from that project's folder.

**Current phase:** PO, BA, UI/UX and Solution Architect are built, plus
`/sdlc-kickoff` for setting up a project's knowledge base. A ticket flows through
those four stages and stops in the **Knowledge Base Writer** list, where it
waits until the next agent exists.

## Install (once per machine)

```bash
pip install -r requirements.txt     # requests, mcp
python3 install.py                  # rerun after pulling changes; --uninstall to remove
```

`install.py`:
- links `~/.local/bin/sdlc` to `sdlc.py` (`~/.local/bin` must be on PATH)
- links the agents in `claude/agents/` into `~/.claude/agents/` and the skills
  in `claude/skills/` into `~/.claude/skills/`, so edits in this repo apply
  immediately
- adds the pipeline's permission rules to `~/.claude/settings.json` (backup in
  `settings.json.sdlc-backup`)

It never overwrites an agent, skill or command it didn't create. It installs
no Trello credentials: those belong to each project (below).

Also needed:
- **Trello credentials, per project.** `sdlc init` asks for them the first
  time in each project, checks them against Trello, and saves them to that
  project's `.sdlc/.env`, which is gitignored. It tells you where to get them:
  the API key and token from your Power-Up's API key page at
  https://trello.com/power-ups/admin, using the **Token** link (the token
  starts with `ATTA`), not the Secret. Run `sdlc init` in a terminal so it can
  prompt; `--reauth` replaces them later. To write the file yourself:

  ```
  TRELLO_KEY=your_trello_api_key
  TRELLO_TOKEN=your_trello_token_starting_with_ATTA
  ```

  `TRELLO_KEY` and `TRELLO_TOKEN` set in the environment win over the file
  (useful in CI). Nothing outside the project is read; earlier versions used
  `~/.config/sdlc/.env`, and `install.py` points it out if it's still there.
- **Chrome or Chromium**, for mockups and the design style guide.
- **The impeccable plugin**, for `/sdlc-kickoff design`.

No Anthropic API key is needed: everything runs through your Claude Code login.

## Set up a project

In the project's root folder (usually the product's code repository), in a
terminal so it can ask for credentials the first time:

```bash
sdlc init --board https://trello.com/b/<id>/<name>
sdlc init --board <url> --create-lists --max-active-agents 2   # add missing stage lists, run 2 agents at once
```

The board needs one list per stage, named exactly: PO, BA, UI/UX, Solution
Architect, Knowledge Base Writer, Senior Developer, Code Analyst, Test Scenario
Writer, Automated QA, PO Tester, Deploy, and Human. `--create-lists` adds the
missing ones. Rerunning `init` refreshes the list IDs and keeps your settings.

This creates:

```
<project>/
  .sdlc/config.json         provider, board, list IDs and settings — commit this
  .sdlc/.env                this project's Trello key and token — never commit
  .sdlc/.gitignore          keeps .env and the three below out of git
  .sdlc/state/              router bookkeeping (disposable)
  .sdlc/design-workspace/   /sdlc-kickoff's scratch folder for impeccable
  .sdlc/kickoff/            /sdlc-kickoff drafts and notes, saved every round
  knowledge-base/           the project's knowledge base — commit this
```

`init` writes `.sdlc/.gitignore` before it saves the credentials, adds any
entries an older one is missing, and keeps lines you added. `sdlc status`
warns if git would still commit `.sdlc/.env` — for instance because it was
committed before it was ignored.

### Project settings (`.sdlc/config.json`)

| Setting | Default | Meaning |
|---|---|---|
| `max_active_agents` | 1 | Stage agents running at the same time. Above 1, `/sdlc` runs them in the background in parallel (never two of the same stage) |
| `bounce_cap` | 3 | Bounces on one ticket before it escalates to Human |
| `max_dispatches_per_run` | 10 | Agent runs per `/sdlc` (override per run: `/sdlc 3`) |
| `stages` | `null` | Limit this project to certain stages, e.g. `["PO", "BA"]`, in dispatch order. `null` means every built stage, in pipeline order |
| `models` | `{}` | Model per stage for this project, e.g. `{"PO": "sonnet", "UIUX": "haiku"}`. Empty means each agent's own model (table below) |
| `knowledge_base` | `knowledge-base` | Knowledge base folder, relative to the project |
| `design_workspace` | `.sdlc/design-workspace` | Where `/sdlc-kickoff` runs impeccable |
| `chrome_path` | `null` | Chrome/Chromium binary for mockups; found on PATH when unset |

`sdlc status` shows the project, its settings and which knowledge base docs
are written. Every `sdlc` command finds the project by walking up from the
current folder, like git.

## Use it

Start Claude Code anywhere inside the project, then:

```
/sdlc-kickoff                         # once: product, architecture, design, technical patterns
/sdlc                                 # process ready tickets
/sdlc https://trello.com/c/k9e9Hxl5   # just this ticket, through every stage
/sdlc PO,BA,UIUX                      # only these stages this run
/sdlc PO 3                            # one stage, at most 3 agent runs
/loop 10m /sdlc                       # keep going while the session is open
```

**One ticket at a time.** Give `/sdlc` a card URL, short link or id and the
run works only that card, moving it stage by stage as far as it can go, and
ignores the rest of the board. It stops when the ticket reaches `Human`,
lands in a list no stage owns, or needs an agent that isn't built. Stage
names don't apply to a ticket run — the point is to move that one card — and
the dispatch limit defaults to 15, since crossing all eleven stages takes
eleven runs. On the command line it's `sdlc next --ticket <url|id>`.

Stage names ignore case, spaces, slashes and dashes, so `UIUX`, `ui/ux` and
`UI/UX` all work; a wrong name lists the valid ones, and a stage with no agent
built yet is reported rather than silently skipped. Cards in stages you leave
out simply wait.

**The order you list them in is the order they run.** `/sdlc UIUX,PO,BA` gives
the first agent run to UI/UX, the next to PO, then BA, then back to UI/UX, so
one busy stage doesn't drain every card before the others get a turn. Without
stage names, stages run in pipeline order (PO first), as before.

To limit a project permanently rather than per run, set `stages` in
`.sdlc/config.json`; listed order counts there too. On the command line it's
`sdlc next --only "PO,BA"`.

### Skipping a stage

A stage can be skipped — for one ticket, or for every ticket in the project.
No agent runs: the router moves the card straight to the next stage and says
so on the card, which costs nothing but the two calls that move and record it.

```
sdlc skip --ticket <url|id> --stages "UI/UX" --reason "backend-only change"
sdlc skip --project --stages "Code Analyst"      # every ticket, writes .sdlc/config.json
sdlc skip --ticket <url|id> --clear              # stop skipping (--stages to clear just some)
sdlc skip --show                                 # what's skipped right now
```

Consecutive skipped stages are passed in one go, each recorded separately:

```
[SKIP] ticket=#abc stages="Knowledge Base Writer" reason="KB already up to date"
[SKIPPED] agent="Knowledge Base Writer" ticket=#abc moved_to="Senior Developer" reason="..."
```

**Or mark it on the card itself.** `sdlc skip --ticket` is only a convenience
that writes the comment for you — you can type it into the Trello card and the
router picks it up on the next `sdlc next`:

```
[SKIP] stages="UI/UX, Code Analyst"     comment this on the card
[UNSKIP] stages="UI/UX"                 stop skipping that stage
[UNSKIP]                                stop skipping everything on this card
```

No `ticket=` needed: the card the comment sits on is the ticket. Stage names
are as loose as everywhere else (`uiux`, `code analyst` both work), and a name
that isn't a stage is logged and ignored rather than guessed at.

Because the record lives on the card, a per-ticket skip survives losing
`.sdlc/state/`. Project-wide skips live in `skip_stages` in
`.sdlc/config.json`, which you commit with the project.

**`skip_stages` is not `stages`.** A stage left out of `stages` still owns its
cards — they wait for a run that includes it. A stage in `skip_stages` never
runs at all, and cards pass straight through.

If a later stage **bounces a ticket back into a stage that ticket skips**, the
router escalates it to `Human` straight away rather than skipping it forward
into a loop: something the skipped stage was supposed to produce is actually
needed. Skipping `PO` is allowed but warned about — nothing creates the spec
or the feature folder, so every later stage escalates.

### Priority

When several cards are waiting for the same stage, the router takes the one
with the highest priority label — **P0**, then **P1**, then **P2**, then
cards with no label — and among equals the card nearest the **top of its
list**. So an unlabelled board just runs top-down, and dragging a card up is
enough to move it first.

`sdlc init` creates the three labels if the board doesn't have them. **You
apply them by hand**; no agent adds, changes or removes a card's labels. A
card carrying two priority labels counts as the highest of them.

Run one `/sdlc` at a time per project.

Agents never commit the **knowledge base** — review that diff and commit it
with the project. The **code** is different: from Senior Developer on, each
ticket's work is committed to its own `feature/<slug>` branch and pushed.
Nothing is merged into your development branch, and nothing is deployed; that
stays with you.

## How `/sdlc` works

```
/sdlc  (skill in the main Claude Code session)
  ├─ sdlc status / sdlc recover    → check the project; close out runs an interrupted session left
  ├─ sdlc next                     → {"action": "dispatch", "agent": "BA", "ticket_id": ...}
  ├─ subagent sdlc-ba              → reads the card and KB, does its stage's work, moves the card,
  │                                  posts [AGENT_DONE], [BOUNCE] or [ESCALATION: agent-stuck]
  ├─ sdlc finish                   → records the event; escalates to Human if there wasn't one
  └─ repeat: next returns dispatch (start another, up to max_active_agents), wait, or idle
```

| Stage | Agent | Reads | Writes | Next / bounces to |
|---|---|---|---|---|
| PO | `sdlc-po` | ticket, product docs | `definition.md`, `spec.md` (goal, priority, actors, use cases, acceptance criteria), **and a spec summary on the Trello card** | BA |
| BA | `sdlc-ba` | ticket, product docs, spec | findings in `decisions.md` only | UI/UX / PO |
| UI/UX | `sdlc-ui-ux` | spec, product docs, `ui-patterns`, `design-system`, **the project's code (read-only)** | `ux.md` plus HTML mockups rendered to desktop and mobile screenshots, **attached to the Trello card** | Solution Architect / PO |
| Solution Architect | `sdlc-solution-architect` | spec, `ux.md` and mockups, architecture and pattern docs, **the project's code (read-only)** | `technical.md`, `flow.md` | Knowledge Base Writer / PO or UI/UX |
| Knowledge Base Writer | `sdlc-kb-writer` | the feature's docs and `decisions.md`, every project doc | `product/`, `architecture/`, `patterns/`, `registry.json` — the proposals earlier stages left, recorded or refused | Senior Developer / Solution Architect or UI/UX |
| Senior Developer | `sdlc-senior-developer` | spec, `ux.md` and mockups, `technical.md`, `flow.md`, patterns, **the code** | **the product's code and its tests**, on `feature/<slug>`, committed and pushed | Code Analyst / Solution Architect, PO or UI/UX |
| Code Analyst | `sdlc-code-analyst` | the branch's diff in every repository, the code it reaches, spec, design, business rules, patterns (reads only; runs no tests) | findings in `decisions.md`, prioritized P0–P3; only P0 bounces (never edits code) | Test Scenario Writer / Senior Developer |
| Test Scenario Writer | `sdlc-test-scenario-writer` | spec, `flow.md`, `ux.md`, business rules, the code | `test-scenarios.md` — behaviour only, no automation code | Automated QA / PO or UI/UX |
| Automated QA | `sdlc-automated-qa` | `test-scenarios.md`, `patterns/testing`, the branch | **test code in the repo**, the suite run in Docker, per-scenario evidence | PO Tester / Senior Developer or Test Scenario Writer |
| PO Tester | `sdlc-po-tester` | spec, `ux.md` and mockups, QA evidence, **the running app** | a verdict and evidence per acceptance criterion | Deploy / Senior Developer or PO |
| Deploy | `sdlc-deploy` | the diff, architecture docs, the pushed branch | `deployment.md` (what's changing, rollback plan, approval request) | **Human** — it never deploys |

PO also keeps the card readable: it appends a summary block (purpose, actors,
priority, acceptance criteria, out of scope, and where the full spec lives)
below the requester's own text, which it never edits, and rewrites that block
whenever the spec changes. The knowledge base stays the source of truth.

Any stage can escalate to **Human**. Every stage appends to the feature's
`decisions.md` (append-only), which is how a bounced ticket carries its
findings back.

- **Routing is plain Python** (`orchestrator.py`, run as `sdlc next` /
  `finish` / `recover`), not model judgment. The main session only carries
  out what it returns, including which ticket runs next — priority label
  first, then position in the list. Commands hold a lock on the project's
  state.
- **Trello is the state machine.** Event comments on cards are the record of
  what happened; `.sdlc/state/` is disposable bookkeeping.
- **Tool scoping is enforced in code.** What an agent can change is set by the
  flags its MCP servers start with (`sdlc mcp kb ...`, `sdlc mcp trello ...`),
  not by prompts: `--allow` (feature docs it may write; only PO can create
  feature folders), `--append-decisions`, `--mockups` and `--attach-mockups`
  (UI/UX only), `--project-write` (Knowledge Base Writer only). A subagent's
  `tools:` list controls built-in tools (Read, Bash, ...) but doesn't hide its
  own MCP servers' tools, so every server tool that isn't gated by a flag is
  read-only. The design stages (BA through Solution Architect) only read code.
  The build stages get more: Senior Developer and Automated QA have Bash,
  `Write` and `Edit`; Code Analyst, PO Tester and Deploy have Bash but no way
  to change a file. No pipeline agent has web access, and none may edit the
  knowledge base directly — that only happens through their MCP tools.
- **The build stages work on a branch.** Each ticket gets `feature/<slug>` off
  the project's development branch (`development_branch` in
  `.sdlc/config.json`, or the first of `develop`, `development`, `main`,
  `master`). Commits are pushed; nothing is ever merged, tagged or deployed,
  and builds and tests run in the project's own Docker setup. Deployment is
  human-gated: the Deploy stage prepares the request and hands the card to
  **Human**.
- **Escalations are real.** A ticket bounced `bounce_cap` times moves to
  **Human** with `[ESCALATION: bounce-cap]`; a `[MISMATCH]` moves it there with
  `[ESCALATION: routing-mismatch]`; a run that ends without an event comment
  moves it there with `[ESCALATION: agent-stuck]`.
- **Agents know the product through the knowledge base.** PO escalates if
  `product/overview.md` is still a template; the Solution Architect escalates
  if the architecture docs are.

### Models and cost

Agents run per ticket, so the model each one uses is what the pipeline costs.
Each agent file sets its own:

| Agent | Model | Why |
|---|---|---|
| `sdlc-po` | opus | Turns a thin ticket into the spec everything downstream is built from |
| `sdlc-ba` | sonnet | Checks an existing spec against the product docs |
| `sdlc-ui-ux` | sonnet | Writes ux.md and static HTML mockups |
| `sdlc-solution-architect` | opus | Reads your code and designs against it |
| `sdlc-kb-writer` | sonnet | Judges which proposals belong in the shared docs and which need a person |
| `sdlc-senior-developer` | opus | Writes the product's code against the design |
| `sdlc-code-analyst` | opus | Finds loopholes, regressions and design drift the tests don't, before the code sets a precedent |
| `sdlc-test-scenario-writer` | sonnet | Turns acceptance criteria into checkable scenarios |
| `sdlc-automated-qa` | opus | Automates the scenarios and decides what a failure means |
| `sdlc-po-tester` | opus | Judges the built feature against what was actually asked for |
| `sdlc-deploy` | sonnet | Writes the release request and the rollback plan |
| `sdlc-kickoff-*` | opus | Run once per project, and everything else reads what they produce |

Override per project with `models` in `.sdlc/config.json` (stage names are
matched loosely, so `UIUX` works), or change an agent file to change it
everywhere. `sdlc status` shows the overrides in force.

Other things that move the bill: `max_dispatches_per_run` caps agent runs per
`/sdlc`; running fewer stages (`/sdlc PO,BA`) skips the rest; and mockup
screenshots are images, which cost more than text.

## How `/sdlc-kickoff` works

A conversation in your main Claude Code session. Subagents can't talk to you
directly, so the session acts as facilitator: it passes your answers to each
specialist and shows you their drafts and questions under the agent's name.
If the project isn't set up yet, it runs `sdlc init` with you first.

| Agent or skill | Does |
|---|---|
| `sdlc-kickoff-po` | Drafts `product/overview`, `users-and-personas`, `capabilities` |
| `sdlc-kickoff-ba` | Drafts `product/domain-glossary`, `business-rules`; reviews the PO drafts for gaps and contradictions |
| `sdlc-kickoff-architect` | Drafts `architecture/*` and the technical `patterns/*`; reads the code |
| `impeccable` skill | Run by the session itself, with you: works out the visual design system (`DESIGN.md`) and a style guide you approve from screenshots |
| `sdlc-kickoff-ui-ux` | Drafts `patterns/ui-patterns` (how the interface behaves) from the approved design system |
| `sdlc-kb-writer` | Records the drafts you approve, checks the singleton rule, copies the design system's assets |

The specialists are read-only. Nothing is written until you approve it, and
unknowns stay `TBD` instead of being guessed.

**Pause and resume.** A kickoff can take many rounds, so after each one the
session saves every draft and a note of what was decided and what's still open
to `.sdlc/kickoff/` (gitignored). Stop whenever you like, even by closing the
chat: run `/sdlc-kickoff` again and it lists the saved drafts and notes, and offers
to carry on from them or start that area again. Drafts are cleared as each doc
is recorded in the knowledge base. Inspect or manage them yourself with
`sdlc draft list`, `sdlc draft show <section>/<name>` and `sdlc draft clear`.
To move an unfinished kickoff to another machine, commit `.sdlc/kickoff/` or
copy it across.

**Design step.** impeccable works in the project's design workspace. It
writes `PRODUCT.md` (from the approved product docs), then `DESIGN.md` and its
`.impeccable/design.json` token sidecar: scanned from your code if the product
has a UI, or worked out with you if it doesn't. A `style-guide.html` is
rendered to screenshots (`sdlc render`) for your approval. Your code is never
written. Once you approve, `sdlc-kb-writer` records `DESIGN.md` as
`patterns/design-system.md` and copies the sidecar, style guide and
screenshots to `patterns/design-system/`, where the UI/UX stage uses them for
mockups that look like your product.

## Test the flow up to Solution Architect

In a project set up with `sdlc init`, run `/sdlc-kickoff` first: the product area
for PO, BA and UI/UX, the architecture area for the Solution Architect, and the
design area so UI/UX mockups follow your design system.

1. **Clear ticket.** Create a card on **PO** with a clear, small request and run
   `/sdlc`. Check that:
   - the card ends in **Knowledge Base Writer** with one `[AGENT_DONE]` comment
     per stage
   - `knowledge-base/features/{slug}/` has `definition.md`, `spec.md`, `ux.md`,
     `technical.md` and `flow.md` filled in, and `decisions.md` has entries
   - `mockups/` has HTML mockups with `-desktop.png` and `-mobile.png`
     screenshots, listed in `ux.md`, and the PNGs are attached to the card
   - `technical.md` cites code paths if the project has code
2. **Bounce.** Create a card whose request has an untestable goal (e.g. "make
   exports fast"). BA should bounce it to PO with findings in `decisions.md`;
   after `bounce_cap` bounces it lands in **Human** with
   `[ESCALATION: bounce-cap]`.
3. **Escalation.** Create a deliberately vague card on **PO**. It should go to
   **Human** with `[ESCALATION: agent-stuck]` and no docs written.
4. **Parallel.** Set `max_active_agents` to 2 in `.sdlc/config.json`, put cards
   on **PO** and **BA**, and run `/sdlc`: both stages should run at once.

To run one stage by hand: `@"sdlc-ba (agent)" ticket_id: <card id>`, then
`sdlc finish --agent BA --ticket <card id>`.

## Files

| File | Purpose |
|---|---|
| `sdlc.py` | The `sdlc` command: `init`, `status`, `next` (`--only`, `--ticket`)/`finish`/`recover`, `skip`, `render`, `draft`, `mcp kb`/`mcp trello` |
| `install.py` | Installs the command, agents, skills and permissions for your user (credentials are per project) |
| `config.py` | Engine constants (stage sequence, `AGENT_SUBAGENTS`, comment prefixes, project setting defaults) and project discovery/loading |
| `orchestrator.py` | Router: comment processing, dispatch choice (priority label, then list position), single-ticket runs, wait/recover, bounce-cap / mismatch / agent-stuck escalation |
| `state_store.py` | Per-project idle/busy, bounce-count and per-ticket skip tracking, with a lock |
| `comment_parser.py` | Parses `[AGENT_DONE]` / `[BOUNCE]` / `[MISMATCH]` / `[ESCALATION: ...]` / `[SKIP]` / `[UNSKIP]` / `[SKIPPED]` |
| `trello_client.py` | Thin REST wrapper; credentials go in a header so errors don't expose them |
| `knowledge_base.py` | Bootstraps a project's knowledge base from `kb_template/`; lists project doc status |
| `mcp_servers/kb_server.py` | Scoped KB tools: everyone reads; feature writes per role (`--allow`); `append_decision` with `--append-decisions`; `save_mockup` with `--mockups`; project writes and design asset import only with `--project-write` |
| `mcp_servers/trello_server.py` | Scoped Trello tools (`get_ticket`, `post_ticket_event`, `advance_ticket`; `attach_mockup` with `--attach-mockups`) |
| `mockup_render.py` | Renders a static HTML page to desktop and mobile PNGs with headless Chrome, with scripts and network blocked |
| `claude/skills/sdlc/`, `claude/skills/kickoff/` | `/sdlc` dispatch loop and `/sdlc-kickoff` session |
| `claude/agents/sdlc-*.md` | Pipeline stage agents: tools, MCP servers, steps, DoD, outcomes |
| `claude/agents/sdlc-kickoff-*.md` | `/sdlc-kickoff` specialists (read-only) and the kickoff Knowledge Base Writer |
| `claude/skills/sdlc-po-role/`, `sdlc-ba-role/`, `sdlc-ui-ux-role/`, `sdlc-solution-architect-role/`, `sdlc-kb-writer-role/`, `sdlc-developer-role/`, `sdlc-qa-role/` | Each role's judgment and quality bar, preloaded into every agent of that role. Edit a role here, not in the agent files |
| `claude/skills/sdlc-stage-rules/` | Rules every pipeline stage preloads: list check, context loading, advance/bounce/escalate, event comment format, decision log |
| `claude/skills/sdlc-code-workflow/` | Rules the build stages preload: where the code is, Docker, the per-ticket branch, commits, pushes, and what's never touched |
| `claude/skills/kb-rules/` | Knowledge base rules every agent preloads. Its ownership table mirrors `kb_template/README.md`; change both together |
| `kb_template/` | Knowledge base skeleton copied into each new project |

## Changing a stage, or adding one

All eleven stages are built. This is the recipe if you split a stage, add one
to `AGENT_SEQUENCE` (it needs a Trello list with the same name), or rebuild
one from scratch.

1. Copy the closest stage agent (e.g. `claude/agents/sdlc-ui-ux.md`) to
   `claude/agents/sdlc-{role}.md`. Change `name`, `description`, the body
   (steps, DoD, outcomes and their comment lines), and `skills:` (keep
   `sdlc-kb-rules` and `sdlc-stage-rules`, swap in the role's skill). If the role has
   no skill yet, create `claude/skills/{role}-role/SKILL.md` with
   `user-invocable: false`, holding the role's judgment and quality bar; keep
   the job (tools, steps, outcomes) in the agent file.
2. Name its KB server `sdlc-kb-{role}`, started with `command: sdlc` and
   `args: ["mcp", "kb", "--role", ..., "--allow", ..., "--append-decisions"]`
   (see "Who writes what" in `kb_template/README.md`). Update the
   `mcp__sdlc-kb-...__*` names in `tools:` to match.
3. Add `"mcp__sdlc-kb-{role}"` to `PERMISSIONS` in `install.py`.
4. Add one line to `AGENT_SUBAGENTS` in `config.py`.
5. A stage that touches code also preloads `sdlc-code-workflow` and needs
   `Bash` in `tools:`; give it `Write`/`Edit` only if it's meant to change
   files. Keep `Write`/`Edit` away from the reviewing stages — that
   separation is what makes a review a review.
6. Rerun `python3 install.py` and restart Claude Code.

Agent names with spaces must be quoted in event comments
(`agent="Solution Architect"`); the router warns about names it doesn't
recognize.
