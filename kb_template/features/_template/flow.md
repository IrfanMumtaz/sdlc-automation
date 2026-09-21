<!--
OWNER: Solution Architect
PURPOSE: End-to-end system flow — the connected sequence from trigger to
         result. Different from ux.md (user-visible only) and technical.md
         (contracts/data only) — this is the full lifecycle across components.
DOD:
  - Every acceptance criterion in spec.md is traceable to a step here
  - No gap between "user does X" and "system does Y" — every hop shown
  - Decision points/branches called out explicitly
-->

# Flow: {feature-name}

## Trigger
{what starts this flow}

## Steps
1. {actor/component} → {action} → {result}
2. {actor/component} → {action} → {result}

## Decision points
- {condition}: {branch A} vs {branch B}

## Result
{end state once flow completes}
