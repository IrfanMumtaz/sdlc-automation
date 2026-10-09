"""
Releases: every ticket ships in a named release, and the Deploy stage merges
the ticket's branch into that release's branch.

The release is recorded on the card, the same way its branch is:

    [RELEASE] ticket=#123 version="1.4.0" by="PO"

The PO stage records it once the requester or a person has named one; a
person can also set it with `sdlc release`. The latest [RELEASE] comment wins,
so changing a ticket's release is one more comment, and the card keeps the
history.

Merging (the Deploy stage, through its merge_into_release tool):

    feature/42-checkout  --merge --no-ff-->  release/1.4.0  --push-->  origin

in every repository the ticket's branch has commits in. The release branch
starts from the repository's development branch the first time a ticket joins
the release. Release branches get their own workspace,
<project>/.sdlc/worktrees/release-<version>/, mirroring the project's layout
like a ticket's. Every repository is checked for conflicts before any of them
changes, so a release never ends up with half a ticket merged. Nothing here
merges into the development branch: that's the pull request a person reviews.

The knowledge base's registry.json is the one file merged by content rather
than by line: every ticket adds its own feature entry at the end of the same
object, so a second ticket in a release would always conflict on it. Its
entries are merged one by one; only two tickets changing the same entry in
different ways is a real conflict.
"""

import json
import re
import subprocess
from pathlib import Path

import config
import worktrees
from worktrees import TicketGitProblem, _git, _ok, _ref_exists, _error_text

RELEASE_PREFIX = "release/"
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
COMMENT_PREFIX = "[RELEASE]"


def validate_version(version):
    """A release version as typed (1.4.0, v2.1, 2026.10), or ValueError."""
    version = (version or "").strip()
    if not VERSION_PATTERN.fullmatch(version) or ".." in version or version.endswith((".", ".lock")):
        raise ValueError(f"'{version}' isn't a usable release version: use letters, digits, dots, dashes "
                         f"and underscores, e.g. 1.4.0")
    return version


def branch_name(version):
    return f"{RELEASE_PREFIX}{version}"


def comment_text(ticket_id, version, by):
    return f'{COMMENT_PREFIX} ticket=#{ticket_id} version="{validate_version(version)}" by="{by}"'


def release_of(comments):
    """
    The ticket's release from its card comments (Trello's order, newest
    first), or None when none is recorded.
    """
    import comment_parser

    for comment in comments:
        event = comment_parser.parse_comment(comment.get("data", {}).get("text", ""))
        if event and event["type"] == "RELEASE" and event.get("version"):
            return event["version"]
    return None


def workspace_for(version):
    return worktrees.worktrees_dir() / f"release-{version}"


def _release_worktree(repo, workspace, release):
    """The repository's worktree on the release branch, created if needed and up to date with origin."""
    path = repo.worktree(workspace)
    registered = worktrees._registered_worktrees(repo)
    if path.resolve() in registered:
        if registered[path.resolve()] != release:
            raise TicketGitProblem(f"{repo.name}: {path} has '{registered[path.resolve()]}' checked out "
                                   f"instead of {release}.")
    else:
        _git("worktree", "prune", cwd=repo.source)
        if release in registered.values():
            where = next(p for p, b in registered.items() if b == release)
            raise TicketGitProblem(f"{repo.name}: {release} is checked out in {where}. Switch that checkout "
                                   f"to another branch so the release can have its own worktree.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if _ref_exists(release, repo.source):
            _git("worktree", "add", str(path), release, cwd=repo.source)
        elif worktrees.has_origin(repo) and _ref_exists(f"origin/{release}", repo.source):
            _git("worktree", "add", "--track", "-b", release, str(path), f"origin/{release}", cwd=repo.source)
        else:
            _, start = worktrees._start_point(repo)
            _git("worktree", "add", "--no-track", "-b", release, str(path), start, cwd=repo.source)
    if worktrees.has_origin(repo):
        worktrees._sync_with_remote(repo, path, release)
    if worktrees.is_dirty(path):
        raise TicketGitProblem(f"{repo.name}: the release worktree {path} has uncommitted changes; a person "
                               f"has to clear them before anything else is merged into {release}.")
    return path


class RegistryConflict(Exception):
    pass


def _registry_path(repo):
    """The knowledge base's registry.json relative to this repository, or None if it isn't in it."""
    registry = config.KB_REPO_PATH.resolve() / "registry.json"
    return registry.relative_to(repo.source).as_posix() if repo.source in registry.parents else None


def _merge_values(base, ours, theirs, where):
    """Three-way merge of two JSON values that started from `base`."""
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base = base if isinstance(base, dict) else {}
        merged = {}
        for key in [*ours, *(k for k in theirs if k not in ours)]:
            if key not in theirs:
                merged[key] = ours[key]
            elif key not in ours:
                merged[key] = theirs[key]
            else:
                merged[key] = _merge_values(base.get(key), ours[key], theirs[key], f"{where}.{key}")
        return merged
    raise RegistryConflict(f"registry.json: both sides changed {where.lstrip('.')} differently")


def _show(path, ref, file):
    result = _git("show", f"{ref}:{file}", cwd=path, check=False)
    return json.loads(result.stdout) if result.returncode == 0 else {}


def _merged_registry(path, release, branch, file):
    """registry.json as the merge of `branch` into `release` should have it, or RegistryConflict."""
    base = _git("merge-base", release, branch, cwd=path).stdout.strip()
    merged = _merge_values(_show(path, base, file), _show(path, release, file), _show(path, branch, file), "")
    return json.dumps(merged, indent=2) + "\n"


def _conflicts(path, release, branch):
    """Files that would conflict merging `branch` into `release`, without touching the worktree."""
    result = _git("merge-tree", "--write-tree", "--name-only", "--no-messages", release, branch,
                  cwd=path, check=False)
    if result.returncode == 0:
        return []
    if result.returncode == 1:
        return [line for line in result.stdout.splitlines()[1:] if line.strip()]
    raise subprocess.CalledProcessError(result.returncode, ["git", "merge-tree"], result.stdout, result.stderr)


def merge(state, ticket_id, card_name, version):
    """
    Merge the ticket's branch into release/<version> in every repository the
    ticket changed, and push each release branch. Called under the router's
    state lock, so two tickets never merge into the same release at once.
    Returns a dict per repository; raises TicketGitProblem, with nothing
    merged anywhere, when the merge can't be done cleanly.
    """
    version = validate_version(version)
    branch = state.get("branches", {}).get(ticket_id)
    if not branch:
        raise TicketGitProblem("the router has no branch recorded for this ticket")
    ticket_ws = worktrees.path_for(branch)
    release = branch_name(version)
    release_ws = workspace_for(version)

    repos = worktrees.repositories()
    try:
        changed = []
        for repo in repos:
            path = repo.worktree(ticket_ws)
            if not worktrees._is_worktree_of(repo, path):
                continue
            if worktrees.has_origin(repo):
                _git("fetch", "--quiet", "origin", cwd=repo.source, check=False)
            if worktrees._commits_beyond_base(repo, path, branch) == 0:
                continue
            unpushed = worktrees._unpushed(repo, path, branch)
            if unpushed not in (0, "no remote"):
                raise TicketGitProblem(f"{repo.name}: {branch} has work that isn't on origin ({unpushed}); "
                                       f"push it before merging it into {release}.")
            changed.append(repo)
        if not changed:
            raise TicketGitProblem(f"{branch} has no commits beyond the development branch in any repository; "
                                   f"there's nothing to release.")

        # The project's own repository holds the others in a workspace, so it
        # gets a release worktree whenever any repository does.
        top = repos[0] if repos[0].rel.as_posix() == "." else None
        needed = ([top] if top and top not in changed else []) + changed
        paths = {repo.name: _release_worktree(repo, release_ws, release) for repo in needed}

        # Check every repository before changing any of them. A conflict in
        # registry.json alone is resolved by merging its entries.
        conflicts, registries = {}, {}
        for repo in changed:
            files = _conflicts(paths[repo.name], release, branch)
            registry = _registry_path(repo)
            if registry in files:
                files.remove(registry)
                try:
                    registries[repo.name] = (registry, _merged_registry(paths[repo.name], release, branch, registry))
                except RegistryConflict as exc:
                    files.append(str(exc))
            if files:
                conflicts[repo.name] = files
        if conflicts:
            detail = "; ".join(f"{name}: {', '.join(files[:10])}" for name, files in conflicts.items())
            raise TicketGitProblem(f"{branch} conflicts with {release} ({detail}). Nothing was merged.")

        result = {"release": release, "version": version, "branch": branch, "repos": {}}
        for repo in changed:
            path = paths[repo.name]
            entry = result["repos"][repo.name] = {"release_worktree": str(path),
                                                  "base": worktrees.base_branch(repo)}
            if _ok("merge-base", "--is-ancestor", branch, release, cwd=path):
                entry["merged"] = "already in the release"
            else:
                message = (f"Merge {branch} into {release}\n\n{card_name}\n\n"
                           f"Ticket: #{ticket_id}\nRelease: {version}\nStage: Deploy\n"
                           f"Co-Authored-By: Claude <noreply@anthropic.com>\n")
                merge = _git("merge", "--no-ff", "--quiet", "-m", message, branch, cwd=path, check=False)
                if merge.returncode != 0:
                    if repo.name not in registries:
                        _git("merge", "--abort", cwd=path, check=False)
                        raise subprocess.CalledProcessError(merge.returncode, ["git", "merge"],
                                                            merge.stdout, merge.stderr)
                    registry, content = registries[repo.name]
                    (Path(path) / registry).write_text(content)
                    _git("add", "--", registry, cwd=path)
                    unmerged = _git("diff", "--name-only", "--diff-filter=U", cwd=path).stdout.split()
                    if unmerged:
                        _git("merge", "--abort", cwd=path, check=False)
                        raise TicketGitProblem(f"{repo.name}: merging {branch} left {', '.join(unmerged)} "
                                               f"in conflict. Nothing was merged in {repo.name}.")
                    _git("commit", "--quiet", "--no-edit", cwd=path)
                    entry["registry"] = "registry.json entries merged"
                entry["merged"] = True
            entry["release_head"] = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
            if not worktrees.has_origin(repo):
                entry["pushed"] = "no remote; merged locally"
                continue
            entry["remote"] = _git("remote", "get-url", "origin", cwd=path).stdout.strip()
            push = _git("push", "--quiet", "-u", "origin", release, cwd=path, check=False)
            entry["pushed"] = True if push.returncode == 0 else f"failed: {' '.join(push.stderr.split())[:300]}"
        return result
    except subprocess.CalledProcessError as exc:
        raise TicketGitProblem(f"git failed merging {branch} into {release}: {_error_text(exc)}") from exc
