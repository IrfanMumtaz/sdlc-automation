"""
One workspace per ticket, so agents working different tickets at the same
time never share a checkout — across every git repository the project has.

A project is one repository (the project folder is inside it), or a parent
folder that isn't a repository itself and holds one repository per service,
with the knowledge base in one of them or in its own:

    parent/                      .sdlc/ lives here
      knowledge-base/   (repo)
      orders-service/   (repo)
      payments-service/ (repo)
      docker-compose.yml         not in any repository

Every ticket gets one branch name, and a workspace folder under
<project>/.sdlc/worktrees/ that mirrors that layout, holding a git worktree of
each repository on that branch:

    .sdlc/worktrees/42-checkout/
      knowledge-base/    worktree, feature/42-checkout
      orders-service/    worktree, feature/42-checkout
      payments-service/  worktree, feature/42-checkout
      docker-compose.yml symlink to the shared file (it has no branch)

Relative paths between repositories (a Compose file building ../orders-service)
therefore resolve to the ticket's own copies. Stages that only write docs get
the knowledge base's repository; stages that read or change code get every
repository, so untouched services sit at their development branch and
integration runs the real combination.

The router prepares the workspace before each dispatch — creating worktrees,
or fast-forwarding them to what earlier stages pushed — and after each run
commits the stage's knowledge base changes and pushes every repository whose
branch has work. Agents only ever work inside the workspace; the project's own
checkouts never change branch.

The branch name, and the repositories it has been pushed to, are recorded on
the card as [BRANCH] comments, so the mapping survives losing .sdlc/state/ and
is the same on every machine.

Two kinds of failure:
  ProjectGitProblem  nothing can run until a person fixes the repositories (the
                     knowledge base isn't in one, no development branch, the
                     knowledge base not committed on it). `sdlc next` exits.
  TicketGitProblem   only this ticket is stuck (its branch diverged from the
                     pushed one, say). The router escalates the card.
"""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import config

BRANCH_PREFIX = "feature/"
BASE_CANDIDATES = ("develop", "development", "main", "master")
MAX_TITLE_SLUG = 40
# Stages that only work through the knowledge base tools. Every other stage
# reads or changes code, and gets every repository in its workspace.
DOC_ONLY_STAGES = {"PO", "BA", "UI/UX", "Knowledge Base Writer"}
# Folders in a parent project that are never repositories to mirror.
SKIP_CHILDREN = {config.PROJECT_DIR_NAME, ".git", "node_modules"}


class ProjectGitProblem(Exception):
    pass


class TicketGitProblem(Exception):
    pass


@dataclass(frozen=True)
class Repo:
    source: Path   # the project's own checkout
    rel: Path      # where it sits relative to the anchor; Path(".") for the anchor itself

    @property
    def name(self):
        return self.rel.as_posix() if self.rel != Path(".") else self.source.name

    def worktree(self, workspace):
        return Path(workspace) / self.rel


def _git(*args, cwd, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, ["git", *args], result.stdout, result.stderr)
    return result


def _ok(*args, cwd):
    return _git(*args, cwd=cwd, check=False).returncode == 0


def _error_text(exc):
    return " ".join((exc.stderr or exc.stdout or str(exc)).split())[:300]


def _toplevel(path):
    result = _git("rev-parse", "--show-toplevel", cwd=path, check=False)
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def anchor():
    """The folder a workspace mirrors: the project's repository, or the project folder when it isn't one."""
    return _toplevel(config.PROJECT_ROOT) or config.PROJECT_ROOT.resolve()


def repo_settings(repo):
    """Per-repository settings from `repositories` in .sdlc/config.json, keyed by path."""
    return (config.PROJECT_SETTINGS.get("repositories") or {}).get(repo.name, {}) or {}


def repositories():
    """
    Every repository the project has, anchor first: the project's own
    repository if it's in one, each folder directly inside the project that is
    its own repository, any path listed under the `repositories` setting, and
    the knowledge base's repository.
    """
    root, base = config.PROJECT_ROOT.resolve(), anchor()
    candidates = [root]
    candidates += sorted(c for c in root.iterdir()
                         if c.is_dir() and c.name not in SKIP_CHILDREN and (c / ".git").exists())
    candidates += [root / rel for rel in (config.PROJECT_SETTINGS.get("repositories") or {})]
    candidates.append(config.KB_REPO_PATH)
    found = {}
    for candidate in candidates:
        top = _toplevel(candidate) if candidate.is_dir() else None
        if top is None or top in found:
            continue
        if top != base and base not in top.parents:
            raise ProjectGitProblem(f"{top} is outside {base}; a ticket's workspace can only mirror "
                                    f"repositories inside the project folder.")
        found[top] = Repo(top, top.relative_to(base) if top != base else Path("."))
    return sorted(found.values(), key=lambda r: (r.rel != Path("."), r.rel.as_posix()))


def kb_repo(repos):
    kb = config.KB_REPO_PATH.resolve()
    holding = [r for r in repos if r.source == kb or r.source in kb.parents]
    if not holding:
        raise ProjectGitProblem(
            f"The knowledge base {kb} isn't in a git repository. Every ticket works on its own branch, so it "
            f"needs one: `git init` it, commit it to the development branch, and add a remote if the team "
            f"shares the board.")
    return max(holding, key=lambda r: len(r.source.parts))


def has_origin(repo):
    return _ok("remote", "get-url", "origin", cwd=repo.source)


def _ref_exists(ref, cwd):
    return _ok("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd)


def base_branch(repo):
    """The repository's own development_branch, else the project's, else the first of develop/development/main/master."""
    own = repo_settings(repo).get("development_branch")
    wanted = config.PROJECT_SETTINGS.get("development_branch")
    for name in [own] if own else [n for n in (wanted, *BASE_CANDIDATES) if n]:
        if _ref_exists(f"origin/{name}", repo.source) or _ref_exists(name, repo.source):
            return name
    raise ProjectGitProblem(
        f"{repo.name} has no development branch: "
        + (f"'{own}' (its development_branch setting) doesn't exist" if own
           else f"none of {[n for n in (wanted, *BASE_CANDIDATES) if n]} exists")
        + ". Create it, or set development_branch for it under `repositories` in .sdlc/config.json.")


def _start_point(repo):
    base = base_branch(repo)
    return base, (f"origin/{base}" if has_origin(repo) and _ref_exists(f"origin/{base}", repo.source) else base)


def worktrees_dir():
    return config.PROJECT_ROOT / config.PROJECT_DIR_NAME / "worktrees"


def path_for(branch):
    """The ticket's workspace folder."""
    return worktrees_dir() / branch.removeprefix(BRANCH_PREFIX).replace("/", "-")


def project_dir_in(workspace):
    """The project folder inside a workspace (the project may sit below its repository's root)."""
    return Path(workspace) / config.PROJECT_ROOT.resolve().relative_to(anchor())


def kb_dir_in(workspace):
    return Path(workspace) / config.KB_REPO_PATH.resolve().relative_to(anchor())


def compose_project_for(branch):
    """A Compose project name per ticket, so parallel stages never share containers."""
    return "sdlc-" + re.sub(r"[^a-z0-9-]", "-", branch.removeprefix(BRANCH_PREFIX).lower())[:50].strip("-")


def _kebab(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def new_branch_name(card):
    """feature/<card number>-<title>, e.g. feature/42-user-login."""
    title = _kebab(card.get("name", ""))[:MAX_TITLE_SLUG].rstrip("-") or "ticket"
    number = card.get("idShort") or card["id"][-6:]
    return f"{BRANCH_PREFIX}{number}-{title}"


def _legacy_branch(ticket_id, repo):
    """
    A ticket started before per-ticket worktrees built on feature/<slug>, with
    the slug registered in the project checkout's knowledge base. Keep using it.
    """
    try:
        features = json.loads((config.KB_REPO_PATH / "registry.json").read_text()).get("features", {})
    except (OSError, ValueError):
        return None
    for slug, entry in features.items():
        if entry.get("ticket_id") == ticket_id:
            branch = f"{BRANCH_PREFIX}{slug}"
            if _ref_exists(branch, repo.source) or _ref_exists(f"origin/{branch}", repo.source):
                return branch
    return None


def branch_for(state, card, repo):
    """(branch, is_new): the ticket's recorded branch, else a new name to record."""
    recorded = state.get("branches", {}).get(card["id"])
    if recorded:
        return recorded, False
    return _legacy_branch(card["id"], repo) or new_branch_name(card), True


def _registered_worktrees(repo):
    """{path: branch} for every worktree of one repository."""
    out = _git("worktree", "list", "--porcelain", cwd=repo.source).stdout
    found, path = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):]).resolve()
            found[path] = None
        elif line.startswith("branch ") and path:
            found[path] = line[len("branch "):].removeprefix("refs/heads/")
    return found


def is_dirty(path, only=None):
    args = ["status", "--porcelain"] + (["--", str(only)] if only else [])
    return bool(_git(*args, cwd=path).stdout.strip())


def _is_worktree_of(repo, path):
    return Path(path).resolve() in _registered_worktrees(repo)


def _sync_with_remote(repo, path, branch):
    """Fast-forward a worktree to what earlier stages pushed. Never merges or rewrites."""
    remote = f"origin/{branch}"
    if not _ref_exists(remote, path):
        return "not on the remote yet"
    ahead, behind = (int(n) for n in _git("rev-list", "--left-right", "--count",
                                          f"{branch}...{remote}", cwd=path).stdout.split())
    if behind == 0:
        return "up to date" if ahead == 0 else f"{ahead} local commit(s) not pushed yet"
    if ahead:
        raise TicketGitProblem(f"{repo.name}: branch {branch} has diverged from {remote} ({ahead} local, "
                               f"{behind} remote commits). A person has to reconcile them; the pipeline never "
                               f"merges or force-pushes.")
    if is_dirty(path):
        raise TicketGitProblem(f"{repo.name}: {remote} has {behind} new commit(s), but the worktree {path} has "
                               f"uncommitted changes, so it can't be fast-forwarded.")
    _git("merge", "--ff-only", remote, cwd=path)
    return f"pulled {behind} commit(s) from {remote}"


def _prepare_repo(repo, workspace, branch, pushed_before, is_kb):
    """One repository's worktree in the workspace, on the branch, up to date."""
    origin = has_origin(repo)
    warnings = []
    if origin:
        fetch = _git("fetch", "--quiet", "origin", cwd=repo.source, check=False)
        if fetch.returncode != 0:
            warnings.append(f"{repo.name}: git fetch failed, working from local refs: "
                            f"{' '.join(fetch.stderr.split())[:200]}")
    path = repo.worktree(workspace)
    registered = _registered_worktrees(repo)
    base = base_branch(repo)

    if path.resolve() in registered:
        checked_out = registered[path.resolve()]
        if checked_out != branch:
            raise TicketGitProblem(f"{repo.name}: the worktree {path} has '{checked_out}' checked out "
                                   f"instead of {branch}.")
        source = "reused"
    else:
        _git("worktree", "prune", cwd=repo.source)
        if branch in registered.values():
            where = next(p for p, b in registered.items() if b == branch)
            raise TicketGitProblem(f"{repo.name}: {branch} is already checked out in {where}. Switch that "
                                   f"checkout to another branch so the ticket can have its own worktree.")
        if path.exists() and (path.is_symlink() or any(path.iterdir())):
            raise TicketGitProblem(f"{repo.name}: {path} already exists and isn't this repository's worktree.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if _ref_exists(branch, repo.source):
            _git("worktree", "add", str(path), branch, cwd=repo.source)
            source = f"checked out {branch}"
        elif origin and _ref_exists(f"origin/{branch}", repo.source):
            _git("worktree", "add", "--track", "-b", branch, str(path), f"origin/{branch}", cwd=repo.source)
            source = f"checked out origin/{branch}, pushed by earlier stages"
        elif repo.name in pushed_before:
            # Recorded on the card as pushed, but not here and not on origin:
            # starting it afresh would lose earlier stages' work.
            raise TicketGitProblem(
                f"{repo.name}: the card records branch {branch} as pushed, but it isn't in this repository"
                + (" or on origin" if origin else "") + ". Push it from the machine that has it, then move "
                f"the card back to its stage.")
        else:
            _, start = _start_point(repo)
            if is_kb:
                registry = (config.KB_REPO_PATH.resolve() / "registry.json").relative_to(repo.source)
                if not _ok("cat-file", "-e", f"{start}:{registry.as_posix()}", cwd=repo.source):
                    raise ProjectGitProblem(
                        f"The knowledge base isn't on {start} in {repo.name}: every ticket branch starts from "
                        f"it, so commit it to {base}" + (" and push it" if origin else "")
                        + " before running the pipeline.")
            _git("worktree", "add", "--no-track", "-b", branch, str(path), start, cwd=repo.source)
            source = f"new branch from {start}"
            if is_kb and is_dirty(repo.source, only=config.KB_REPO_PATH):
                warnings.append(f"the knowledge base has uncommitted changes in {repo.source}; ticket branches "
                                f"only see what's committed to {base}.")
    synced = _sync_with_remote(repo, path, branch) if origin else "no remote"
    return {"path": str(path), "base": base, "git": f"{source}; {synced}"}, warnings


def _link_shared_files(workspace, repos):
    """
    When the project folder isn't a repository, its files outside every
    repository (a shared docker-compose.yml, a Makefile) have no branch. Link
    them into the workspace so relative paths still work; they stay shared.
    """
    root = anchor()
    if _toplevel(config.PROJECT_ROOT):
        return []
    repo_paths = {r.source for r in repos}

    def mirror(folder, target):
        linked = []
        for entry in sorted(folder.iterdir()):
            if entry.name in SKIP_CHILDREN or entry.resolve() in repo_paths:
                continue
            dest = target / entry.name
            if any(entry.resolve() in p.parents for p in repo_paths):  # holds a repository further down
                dest.mkdir(exist_ok=True)
                linked += mirror(entry, dest)
            elif not dest.exists() and not dest.is_symlink():
                dest.symlink_to(entry.resolve())
                linked.append(str(dest.relative_to(workspace)))
        return linked

    return mirror(root, Path(workspace))


def prepare(state, card, stage):
    """
    Make sure the ticket's workspace holds a worktree of every repository the
    stage needs, on the ticket's branch, with the latest pushed work. Called
    under the router's state lock. Returns (info, new_branch): info is a dict
    for the dispatch output; new_branch is True when the branch name still has
    to be recorded on the card.
    """
    repos = repositories()
    kb = kb_repo(repos)
    branch, is_new = branch_for(state, card, kb)
    workspace = path_for(branch)
    pushed_before = set(state.get("pushed_repos", {}).get(card["id"], []))

    top = repos[0] if repos[0].rel == Path(".") else None
    wanted = repos if stage not in DOC_ONLY_STAGES else [r for r in repos if r in (top, kb)]
    # Repositories a code stage already added stay in step, whatever the stage.
    wanted += [r for r in repos if r not in wanted and _is_worktree_of(r, r.worktree(workspace))]

    worktrees_dir().mkdir(parents=True, exist_ok=True)
    config.ensure_gitignore(config.PROJECT_ROOT / config.PROJECT_DIR_NAME)
    if not top:
        workspace.mkdir(exist_ok=True)

    repo_info, warnings = {}, []
    try:
        for repo in [r for r in repos if r in wanted]:  # anchor first: the others nest inside it
            repo_info[repo.name], repo_warnings = _prepare_repo(repo, workspace, branch, pushed_before, repo == kb)
            warnings += repo_warnings
        shared = _link_shared_files(workspace, repos)
    except subprocess.CalledProcessError as exc:
        raise TicketGitProblem(f"git failed preparing {branch}: {_error_text(exc)}") from exc

    info = {
        "worktree": str(workspace),
        "project_dir": str(project_dir_in(workspace)),
        "branch": branch,
        "compose_project": compose_project_for(branch),
        "repos": repo_info,
    }
    if len(repos) == 1:
        info["git"] = repo_info[kb.name]["git"]
    if shared:
        info["shared_files"] = shared
    if warnings:
        info["git_warnings"] = warnings
    return info, is_new


def _commits_beyond_base(repo, path, branch):
    _, start = _start_point(repo)
    return int(_git("rev-list", "--count", f"{start}..{branch}", cwd=path).stdout.strip() or 0)


def record_stage(state, stage, ticket_id, card_name, outcome):
    """
    After a stage's run: commit its knowledge base changes on the ticket's
    branch, and push every repository whose branch has work. Code the stage
    changed is its own to commit; anything left uncommitted is reported, never
    committed here. Returns the result, with `pushed_repos` listing every
    repository whose branch is now on origin.
    """
    branch = state.get("branches", {}).get(ticket_id)
    if not branch:
        return {"git": "no worktree for this ticket"}
    workspace = path_for(branch)
    if not workspace.is_dir():
        return {"git": f"workspace {workspace} is missing"}

    repos = repositories()
    kb = kb_repo(repos)
    result = {"branch": branch, "repos": {}, "pushed_repos": []}
    for repo in repos:
        path = repo.worktree(workspace)
        if not _is_worktree_of(repo, path):
            continue
        entry = result["repos"][repo.name] = {}
        if repo == kb:
            try:
                kb_dir = kb_dir_in(workspace)
                if kb_dir.exists() and is_dirty(path, only=kb_dir):
                    _git("add", "--", str(kb_dir), cwd=path)
                    subject = f"{stage}: {card_name}"[:72]
                    message = (f"{subject}\n\nKnowledge base changes from the {stage} stage.\n\n"
                               f"Ticket: #{ticket_id}\nStage: {stage}\nOutcome: {outcome}\n"
                               f"Co-Authored-By: Claude <noreply@anthropic.com>\n")
                    _git("commit", "--quiet", "-m", message, cwd=path)
                    entry["committed"] = _git("rev-parse", "--short", "HEAD", cwd=path).stdout.strip()
            except subprocess.CalledProcessError as exc:
                entry["commit_error"] = _error_text(exc)

        leftover = _git("status", "--porcelain", cwd=path, check=False).stdout.splitlines()
        if leftover:
            entry["uncommitted"] = leftover[:20]

        if not has_origin(repo):
            entry["pushed"] = "no remote; committed locally"
            continue
        on_origin = _ref_exists(f"origin/{branch}", path)
        try:
            has_work = on_origin or _commits_beyond_base(repo, path, branch) > 0
        except (subprocess.CalledProcessError, ProjectGitProblem) as exc:
            entry["pushed"] = f"failed: {exc}"
            continue
        if not has_work:
            entry["pushed"] = "nothing to push (no commits on this branch)"
            continue
        push = _git("push", "--quiet", "-u", "origin", branch, cwd=path, check=False)
        if push.returncode == 0:
            entry["pushed"] = True
            result["pushed_repos"].append(repo.name)
        else:
            entry["pushed"] = f"failed: {' '.join(push.stderr.split())[:300]}"
            if on_origin:
                result["pushed_repos"].append(repo.name)  # an earlier push is still there
    return result


def _state_unlocked():
    try:
        return json.loads(config.STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def ticket_kb_root(ticket_id):
    """The knowledge base inside a ticket's workspace, read without the lock (MCP servers)."""
    branch = _state_unlocked().get("branches", {}).get(ticket_id)
    return kb_dir_in(path_for(branch)) if branch and path_for(branch).is_dir() else None


def dispatched_ticket(stage):
    """The ticket the router last dispatched to `stage` and hasn't seen finish."""
    info = _state_unlocked().get("agents", {}).get(stage, {})
    return info.get("ticket_id") if info.get("status") == "busy" else None


def _unpushed(repo, path, branch):
    if not has_origin(repo):
        return "no remote"
    if not _ref_exists(f"origin/{branch}", path):
        commits = _commits_beyond_base(repo, path, branch)
        return f"never pushed ({commits} commit(s))" if commits else 0
    return int(_git("rev-list", "--count", f"origin/{branch}..{branch}", cwd=path).stdout.strip() or 0)


def listing(state):
    """Every ticket workspace the router knows about, per repository, with whether it's safe to remove."""
    repos = repositories()
    rows = []
    for ticket_id, branch in sorted(state.get("branches", {}).items(), key=lambda kv: kv[1]):
        workspace = path_for(branch)
        row = {"ticket_id": ticket_id, "branch": branch, "worktree": str(workspace),
               "exists": workspace.is_dir(), "repos": {}}
        for repo in repos:
            path = repo.worktree(workspace)
            if _is_worktree_of(repo, path):
                row["repos"][repo.name] = {"dirty": is_dirty(path), "unpushed": _unpushed(repo, path, branch)}
        rows.append(row)
    return rows


def remove(state, ticket_id):
    """Remove a ticket's workspace (never its branches), refusing if work would be lost."""
    branch = state.get("branches", {}).get(ticket_id)
    if not branch:
        raise TicketGitProblem("the router has no workspace for that ticket")
    workspace = path_for(branch)
    trees = [(r, r.worktree(workspace)) for r in repositories() if _is_worktree_of(r, r.worktree(workspace))]
    for repo, path in trees:
        if is_dirty(path):
            raise TicketGitProblem(f"{repo.name} has uncommitted changes in {path}; commit or discard them first")
        unpushed = _unpushed(repo, path, branch)
        if unpushed not in (0, "no remote"):
            raise TicketGitProblem(f"{repo.name}: {branch} has work that isn't on origin ({unpushed}); push it first")
    for repo, path in reversed(trees):  # nested worktrees before the one holding them
        _git("worktree", "remove", str(path), cwd=repo.source)
    if workspace.exists():
        leftovers = [p for p in workspace.rglob("*") if not p.is_symlink() and not p.is_dir()
                     and not any(q.is_symlink() for q in p.parents)]
        if leftovers:
            raise TicketGitProblem(f"worktrees removed, but {workspace} still holds files that aren't in any "
                                   f"repository (e.g. {leftovers[0]}); look at them and delete the folder yourself")
        shutil.rmtree(workspace)  # only links to shared files and empty folders are left
    return f"removed {workspace}; the branch {branch} is kept in every repository"
