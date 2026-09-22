---
name: sdlc-code-workflow
description: How SDLC pipeline stages touch the product's code: finding it, running every command through the project's Docker setup, the per-ticket branch, commits and pushes, and what is never touched. Preloaded into sdlc-senior-developer, sdlc-automated-qa, sdlc-po-tester and sdlc-deploy; not for direct use.
user-invocable: false
---

# Code workflow

The stages from Senior Developer onward work in the product's code
repository, not just the knowledge base. These rules apply to all of them, so
a ticket's branch looks the same whichever stage touched it last.

## 1. Where the code is
`architecture/tech-stack.md` names every platform and its code location.
Those paths are relative to the project root — your working directory — unless
the doc gives an absolute path or another repository.

Read that doc before assuming a layout. Don't guess a package manager, a test
runner or a folder name that isn't in it.

## 2. Run everything in the project's Docker setup
The project runs on Docker (`architecture/tech-stack.md` says where the
Compose files live, usually `infra/`). Every command that needs a language
runtime, a database or a browser goes through Compose:

```
docker compose -f <compose file> run --rm <service> <command>
docker compose -f <compose file> exec <service> <command>
docker compose -f <compose file> up -d <service>     # e.g. postgres for integration tests
```

- Never install a runtime, a package manager or a system package on the host.
- Never run a database, migration or test against anything but the project's
  own containers.
- Bring up only the services you need, and leave the stack as you found it:
  stop what you started (`down` for a stack you brought up yourself).
- If the Compose setup doesn't exist yet and the architecture docs call for
  it, creating it is part of the first ticket that needs it — build it to
  `architecture/tech-stack.md`, not from memory.

Host `git` is fine, and so is anything that only reads files.

## 3. The branch
One branch per ticket.

If the project isn't a git repository yet, stop and escalate — say that
`git init` and the first commit are needed, and whether a remote should
exist. Creating the repository, choosing its remote and deciding what the
first commit contains are a person's call, not something to do mid-ticket.

- **Base:** the project's development branch. `sdlc status` prints
  `development_branch`; when it's `None`, use the first of `develop`,
  `development`, `main`, `master` that exists. Fetch and pull the base before
  branching so the work starts from the latest commit.
- **Name:** `feature/<feature-slug>`, the slug from `find_feature`.
- If the branch already exists (the ticket came back from a later stage),
  check it out and keep working on it. Never start a second branch for the
  same ticket.

Never commit to the base branch. Never merge, rebase, cherry-pick, force-push,
reset another stage's commits, delete a branch, or open a pull request. A
person integrates the branch.

## 4. Commits
Commit the work of your stage before you advance the ticket.

- Stage only files this ticket needs. Never `git add -A` over a tree you
  haven't looked at.
- Never commit secrets or generated output: `.env` files, `.sdlc/.env`, keys,
  credentials, `node_modules`, build artifacts, coverage reports, database
  dumps.
- Message: an imperative subject under ~70 characters, then a body saying what
  changed and why, then trailers:

```
Add website custom pages endpoint

Implements the dashboard endpoint from technical.md, with the account
isolation check from patterns/auth-patterns.md.

Ticket: #<ticket_id>
Feature: <feature-slug>
Stage: <your stage>
Co-Authored-By: Claude <noreply@anthropic.com>
```

## 5. Pushing
Push the ticket's branch to `origin` when your stage's commits are in
(`git push -u origin feature/<slug>` the first time). Push nothing else: not
the base branch, not tags, not another branch.

If the push fails, don't retry blindly:
- **No remote, or authentication refused:** record it with `append_decision`,
  say so in your report, and carry on — the work is committed locally.
- **Rejected because the remote branch moved:** stop and escalate. Someone
  else has the branch; never force it.

## 6. Never
- Read or print secrets: `.env` files, `.sdlc/.env`, key or credential files.
  Pass configuration through the Compose environment instead.
- Touch production: real customer data, live databases, deploy commands or
  hosting providers. Deployment is human-gated.
- Edit the knowledge base with `Write` or `Edit`. Its files are only ever
  changed through your knowledge base tools.
- Change another stage's docs, or rewrite history on a branch.

## 7. Report what actually happened
- Quote real command output for every check you claim to have run. Never say a
  check passed if you didn't run it, and never call a failure a pass.
- "Not run" and "passed" are different results; say which one you mean, and
  why a check couldn't run.
- If the working tree was already dirty with changes that aren't yours, don't
  discard them: escalate and say what was there.
