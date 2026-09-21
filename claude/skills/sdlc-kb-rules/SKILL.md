---
name: sdlc-kb-rules
description: Rules of the project knowledge base (layout, who writes what, singleton rule, no invented facts) shared by every SDLC pipeline and kickoff agent. Preloaded into those agents; not for direct use.
user-invocable: false
---

# Knowledge base rules

Every agent in the pipeline works from one shared knowledge base: what the
product is, how it's built, the conventions it follows, and one folder per
feature. It lives inside the project (its path is in `.sdlc/config.json`),
and people review and commit its changes with the project; agents never
commit. Later agents treat what's in it as fact, so these rules apply to
every role.

## Layout
- `product/`: overview, users-and-personas, capabilities, domain-glossary, business-rules
- `architecture/`: system-overview, service-boundaries, data-model, tech-stack
- `patterns/`: one convention topic per file (api-conventions, error-handling,
  ui-patterns, ...). `design-system.md` is the visual design system in
  DESIGN.md format, with its token extensions, style guide and screenshots in
  `patterns/design-system/`
- `features/{slug}/mockups/`: the UI/UX stage's HTML mockups and their screenshots
- `features/{slug}/`: the 8 docs for one ticket
- `registry.json`: index of all of the above; project docs are marked `template` or `written`

## Who writes what
| Path | Writer |
|---|---|
| `features/{slug}/definition.md`, `spec.md` | PO |
| `features/{slug}/ux.md` | UI/UX |
| `features/{slug}/technical.md`, `flow.md` | Solution Architect |
| `features/{slug}/test-scenarios.md` | Test Scenario Writer |
| `features/{slug}/decisions.md` | any agent, append-only |
| `features/{slug}/deployment.md` | Deploy |
| `product/`, `architecture/`, `patterns/`, `registry.json` | Knowledge Base Writer only; other roles supply the content |

Your tools enforce this. If the write you'd need isn't among your tools, the
doc isn't yours: propose the change instead of working around it.

## The singleton rule
A fact lives in exactly one doc. Every other doc refers to it instead of
restating it, e.g. "See `product/business-rules.md`, Refunds". Restated facts
drift apart, and every agent ends up loading them twice.

## Facts, not guesses
- Write only what a source supports: the ticket, the person, their documents,
  the code, or another doc in the knowledge base.
- Never fill a gap with something plausible. Later agents build on it as fact.
- Keep what you inferred apart from what was stated.
- What to do with an unknown depends on your job (kickoff agents mark it
  `TBD` and ask; pipeline agents escalate). Your agent instructions say which.

## Templates
Each doc starts with an HTML comment giving its owner, purpose and Definition
of Done. Keep the comment and the headings, and treat the DoD as the bar the
doc must meet.

## Written for agents
These docs are loaded into agents' context on every ticket. Keep them
concise: short sentences, lists and tables, no preamble.

## Terms and personas
Use terms exactly as defined in `product/domain-glossary.md` and personas
exactly as named in `product/users-and-personas.md`. If you need a term or
persona that isn't there, flag it instead of defining it yourself.
