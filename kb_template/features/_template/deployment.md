<!--
OWNER: Deploy
PURPOSE: Rollback plan and deployment summary. V1 is human-gated — this file
         is what the human approval request is based on.
DOD:
  - Deployment plan/summary present before human approval is requested
  - Release version, merge commit and pull request recorded for every
    repository the ticket changed
  - Rollback plan explicit, not "N/A"
  - Deployment reference (commit/release ID) filled in only after execution
-->

# Deployment: {feature-name}

## What's changing
{summary}

## Release
- **Version:** {release version, from the card's [RELEASE] comment}
- **Per repository:** {release/<version> branch, merge commit, pull request link}
- **Release order:** {when more than one service changes; otherwise "single service"}

## Rollback plan
{explicit steps to revert if something goes wrong}

## Human approval
- **Requested:** {date}
- **Approved by:** {name}
- **Approved:** {date}

## Deployment reference
{commit/release ID — filled in after execution}
