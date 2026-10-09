"""
Publish the project docs a ticket's Knowledge Base Writer recorded straight to
the development branch, so every ticket sees them on its next dispatch instead
of after the ticket's release is merged.

Only product/, architecture/ and patterns/ go, with their registry.json
entries: the shared facts. The ticket's own feature folder and its code stay
on its branch and travel with its release.

The commit is built without checking anything out, on top of the development
branch as origin has it, and pushed there. Each file is merged three ways
against where the ticket branch left the development branch: a doc that
someone else changed on the development branch in the meantime is a conflict,
and then nothing is published (the router reports it; a person reconciles).
"""

import os
import subprocess
import tempfile

import config
import worktrees
from knowledge_base import PROJECT_SECTIONS
from releases import RegistryConflict, _merge_values, _show
from worktrees import _git, _ok, _ref_exists


def _blob(path, ref, file):
    result = _git("rev-parse", "--verify", "--quiet", f"{ref}:{file}", cwd=path, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _checked_out_in(repo, branch):
    return next((p for p, b in worktrees._registered_worktrees(repo).items() if b == branch), None)


def publish(state, ticket_id, card_name):
    """
    Put the project-doc changes on the ticket's branch onto the development
    branch. Returns a dict for the finish output: what was published, or why
    nothing was.
    """
    branch = state.get("branches", {}).get(ticket_id)
    if not branch:
        return {"published": "nothing: no branch for this ticket"}
    repo = worktrees.kb_repo(worktrees.repositories())
    path = repo.worktree(worktrees.path_for(branch))
    if not worktrees._is_worktree_of(repo, path):
        return {"published": "nothing: the ticket has no knowledge base worktree"}

    origin = worktrees.has_origin(repo)
    if origin:
        _git("fetch", "--quiet", "origin", cwd=repo.source, check=False)
    base, start = worktrees._start_point(repo)
    kb_rel = config.KB_REPO_PATH.resolve().relative_to(repo.source).as_posix()
    prefix = "" if kb_rel == "." else f"{kb_rel}/"
    registry = f"{prefix}registry.json"

    merge_base = _git("merge-base", start, branch, cwd=path).stdout.strip()
    changed = _git("diff", "--name-only", merge_base, branch, "--",
                   *(f"{prefix}{section}/" for section in PROJECT_SECTIONS), cwd=path).stdout.split()

    updates, conflicts = {}, []
    for file in changed:
        ours, theirs, old = _blob(path, start, file), _blob(path, branch, file), _blob(path, merge_base, file)
        if ours == theirs:
            continue  # already on the development branch
        if ours != old:
            conflicts.append(file)
        else:
            updates[file] = theirs  # None removes it

    # registry.json: only its project sections; features stay with their tickets.
    dev_registry = _show(path, start, registry)
    merged = dict(dev_registry)
    old_registry, ticket_registry = _show(path, merge_base, registry), _show(path, branch, registry)
    for section in PROJECT_SECTIONS:
        try:
            value = _merge_values(old_registry.get(section), dev_registry.get(section),
                                  ticket_registry.get(section), section)
        except RegistryConflict as exc:
            conflicts.append(str(exc))
            continue
        if value is not None:
            merged[section] = value
    if merged != dev_registry:
        import json
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=path, input=json.dumps(merged, indent=2) + "\n",
                              capture_output=True, text=True, check=True).stdout.strip()
        updates[registry] = blob

    if conflicts:
        return {"published": "nothing", "conflicts": conflicts,
                "reason": f"these changed on {base} since the ticket's branch last took it in; a person has to "
                          f"reconcile them there"}
    if not updates:
        return {"published": "nothing new"}

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}

        def git_env(*args, **kwargs):
            return subprocess.run(["git", *args], cwd=path, env=env, capture_output=True, text=True, check=True,
                                  **kwargs).stdout.strip()

        git_env("read-tree", start)
        for file, blob in updates.items():
            if blob is None:
                git_env("update-index", "--force-remove", "--", file)
            else:
                git_env("update-index", "--add", "--cacheinfo", f"100644,{blob},{file}")
        tree = git_env("write-tree")
    parent = _git("rev-parse", start, cwd=path).stdout.strip()
    message = (f"Knowledge base: project docs from {card_name}"[:72] + "\n\n"
               f"Recorded by the Knowledge Base Writer stage, published to {base} so every ticket sees them.\n\n"
               + "".join(f"- {file}\n" for file in updates)
               + f"\nTicket: #{ticket_id}\nStage: Knowledge Base Writer\n"
               f"Co-Authored-By: Claude <noreply@anthropic.com>\n")
    commit = _git("commit-tree", tree, "-p", parent, "-m", message, cwd=path).stdout.strip()

    result = {"published": sorted(updates), "commit": commit[:12], "branch": base}
    if origin:
        push = _git("push", "--quiet", "origin", f"{commit}:refs/heads/{base}", cwd=path, check=False)
        if push.returncode != 0:
            return {"published": "nothing", "reason": f"push to {base} failed: {' '.join(push.stderr.split())[:300]}"}
    # Move the local development branch too, unless someone has it checked out
    # (their working tree would no longer match it); they pull as usual.
    holder = _checked_out_in(repo, base)
    local_at = _git("rev-parse", base, cwd=path, check=False).stdout.strip() if _ref_exists(base, path) else None
    if holder is None and local_at == parent:
        _git("update-ref", f"refs/heads/{base}", commit, parent, cwd=path)
    elif not origin:
        return {"published": "nothing",
                "reason": f"there's no remote, and {base} is checked out in {holder}; record the docs there by hand"
                          if holder else f"there's no remote, and local {base} has moved on"}
    elif holder is not None:
        result["note"] = f"{holder} has {base} checked out; pull to get these docs there"
    return result
