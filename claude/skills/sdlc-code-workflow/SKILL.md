---
name: sdlc-code-workflow
description: How SDLC pipeline stages touch the product's code: finding it, running every command through the project's Docker setup, the per-ticket branch, commits and pushes, and what is never touched. Preloaded into sdlc-senior-developer, sdlc-automated-qa, sdlc-po-tester and sdlc-deploy; not for direct use.
user-invocable: false
---

# Code workflow

The stages from Senior Developer onward work in the product's code
repository, not just the knowledge base. These rules apply to all of them, so
a ticket's branch looks the same whichever stage touched it last.

## 1. Where the code is: your ticket's workspace
Other agents are working other tickets at the same time, each on its own
branch. So every ticket has its own workspace, and your prompt names it:

- `worktree`: the ticket's workspace. It mirrors the project folder, with a
  git worktree of each repository in the same place it has in the project.
  For microservices in separate repositories under one parent folder, that's
  one folder per service, all on the ticket's branch.
- `repos`: every repository in the workspace, its path and its development
  branch (`base`). Repositories this ticket doesn't change sit exactly at
  their base, so the services run together the way they would after merge.
- `project_dir`: the project folder inside the workspace.
- `branch`: the ticket's branch, the same name in every repository.
- `compose_project`: the Docker Compose project name for this ticket.

Work only there. Your session's working directory is the project's own
checkout, which belongs to the person, not to your ticket: never read code
from it, change it, or switch its branch.
- File tools (`Read`, `Write`, `Edit`, `Glob`, `Grep`): absolute paths under
  `worktree`.
- Shell: start every command with `cd <path> && `, where `<path>` is the
  repository the command is for (or `project_dir` for project-wide
  commands), so it can't run in the wrong checkout whatever the shell's last
  directory was. Run `sdlc` commands without the `cd`.
- Files in the workspace that are links (a shared `docker-compose.yml` in a
  parent folder that isn't a repository) have no branch: every ticket sees
  the same file. Use them, but never change them. If one needs changing,
  escalate.

`architecture/tech-stack.md` names every platform and its code location.
Those paths are relative to `project_dir` unless the doc gives an absolute
path. A repository that isn't in `repos` has no ticket worktree: escalate
before changing it, rather than switching the branch under whoever else is
using it.

Read that doc before assuming a layout. Don't guess a package manager, a test
runner or a folder name that isn't in it.

## 2. Run everything in the project's Docker setup
The project runs on Docker (`architecture/tech-stack.md` says where the
Compose files live, usually `infra/`). Every command that needs a language
runtime, a database or a browser goes through Compose:

```
cd <project_dir> && docker compose -p <compose_project> -f <compose file> run --rm <service> <command>
cd <project_dir> && docker compose -p <compose_project> -f <compose file> exec <service> <command>
cd <project_dir> && docker compose -p <compose_project> -f <compose file> up -d <service>   # e.g. postgres
```

Always pass `-p <compose_project>`. Without it every worktree's stack gets the
same default name, and a stage testing one ticket would stop or reuse the
containers another ticket is running on. If two stacks can't run side by side
because the Compose file publishes fixed host ports, don't edit the ports:
say so in your report (`append_decision` too) and escalate if it stops you.

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
One branch per ticket, and the router owns it. Before you start, it created
the branch from the latest development branch (or reused it, if an earlier
stage made it), checked it out in the ticket's worktree, pulled what
earlier stages pushed, and merged in the latest development branch. When you
finish, it commits your knowledge base
changes on it and pushes it.

- Check before working, in every repository you'll touch:
  `cd <path> && git status --short --branch` shows `branch` and a clean tree.
  If it's on another branch, or dirty with changes that aren't yours,
  escalate and say what was there.
- Each repository's base is its `base` in `repos`. Diff against
  `origin/<base>` when it exists.
- Change only the repositories the design calls for (`technical.md` names
  the services). If the work needs a service the design didn't mention, say
  why in `decisions.md` and bounce to the Solution Architect.
- Never `checkout`, `switch`, create or delete a branch or a worktree, and
  never pull: the router already brought the branch up to date.

Never commit to the base branch. Never merge, rebase, cherry-pick, force-push,
reset another stage's commits, delete a branch, or open a pull request. A
person integrates the branch.

The one exception is the Deploy stage, and only as its own instructions say:
its `merge_into_release` tool merges the ticket's branch into the ticket's
release branch (`release/<version>`) and pushes it, in a release workspace
under `.sdlc/worktrees/release-<version>/`, and Deploy opens or updates the
release's pull request into the development branch from there. Nobody in the
pipeline merges into the development branch or merges a pull request.

## 4. Commits
Commit the work of your stage before you advance the ticket, in each
repository you changed, and only in those.

- Stage only files this ticket needs. Never `git add -A` over a tree you
  haven't looked at.
- Leave the knowledge base out: your knowledge base tools change it, and the
  router commits those changes after your run.
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
Push the ticket's branch to `origin` in each repository you committed to
(`cd <path> && git push -u origin <branch>`). Push nothing else: not the base
branch, not tags, not another branch, and not the branch in a repository you
didn't change.

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
