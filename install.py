#!/usr/bin/env python3
"""
Install the SDLC pipeline for your user, so /sdlc and /sdlc-kickoff work in any
project folder:

    python3 install.py              install or update (safe to rerun)
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
  4. sets up Trello credentials in ~/.config/sdlc/.env, moving this folder's
     .env there if it has one

It never overwrites a file it didn't create: an existing agent, skill or
command with the same name is reported and skipped.
"""

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
HOME = Path.home()
BIN_LINK = HOME / ".local" / "bin" / "sdlc"
CLAUDE_DIR = HOME / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"
USER_ENV = HOME / ".config" / "sdlc" / ".env"

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
    for link, target in links():
        link.parent.mkdir(parents=True, exist_ok=True)
        if ours(link):
            link.unlink()
        elif link.exists() or link.is_symlink():
            print(f"  skipped {link}: already exists and isn't from this engine")
            continue
        try:
            link.symlink_to(target)
            print(f"  linked {link}")
        except OSError:  # e.g. Windows without developer mode: copy instead
            shutil.copytree(target, link) if target.is_dir() else shutil.copyfile(target, link)
            print(f"  copied {link} (no symlinks here: rerun install.py after changing the engine)")
    (ENGINE / "sdlc.py").chmod(0o755)
    # remove links to agents or skills that no longer exist in the engine
    for folder in (CLAUDE_DIR / "agents", CLAUDE_DIR / "skills"):
        for entry in folder.iterdir() if folder.exists() else []:
            if entry.is_symlink() and str(Path(entry.readlink())).startswith(str(ENGINE)) and not entry.exists():
                entry.unlink()
                print(f"  removed stale link {entry}")


def load_settings():
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}


def save_settings(settings):
    if SETTINGS.exists():
        shutil.copyfile(SETTINGS, SETTINGS.with_name("settings.json.sdlc-backup"))
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def install_permissions(with_dev=True):
    settings = load_settings()
    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    wanted = PERMISSIONS + (DEV_PERMISSIONS if with_dev else [])
    stale = [rule for rule in OBSOLETE_PERMISSIONS if rule in allow]
    added = [rule for rule in wanted if rule not in allow]
    if stale:
        allow[:] = [rule for rule in allow if rule not in stale]
    allow.extend(added)
    if added or stale:
        save_settings(settings)
        print(f"  permissions: {len(added)} added, {len(stale)} obsolete removed, in {SETTINGS}")
        for rule in added:
            if rule in DEV_PERMISSIONS:
                print(f"    {rule}  (coding stages; applies to every project)")
    else:
        print("  permissions: already present")
    if not with_dev:
        print("  skipped the coding stages' shell rules; those commands will ask each time")


def install_credentials():
    if USER_ENV.exists():
        print(f"  credentials: {USER_ENV} exists")
        return
    USER_ENV.parent.mkdir(parents=True, exist_ok=True)
    old = ENGINE / ".env"
    if old.exists():
        lines = [l for l in old.read_text().splitlines() if l.split("=", 1)[0].strip() in ("TRELLO_KEY", "TRELLO_TOKEN")]
        USER_ENV.write_text("\n".join(lines) + "\n")
        old.unlink()
        print(f"  credentials: moved TRELLO_KEY/TRELLO_TOKEN from {old} to {USER_ENV}")
    else:
        USER_ENV.write_text("TRELLO_KEY=\nTRELLO_TOKEN=\n")
        print(f"  credentials: fill in TRELLO_KEY and TRELLO_TOKEN in {USER_ENV}")
    USER_ENV.chmod(0o600)


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
    print(f"  kept {USER_ENV} (your Trello credentials); delete it yourself if you no longer need it")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--no-dev-permissions", action="store_true",
                        help="don't allow the coding stages' docker/git/package-manager commands")
    args = parser.parse_args()
    if args.uninstall:
        uninstall()
        return
    install_links()
    install_permissions(with_dev=not args.no_dev_permissions)
    install_credentials()
    check_requirements()
    print("Done. Restart Claude Code, then in a project folder run: sdlc init --board <Trello board URL>")


if __name__ == "__main__":
    sys.exit(main())
