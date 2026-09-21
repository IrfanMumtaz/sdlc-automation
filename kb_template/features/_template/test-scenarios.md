<!--
OWNER: Test Scenario Writer
PURPOSE: What "correct" means, behaviorally. Scenario intent only — no
         automation code (that's Automated QA's job, in a separate execution
         artifact, not this file).
DOD:
  - Every acceptance criterion in spec.md has at least one scenario here
  - Negative/error-path scenarios included, not just happy path
  - Written as given/when/then or input -> expected-output, no ambiguity
-->

# Test Scenarios: {feature-name}

## Scenario: {name}
- **Given:** {precondition}
- **When:** {action}
- **Then:** {expected result}

## Scenario: {negative case name}
- **Given:** {precondition}
- **When:** {invalid/edge action}
- **Then:** {expected error/handling}
