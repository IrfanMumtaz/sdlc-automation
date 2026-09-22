#!/usr/bin/env python3
"""
Install the SDLC pipeline for your user, so /sdlc and /sdlc-kickoff work in any
project folder:

    python3 install.py              install or update (safe to rerun)
    python3 install.py --update     pull the latest engine from git, then reinstall
    python3 install.py --uninstall  remove everything install added

It:
  1. links ~/.local/bin/sdlc to this engine's sdlc.py
  2. links each agent in claude/agents/ into ~/.claude/agents/ and each skill
     in claude/skills/ into ~/.claude/skills/ (links, so edits here apply
     immediately)
  3. adds the pipeline's permission rules to ~/.claude/settings.json
     (a backup is written to settings.json.sdlc-backup first). These include
     the docker, git and package-manager commands the coding stages run, which
     apply to every project; --no-dev-permissions leaves those out.
  4. adds a SessionStart hook to ~/.claude/settings.json that runs
     `install.py --update --quiet` whenever Claude Code starts, so this machine
     picks up engine changes pushed from elsewhere; --no-auto-update leaves it
     out (and removes it if it's there).

--update only fast-forwards: it never merges, and it leaves the engine alone
when it has local changes or commits that aren't on its upstream branch.

Trello credentials aren't installed here: they belong to each project, in its
gitignored .sdlc/.env, and `sdlc init` asks for them.

It never overwrites a file it didn't create: an existing agent, skill or
command with the same name is reported and skipped.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
HOME = Path.home()
BIN_LINK = HOME / ".local" / "bin" / "sdlc"
CLAUDE_DIR = HOME / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
# Where earlier versions kept Trello credentials for every project. No longer read.
LEGACY_CREDENTIALS = [HOME / ".config" / "sdlc" / ".env", ENGINE / ".env"]

PERMISSIONS = [
    "Bash(sdlc status)",
    "Bash(sdlc next *)",
    "Bash(sdlc finish *)",
    "Bash(sdlc recover)",
    "Bash(sdlc skip *)",
    "Bash(sdlc render *)",
    "Bash(sdlc draft *)",
    "mcp__sdlc-trello",
    "mcp__sdlc-kb-po",
    "mcp__sdlc-kb-ba",
    "mcp__sdlc-kb-ui-ux",
    "mcp__sdlc-kb-architect",
    "mcp__sdlc-kb-read",
    "mcp__sdlc-kb-writer",
    "mcp__sdlc-kb-dev",
    "mcp__sdlc-kb-analyst",
    "mcp__sdlc-kb-test-writer",
    "mcp__sdlc-kb-qa",
    "mcp__sdlc-kb-po-tester",
    "mcp__sdlc-kb-deploy",
]

# The coding stages (Senior Developer onward) build, test and run the product
# through its own Docker setup, and keep each ticket on its own branch. Without
# these rules every command stops an unattended /sdlc run to ask.
#
# They are broader than the rules above: they apply to every project you use
# Claude Code in, not just SDLC ones. Drop any you'd rather approve by hand —
# the pipeline still works, it just pauses for an answer.
DEV_PERMISSIONS = [
    "Bash(docker compose *)",
    "Bash(docker *)",
    "Bash(git *)",
    "Bash(pnpm *)",
    "Bash(npm *)",
    "Bash(npx *)",
    "Bash(node *)",
]

# Rules earlier versions added, replaced by the ones above.
OBSOLETE_PERMISSIONS = ["Bash(sdlc next)"]

# The SessionStart hook that keeps this machine's engine current. Recognised by
# HOOK_MARKER, so a moved engine or an older command line is still found.
HOOK_MARKER = 'install.py" --update --quiet'
HOOK_STATUS = "Checking for SDLC engine updates"


def links():
    """(link path, target) for everything install links."""
    pairs = [(BIN_LINK, ENGINE / "sdlc.py")]
    pairs += [(CLAUDE_DIR / "agents" / f.name, f) for f in sorted((ENGINE / "claude" / "agents").glob("*.md"))]
    pairs += [(CLAUDE_DIR / "skills" / d.name, d) for d in sorted((ENGINE / "claude" / "skills").iterdir()) if d.is_dir()]
    return pairs


def ours(path):
    """True for links (or copies) this installer made, never for a user's own file."""
    if path.is_symlink():
        return str(path.resolve()).startswith(str(ENGINE))
    return False


def install_links():
    """Link everything; return what changed (links already in place aren't listed)."""
    changes = []
    for link, target in links():
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if ours(link):
            link.unlink()
        elif link.exists() or link.is_symlink():
            changes.append(f"skipped {link}: already exists and isn't from this engine")
            continue
        try:
            link.symlink_to(target)
            changes.append(f"linked {link}")
        except OSError:  # e.g. Windows without developer mode: copy instead
            shutil.copytree(target, link) if target.is_dir() else shutil.copyfile(target, link)
            changes.append(f"copied {link} (no symlinks here: rerun install.py after changing the engine)")
    (ENGINE / "sdlc.py").chmod(0o755)
    # remove links to agents or skills that no longer exist in the engine
    for folder in (CLAUDE_DIR / "agents", CLAUDE_DIR / "skills"):
        for entry in folder.iterdir() if folder.exists() else []:
            if entry.is_symlink() and str(Path(entry.readlink())).startswith(str(ENGINE)) and not entry.exists():
                entry.unlink()
                changes.append(f"removed stale link {entry}")
    return changes


def load_settings():
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}


def save_settings(settings):
    if SETTINGS.exists():
        shutil.copyfile(SETTINGS, SETTINGS.with_name("settings.json.sdlc-backup"))
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def install_permissions(with_dev=True):
    """Add the pipeline's rules; return what changed (nothing when all are present)."""
    settings = load_settings()
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    wanted = PERMISSIONS + (DEV_PERMISSIONS if with_dev else [])
    stale = [rule for rule in OBSOLETE_PERMISSIONS if rule in allow]
    added = [rule for rule in wanted if rule not in allow]
    if not (added or stale):
        return []
    if stale:
        allow[:] = [rule for rule in allow if rule not in stale]
    allow.extend(added)
    save_settings(settings)
    changes = [f"permissions: {len(added)} added, {len(stale)} obsolete removed, in {SETTINGS}"]
    changes += [f"  {rule}  (coding stages; applies to every project)" for rule in added if rule in DEV_PERMISSIONS]
    return changes


def is_our_hook(hook):
    return HOOK_MARKER in hook.get("command", "")


def auto_update_on():
    groups = load_settings().get("hooks", {}).get("SessionStart", [])
    return any(is_our_hook(h) for group in groups for h in group.get("hooks", []))


def set_auto_update(enabled):
    """Add or remove the SessionStart hook; return what changed."""
    settings = load_settings()
    hooks = settings.get("hooks", {})
    before = json.dumps(hooks, sort_keys=True)
    groups = []
    for group in hooks.get("SessionStart", []):
        kept = [h for h in group.get("hooks", []) if not is_our_hook(h)]
        if kept:
            groups.append({**group, "hooks": kept})
    if enabled:
        command = f'"{sys.executable}" "{ENGINE / "install.py"}" --update --quiet'
        groups.append({"matcher": "startup", "hooks": [
            {"type": "command", "command": command, "timeout": 30, "statusMessage": HOOK_STATUS}]})
    if groups:
        hooks["SessionStart"] = groups
    else:
        hooks.pop("SessionStart", None)
    if json.dumps(hooks, sort_keys=True) == before:
        return []
    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)
    save_settings(settings)
    if enabled:
        return [f"auto-update: the engine updates itself from git when Claude Code starts (hook in {SETTINGS})"]
    return [f"auto-update: removed the startup hook from {SETTINGS}"]


def git(*args, timeout=60):
    """Run git in the engine folder, never prompting for a password or passphrase."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=10")
    result = subprocess.run(["git", "-C", str(ENGINE), *args], capture_output=True, text=True,
                            timeout=timeout, env=env)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def update(quiet):
    """
    Fast-forward the engine to its upstream branch, then reinstall with the new
    code. With quiet (the startup hook), say nothing unless something changed or
    an update is waiting that couldn't be applied, and say it as a Claude Code
    systemMessage so it shows in the session.
    """
    def report(lines):
        if not lines:
            return 0
        if quiet:
            print(json.dumps({"systemMessage": "SDLC engine: " + " ".join(lines)}))
        else:
            print("\n".join(lines))
        return 0

    try:
        code, upstream, _ = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if code:
            return report([] if quiet else [f"{ENGINE} has no upstream branch to update from."])
        code, _, err = git("fetch", "--quiet", timeout=20)
        if code:  # offline, or no access: try again next time
            return report([] if quiet else [f"Couldn't reach the engine's remote: {err}"])
        _, behind, _ = git("rev-list", "--count", "HEAD..@{u}")
        _, ahead, _ = git("rev-list", "--count", "@{u}..HEAD")
        if not (behind.isdigit() and ahead.isdigit()):
            return report([] if quiet else [f"Couldn't compare {ENGINE} with {upstream}."])
        if behind == "0":
            return report([] if quiet else [f"Already up to date with {upstream}."])
        if ahead != "0":
            return report([f"{behind} new commit(s) on {upstream} not applied: {ENGINE} has {ahead} local "
                           f"commit(s) that aren't pushed. Push or reconcile them, then run install.py --update."])
        _, dirty, _ = git("status", "--porcelain", "--untracked-files=no")
        if dirty:
            return report([f"{behind} new commit(s) on {upstream} not applied: {ENGINE} has uncommitted "
                           f"changes. Commit or discard them, then run install.py --update."])
        _, old, _ = git("rev-parse", "HEAD")
        code, _, err = git("merge", "--ff-only", "--quiet", "@{u}")
        if code:
            return report([f"Update from {upstream} failed: {err}"])
        _, subjects, _ = git("log", "--format=%s", f"{old}..HEAD")
        _, files, _ = git("diff", "--name-only", old, "HEAD")
    except (OSError, subprocess.TimeoutExpired) as e:
        return report([] if quiet else [f"Update failed: {e}"])

    # the new install.py relinks and adds new permission rules, keeping this machine's choices
    refresh = subprocess.run([sys.executable, str(ENGINE / "install.py"), "--refresh"],
                             capture_output=True, text=True)
    lines = [f"updated to the latest {upstream} ({behind} commit(s): {'; '.join(subjects.splitlines())})."]
    lines += [line.strip() for line in refresh.stdout.splitlines() if line.strip()]
    if refresh.returncode:
        lines.append(f"Reinstall failed, run python3 {ENGINE / 'install.py'} by hand: {refresh.stderr.strip()}")
    if "requirements.txt" in files.splitlines():
        lines.append(f"Python requirements changed: pip install -r {ENGINE / 'requirements.txt'}")
    lines.append("Changes apply from the next Claude Code session at the latest.")
    return report(lines)


def report_legacy_credentials():
    """Credentials are per project now; point out files earlier versions used."""
    for path in LEGACY_CREDENTIALS:
        if path.exists():
            print(f"  NOTE: {path} is no longer read. Trello credentials live in each project's "
                  f".sdlc/.env: copy them there (or rerun `sdlc init` in the project), then delete this file.")


def check_requirements():
    missing = [m for m in ("requests", "mcp") if importlib.util.find_spec(m) is None]
    if missing:
        print(f"  WARNING: missing Python packages {missing}: pip install -r {ENGINE / 'requirements.txt'}")
    if not any(shutil.which(c) for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")):
        print("  WARNING: no Chrome or Chromium on PATH; mockups need one (or set chrome_path per project)")
    if str(BIN_LINK.parent) not in __import__("os").environ.get("PATH", "").split(":"):
        print(f"  WARNING: {BIN_LINK.parent} isn't on PATH; add it so Claude Code can run `sdlc`")


def uninstall():
    for link, _ in links():
        if ours(link):
            link.unlink()
            print(f"  removed {link}")
    settings = load_settings()
    allow = settings.get("permissions", {}).get("allow", [])
    removable = PERMISSIONS + DEV_PERMISSIONS + OBSOLETE_PERMISSIONS
    if any(rule in allow for rule in removable):
        settings["permissions"]["allow"] = [rule for rule in allow if rule not in removable]
        save_settings(settings)
        print(f"  removed permission rules from {SETTINGS}")
    for line in set_auto_update(False):
        print(f"  {line}")
    print("  kept each project's .sdlc/.env (its Trello credentials); delete them yourself if you no longer need them")


def refresh():
    """
    What --update runs with the freshly pulled install.py: relink, add the
    pipeline's own new permission rules, and rewrite the startup hook if it's
    on. The broad coding-stage rules and the auto-update choice are left as
    this machine has them; rerun install.py by hand to change those.
    """
    changes = install_links() + install_permissions(with_dev=False)
    if auto_update_on():
        changes += set_auto_update(True)
    for line in changes:
        print(line)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--update", action="store_true", help="pull the latest engine from git, then reinstall")
    parser.add_argument("--no-dev-permissions", action="store_true",
                        help="don't allow the coding stages' docker/git/package-manager commands")
    parser.add_argument("--no-auto-update", action="store_true",
                        help="don't update the engine when Claude Code starts (removes the hook if it's there)")
    parser.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)  # --update from the startup hook
    parser.add_argument("--refresh", action="store_true", help=argparse.SUPPRESS)  # run by --update after a pull
    args = parser.parse_args()
    if args.uninstall:
        uninstall()
        return
    if args.update:
        return update(args.quiet)
    if args.refresh:
        refresh()
        return
    changes = install_links()
    changes += install_permissions(with_dev=not args.no_dev_permissions)
    changes += set_auto_update(not args.no_auto_update)
    for line in changes or ["already installed; nothing to change"]:
        print(f"  {line}")
    if args.no_dev_permissions:
        print("  skipped the coding stages' shell rules; those commands will ask each time")
    report_legacy_credentials()
    check_requirements()
    print("Done. Restart Claude Code, then in a project folder run: sdlc init --board <Trello board URL>")


if __name__ == "__main__":
    sys.exit(main())
