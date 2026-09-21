<!--
OWNER: UI/UX
PURPOSE: User-facing behavior only — what the user sees and does. Not the
         system-level flow (see flow.md) and not the API/data contracts
         (see technical.md).
DOD:
  - Applicability explicitly stated, even if "N/A: backend/config only"
  - If applicable: user flow / interaction sequence defined
  - If applicable: states, layout and interaction described in text
  - If applicable: a mockup for each key screen and state, in mockups/, listed below
  - Accessibility/responsive notes if relevant
  - Checked against /patterns/ui-patterns.md and /patterns/design-system.md
    for consistency — link, don't restate
  - This text is the source of truth; mockups illustrate it
-->

# UX: {feature-name}

## Applicability
{Yes — user-facing | N/A: backend/config only, reason: ...}

## User flow
1. {step}
2. {step}

## States
- **{screen or message} — {state}:** {what the user sees and can do}

## Layout / interaction notes
{text description of each screen: content, grouping, primary action, what's editable}

## Mockups
- `mockups/{name}.html` ({screen and state}): `{name}-desktop.png`, `{name}-mobile.png`

## Accessibility and responsive notes
{keyboard and focus, labels, contrast, how layouts adapt}

## Patterns referenced
- [patterns/ui-patterns.md#{anchor}](../../patterns/ui-patterns.md)
- [patterns/design-system.md#{anchor}](../../patterns/design-system.md)
