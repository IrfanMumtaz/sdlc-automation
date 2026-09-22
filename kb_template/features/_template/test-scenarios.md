<!--
OWNER: Test Scenario Writer
PURPOSE: What "correct" means, behaviorally, at every test level. Scenario
         intent only — no automation code (that's Automated QA's job, in the
         product's repository, not this file).
DOD:
  - Every acceptance criterion in spec.md is in the coverage table, with the
    scenario IDs that cover it
  - Every level has scenarios, or says N/A with the reason
  - Negative/error-path and boundary scenarios included, not just happy path
  - Written as given/when/then or input -> expected-output, no ambiguity
  - IDs (FLD-, UNIT-, INT-, SYS-, E2E-, UAT-) are never renumbered once written
-->

# Test Scenarios: {feature-name}

## Coverage
| Acceptance criterion | Scenarios |
|---|---|
| AC-1: {short name} | {FLD-01–FLD-08, UNIT-01, INT-01, E2E-01, UAT-01} |

## Field-level
### {Field name} ({form field / API field / both})
Rules: {required, type, length, format, allowed values, default} ({source})

| ID | Case | Input | Expected |
|---|---|---|---|
| FLD-01 | {empty} | {""} | {rejected: "{exact message}" ({code})} |
| FLD-02 | {at maximum length} | {value} | {accepted, stored as {value}} |

## Unit
### UNIT-01: {name} (AC-{n})
- **Unit:** {function, class or component, as the code names it}
- **Given:** {precondition}
- **When:** {call or input}
- **Then:** {returned value, raised error or state}

## Integration
### INT-01: {name} (AC-{n})
- **Given:** {precondition, data in the database, fake service's response}
- **When:** {action}
- **Then:** {what's stored, emitted or rolled back}

## System
### SYS-01: {name} (AC-{n})
- **Given:** {role, account, state of the running system}
- **When:** {request through the public interface}
- **Then:** {response, status and resulting state}

## End-to-end
### E2E-01: {journey} (AC-{n})
- **Persona:** {who}
- **Steps:** {1. ... 2. ... 3. ...}
- **Then:** {what the user sees and what's true at the end}

## UAT
### UAT-01: {business outcome, in the user's words} (AC-{n})
- **Persona:** {who}
- **Scenario:** {what they set out to do, in their language}
- **Accept when:** {the observable outcome that satisfies them}
- **Run:** {automated / manual — what the person should look at}
