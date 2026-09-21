<!--
OWNER: Deploy
PURPOSE: Rollback plan and deployment summary. V1 is human-gated — this file
         is what the human approval request is based on.
DOD:
  - Deployment plan/summary present before human approval is requested
  - Rollback plan explicit, not "N/A"
  - Deployment reference (commit/release ID) filled in only after execution
-->

# Deployment: {feature-name}

## What's changing
{summary}

## Rollback plan
{explicit steps to revert if something goes wrong}

## Human approval
- **Requested:** {date}
- **Approved by:** {name}
- **Approved:** {date}

## Deployment reference
{commit/release ID — filled in after execution}
