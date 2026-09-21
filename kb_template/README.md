# Knowledge Base

This is the single source of truth every pipeline agent reads from and writes
to. It lives in this repo — versioned, diffable, reviewable via PR like code —
not in an external wiki or tool.

## Structure

```
/knowledge-base
  registry.json          <- router: ticket/feature -> exact file paths + tags
  /product/               <- what the product is: overview, personas, capabilities,
                             glossary, business rules (singleton)
  /features/{slug}/       <- one folder per feature/ticket (8 fixed documents)
  /patterns/              <- reusable conventions, ONE file per topic (singleton);
                             design-system.md holds the visual design system, with its
                             tokens, style guide and screenshots in /patterns/design-system/
  /architecture/          <- system-level facts, ONE file per topic (singleton)
```

## Initial project knowledge

A new knowledge base starts as templates. Run `/sdlc-kickoff` in Claude Code to fill
`/product/`, `/architecture/` and `/patterns/` in a working session with PO, BA,
Solution Architect and UI/UX agents (the design system with impeccable); the Knowledge Base Writer records what you
approve. `registry.json` marks each project doc `template` or `written`.

## The singleton rule

A fact lives in exactly one file. Feature docs **link to** product, pattern and
architecture docs — they never restate the content. If two features need the
same convention, both link to the same `/patterns/*.md` file.

This exists to control LLM token usage: an agent loads only the exact files
`registry.json` points it to, not a folder scan or a full-repo dump. Keeping
facts singleton means an agent's context pull stays small and never contains
duplicated information.

## Who writes what

| Path | Writer | Rule |
|---|---|---|
| `/features/{slug}/definition.md`, `spec.md` | PO | — |
| `/features/{slug}/ux.md` | UI/UX | — |
| `/features/{slug}/technical.md`, `flow.md` | Solution Architect | — |
| `/features/{slug}/test-scenarios.md` | Test Scenario Writer | — |
| `/features/{slug}/decisions.md` | any agent, append-only | never overwrite prior entries |
| `/features/{slug}/deployment.md` | Deploy | — |
| `/product/*.md`, `/patterns/*.md`, `/architecture/*.md`, `registry.json` | **Knowledge Base Writer only** | every other agent may propose, never write directly; `/product/` content comes from PO and BA, `/architecture/` from Solution Architect, `ui-patterns.md` and `design-system.md` from UI/UX and the design session |

## Adding a new feature

Don't create feature folders by hand. The PO agent creates one per ticket with
its `get_or_create_feature` tool, which copies `/features/_template/` into
`/features/{slug}/` and adds the matching `registry.json` entry, so the two
never drift apart.

## Before creating a new pattern

The Knowledge Base Writer agent must search existing `/patterns/` and
`/architecture/` files first. A new pattern file is only justified if nothing
existing covers it — otherwise link to what's there.
