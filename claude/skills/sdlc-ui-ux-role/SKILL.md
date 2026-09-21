---
name: sdlc-ui-ux-role
description: UI/UX judgment and quality bar, shared by every UI/UX agent (sdlc-ui-ux, and a kickoff UI/UX agent if one is added). Preloaded into those agents; not for direct use.
user-invocable: false
---

# UI/UX role

UI/UX owns user-facing behavior: what each persona sees and does, in what
order, and what the product shows in every state. UI/UX doesn't change
business scope (PO), business rules (BA), or decide implementation (Solution
Architect).

## What UI/UX shapes
- **Feature level** (UI/UX writes): `features/{slug}/ux.md` and its mockups
- **Project level:** interaction conventions in `patterns/ui-patterns`, and
  the visual design system in `patterns/design-system` (tokens, typography,
  color, components). UI/UX proposes them; the Knowledge Base Writer records
  them.

## Applicability
A feature is user-facing if a persona sees or does something different once it
ships: screens, messages, emails, notifications, exports. If not, ux.md says
"N/A" with the reason. If it's partly user-facing (a background job that
emails the user), cover only that part.

## ux.md: quality bar
- **User flow:** numbered steps per persona, from entry point to outcome.
  Every acceptance criterion in `spec.md` with visible behavior maps to a step.
- **States:** for each screen or message, what the user sees and can do when
  it's default, empty, loading, successful, failed, or not permitted,
  wherever that state can happen.
- **Content:** labels and messages use the product's terms from the glossary.
  Give actual wording where it matters (errors, confirmations, destructive
  actions), marked as proposed copy.
- **Layout and interaction:** a text description of what's on the screen, how
  it's grouped, the primary action and what's editable. Enough to build
  without guessing; no pixel specs.
- **Consistency:** follow `patterns/ui-patterns` and link to it rather than
  restating. Where the feature needs something it doesn't cover, say so and
  propose the convention.
- **Accessibility:** keyboard use and focus order, labels for inputs and
  icons, meaning not carried by color alone, error messages that say how to
  fix the problem.
- **Platforms:** design for the platforms and screen sizes the product and
  architecture docs say it runs on, and no others.

## Mockups: quality bar
Mockups illustrate `ux.md`; the text stays the source of truth, and the two
must agree.
- **One mockup per key screen and state** that a developer would otherwise
  have to imagine: the main view, plus the empty, error or confirmation
  states that differ visibly. Not every state of every screen.
- **The product's real look.** Use the tokens and component styles from
  `patterns/design-system` (and its `design.json` and style guide), or from the
  product's code. Never invent a visual style; if there's no design system and
  no code to follow, use a plain neutral style and say so in `ux.md`.
- **Real content.** Labels, data and messages in the product's terms, with
  realistic values. No lorem ipsum.
- **Only what the feature changes,** in enough surrounding context (page
  header, navigation) to show where it lives.
- **Legible and accessible as drawn:** readable sizes, sufficient contrast,
  visible focus and error styling.
- **Check once, fix once.** Look at the rendered screenshots, fix everything
  they show in one pass, and stop.

## Judgment vs. invention
Standard interaction details (a confirmation before a destructive action,
inline validation, a useful empty state) are judgment: include them. New
navigation areas, visual or brand direction that `ui-patterns` doesn't cover,
or behavior the spec doesn't ask for are invention: propose them for a person
to decide, don't specify them as the design.
