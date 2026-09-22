#!/usr/bin/env python3
"""
sdlc — the SDLC pipeline's command line. Run it from anywhere inside a project.

  sdlc init --board <trello board URL or id>   set up the project in the current folder
  sdlc status                                  project settings and knowledge base status
  sdlc next [--only PO,BA] [--ticket <url|id>] | finish | recover
                                               router commands used by /sdlc
  sdlc skip --ticket <url|id> --stages "UI/UX" skip stages for one ticket
  sdlc skip --project --stages "UI/UX"         skip stages for every ticket
  sdlc skip --show                             what's skipped right now
  sdlc render <page.html>                      render a static page to desktop/mobile PNGs
  sdlc draft save|show|list|clear|note          /sdlc-kickoff's work in progress, so a session can be resumed
  sdlc mcp kb|trello [options]                 start an agent's MCP server (used by agent files)

install.py puts this on PATH as `sdlc`.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent  # resolves the ~/.local/bin symlink
sys.path.insert(0, str(ENGINE_ROOT))

import config


def emit(result):
    print(json.dumps(result, indent=2))


def board_ref_from(value):
    """Accept a board URL (https://trello.com/b/<shortLink>/name), short link or id."""
    m = re.search(r"trello\.com/b/([A-Za-z0-9]+)", value)
    return m.group(1) if m else value.strip()


def ticket_id_from(value):
    """
    Accept a card URL (https://trello.com/c/<shortLink>/5-name), a short link or
    an id, and return the card's real id — which is what the board listing and
    the state file are keyed on, so a short link has to be resolved first.
    """
    import trello_client

    m = re.search(r"trello\.com/c/([A-Za-z0-9]+)", value)
    ref = m.group(1) if m else value.strip()
    try:
        return trello_client.get_card(ref)["id"]
    except Exception as exc:  # noqa: BLE001 - a bad reference should read as a bad reference
        sys.exit(f"Trello has no card '{ref}': {exc}\n"
                 f"Pass the card's URL (https://trello.com/c/...), its short link, or its id.")


CREDENTIALS_HELP = """Trello needs an API key and a token, both from your Power-Up's API key page:
  https://trello.com/power-ups/admin  ->  your Power-Up  ->  API key
Copy the API key, then use the "Token" link on that page (the token starts with
ATTA) — not the Secret. The token reaches every board your Trello account can
see; revoke it any time at https://trello.com/my/account under Applications."""


def ask_for_credentials(where):
    """Prompt for a Trello key and token, check them, and save them to `where`."""
    import getpass

    import trello_client

    if not sys.stdin.isatty():
        sys.exit(f"No Trello credentials. Put TRELLO_KEY and TRELLO_TOKEN in {where}, "
                 f"or run `sdlc init` in a terminal to be asked for them.\n\n{CREDENTIALS_HELP}")
    print(CREDENTIALS_HELP + "\n")
    key = input("Trello API key: ").strip()
    token = getpass.getpass("Trello token (not shown): ").strip()
    if not key or not token:
        sys.exit("Both the key and the token are needed.")

    config.TRELLO_KEY, config.TRELLO_TOKEN = key, token
    try:
        member = trello_client.whoami()
    except Exception as exc:  # noqa: BLE001 - any failure here means unusable credentials
        sys.exit(f"Trello rejected those credentials: {exc}\nNothing was saved; check them and rerun `sdlc init`.")

    where.parent.mkdir(parents=True, exist_ok=True)
    lines = [l for l in (where.read_text().splitlines() if where.is_file() else [])
             if not l.startswith(("TRELLO_KEY=", "TRELLO_TOKEN="))]
    where.write_text("\n".join([*lines, f"TRELLO_KEY={key}", f"TRELLO_TOKEN={token}"]) + "\n")
    where.chmod(0o600)
    print(f"Credentials check out as Trello user '{member.get('username')}'; saved to {where} (gitignored)\n")


def git_ignores(path):
    """
    False when `path` is inside a git repository that would commit it: it isn't
    ignored, or it's already tracked. True otherwise, including outside a repo.
    """
    try:
        result = subprocess.run(["git", "check-ignore", "-q", path.name], cwd=path.parent,
                                capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return result.returncode != 1  # 0 ignored, 1 not ignored or tracked, 128 not a repo


def cmd_init(args):
    import knowledge_base
    import trello_client

    root = Path.cwd().resolve()
    existing = config.find_project_root(root)
    if existing and existing != root and not args.force:
        sys.exit(f"{root} is inside the SDLC project at {existing}. Run init there, or pass --force "
                 f"to create a separate project here.")
    sdlc_dir = root / config.PROJECT_DIR_NAME
    # Ignore the credentials file before anything is written to it.
    config.ensure_gitignore(sdlc_dir)
    # This project's own credentials, never those of a project it sits inside.
    config.TRELLO_KEY, config.TRELLO_TOKEN = config.trello_credentials(root)
    if args.reauth or not (config.TRELLO_KEY and config.TRELLO_TOKEN):
        ask_for_credentials(config.credentials_file(root))

    config_path = root / config.PROJECT_DIR_NAME / config.PROJECT_CONFIG_NAME
    current = json.loads(config_path.read_text()) if config_path.is_file() else {}

    board = trello_client.get_board(board_ref_from(args.board))
    lists = {}
    for lst in trello_client.get_open_lists(board["id"]):
        lists.setdefault(lst["name"], lst["id"])
    missing = [name for name in config.BOARD_LISTS if name not in lists]
    if missing and not args.create_lists:
        sys.exit(f"Board '{board['name']}' is missing these lists: {missing}.\n"
                 f"Rename existing lists to match, or rerun with --create-lists to add them.")
    for name in missing:
        lists[name] = trello_client.create_list(board["id"], name)["id"]

    # Priority labels people apply by hand; the router runs labelled cards first.
    have_labels = {(l.get("name") or "").strip() for l in trello_client.get_board_labels(board["id"])}
    new_labels = [p for p in config.PRIORITY_LABELS if p not in have_labels]
    for name in new_labels:
        trello_client.create_label(board["id"], name, config.PRIORITY_LABEL_COLORS[name])

    settings = {**config.PROJECT_DEFAULTS, **current}
    for key in ("max_active_agents", "bounce_cap", "knowledge_base"):
        if getattr(args, key) is not None:
            settings[key] = getattr(args, key)
    project = {
        "project": args.name or current.get("project") or root.name,
        "provider": "trello",
        "trello_board_id": board["id"],
        "trello_board_name": board["name"],
        "trello_board_url": board.get("url"),
        "trello_lists": {name: lists[name] for name in config.BOARD_LISTS},
        **{k: settings[k] for k in config.PROJECT_DEFAULTS},
    }

    config_path.write_text(json.dumps(project, indent=2) + "\n")
    kb_root = (root / project["knowledge_base"]).resolve()
    created_kb = knowledge_base.bootstrap(kb_root)

    print(f"{'Updated' if current else 'Created'} {config_path}")
    print(f"  board: {board['name']} ({board['id']})" + (f"; created lists: {missing}" if missing else ""))
    print(f"  priority labels: " + (f"created {new_labels}" if new_labels else "already on the board")
          + f" — apply them by hand; cards without one run in list order")
    print(f"  knowledge base: {kb_root}" + (" (created from template)" if created_kb else ""))
    print(f"  settings: " + ", ".join(f"{k}={project[k]}" for k in config.PROJECT_DEFAULTS))
    credentials = config.credentials_file(root)
    if credentials.is_file() and not git_ignores(credentials):
        print(f"WARNING: git would commit {credentials}, which holds your Trello token. It's probably "
              f"already tracked: `git rm --cached .sdlc/.env`, then revoke and replace the token.")
    print("Commit .sdlc/config.json and the knowledge base with the project; .sdlc/.env stays out of git. "
          "Next: /sdlc-kickoff in Claude Code.")


def cmd_status(_args):
    import knowledge_base

    config.require_project()
    s = config.PROJECT_SETTINGS
    created_kb = knowledge_base.bootstrap(config.KB_REPO_PATH)
    credentials_file = config.credentials_file(config.PROJECT_ROOT)
    if not (config.TRELLO_KEY and config.TRELLO_TOKEN):
        credentials = (f"MISSING: run `sdlc init --board <board URL>` in a terminal, or put TRELLO_KEY "
                       f"and TRELLO_TOKEN in {credentials_file}")
    elif os.environ.get("TRELLO_KEY") and os.environ.get("TRELLO_TOKEN"):
        credentials = "from the environment"
    else:
        credentials = "in .sdlc/.env"
    print(f"Project: {s['project']} ({config.PROJECT_ROOT})")
    print(f"Trello board: {s.get('trello_board_name', '?')} ({config.BOARD_ID}); credentials {credentials}")
    if credentials_file.is_file() and not git_ignores(credentials_file):
        print(f"WARNING: git would commit {credentials_file}, which holds a Trello token. Rerun `sdlc init` "
              f"to fix .sdlc/.gitignore; if it's already tracked, `git rm --cached .sdlc/.env` and replace the token.")
    print("Settings: " + ", ".join(f"{k}={s[k]}" for k in config.PROJECT_DEFAULTS))
    print("Stage agents built: " + ", ".join(f"{role} ({name})" for role, name in config.AGENT_SUBAGENTS.items()))
    print("Stages this project runs: " + (", ".join(config.resolve_stages(config.STAGES)) if config.STAGES else "all built stages"))
    print("Priority: " + " > ".join(config.PRIORITY_LABELS) + " > unlabelled, then top of the list "
          "(Trello labels, set by hand)")
    print("Skipped for every ticket: " + (", ".join(config.project_skips()) or "nothing")
          + "  (`sdlc skip --show` includes single tickets)")
    print("Model overrides: " + (", ".join(f"{k}={v}" for k, v in config.MODELS.items()) if config.MODELS
                                 else "none (each agent uses the model in its own file)"))
    print(f"Design workspace: {config.DESIGN_WORKSPACE_PATH}")
    print(f"Knowledge base: {config.KB_REPO_PATH}" + (" (just created from template)" if created_kb else ""))
    print(knowledge_base.project_doc_status(config.KB_REPO_PATH))


def cmd_router(args):
    config.require_project()
    import orchestrator

    if args.command == "next":
        try:
            config.resolve_stages(args.only)  # reject bad stage names before touching the board
        except ValueError as exc:
            sys.exit(str(exc))
        ticket_id = ticket_id_from(args.ticket) if args.ticket else None
        emit(orchestrator.cmd_next(args.only, ticket_id))
    elif args.command == "finish":
        emit(orchestrator.cmd_finish(args.agent, args.ticket))
    else:
        emit(orchestrator.cmd_recover())


def cmd_skip(args):
    """
    Mark stages to skip — for one ticket, or for every ticket in the project.
    A skipped stage runs no agent: the router moves the card straight to the
    next stage and records it on the card.
    """
    config.require_project()
    import trello_client
    from state_store import locked, load_state, save_state, load_seen_comments, save_seen_comments
    from state_store import add_ticket_skips, remove_ticket_skips, ticket_skips

    if not (args.ticket or args.project or args.show):
        sys.exit("Say what to skip for: --ticket <url|id>, --project, or --show to see what's skipped.")

    if args.show:
        print("Skipped for every ticket: " + (", ".join(config.project_skips()) or "nothing"))
        with locked():
            per_ticket = load_state().get("skips", {})
        if not per_ticket:
            print("Skipped for single tickets: nothing")
            return
        print("Skipped for single tickets:")
        for ticket_id, stages in per_ticket.items():
            try:
                name = trello_client.get_card(ticket_id)["name"]
            except Exception:  # noqa: BLE001 - a deleted card shouldn't break the listing
                name = "(card not found)"
            print(f"  {name} ({ticket_id}): {', '.join(stages)}")
        return

    try:
        stages = config.resolve_skip_stages(args.stages)
    except ValueError as exc:
        sys.exit(str(exc))
    if not stages and not args.clear:
        sys.exit(f"Name the stages to skip with --stages, e.g. --stages 'UI/UX,Code Analyst'.\n"
                 f"Valid stages: {config.AGENT_SEQUENCE}")
    if "PO" in stages:
        print("WARNING: skipping PO means no spec and no feature folder is ever created, so every "
              "later stage escalates. Skip it only for a ticket the PO has already written up.")

    if args.project:
        config_path = config.PROJECT_ROOT / config.PROJECT_DIR_NAME / config.PROJECT_CONFIG_NAME
        settings = json.loads(config_path.read_text())
        current = config.resolve_skip_stages(settings.get("skip_stages"))
        updated = ([s for s in current if s not in stages] if args.clear
                   else [s for s in config.AGENT_SEQUENCE if s in set(current) | set(stages)])
        settings["skip_stages"] = updated
        config_path.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"{config_path}: skip_stages = {updated or 'nothing'}")
        print("Commit .sdlc/config.json so the rest of the team skips the same stages.")
        return

    ticket_id = ticket_id_from(args.ticket)
    with locked():
        state, seen = load_state(), load_seen_comments()
        if args.clear:
            remaining = remove_ticket_skips(state, ticket_id, stages or None)
            text = f'[UNSKIP] ticket=#{ticket_id} stages="{",".join(stages) if stages else "all"}"'
        else:
            remaining = add_ticket_skips(state, ticket_id, stages)
            text = f'[SKIP] ticket=#{ticket_id} stages="{",".join(stages)}"'
            if args.reason:
                text += f' reason="{args.reason.replace(chr(34), chr(39))}"'
        # Record it on the card too, so the board explains itself and the skip
        # survives losing .sdlc/state/.
        comment = trello_client.add_comment(ticket_id, text)
        seen.setdefault(ticket_id, []).append(comment["id"])
        save_state(state)
        save_seen_comments(seen)

    card_name = trello_client.get_card(ticket_id)["name"]
    print(f"{card_name} ({ticket_id}) now skips: " + (", ".join(remaining) or "nothing"))
    print("Recorded on the card. It takes effect at the next `sdlc next`.")


DRAFT_SECTIONS = ("product", "architecture", "patterns")


def draft_dir():
    config.require_project()
    return config.PROJECT_ROOT / config.PROJECT_DIR_NAME / "kickoff"


def draft_path(doc):
    """Drafts mirror knowledge base paths: product/overview.md, patterns/ui-patterns.md, ..."""
    doc = doc.strip().removesuffix(".md")
    parts = doc.split("/")
    if len(parts) != 2 or parts[0] not in DRAFT_SECTIONS or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", parts[1]):
        sys.exit(f"invalid doc '{doc}'. Use <section>/<name>, e.g. product/overview, with section one of "
                 f"{list(DRAFT_SECTIONS)}.")
    return draft_dir() / "drafts" / parts[0] / f"{parts[1]}.md"


def cmd_draft(args):
    root = draft_dir()
    notes = root / "notes.md"

    if args.draft_command == "save":
        path = draft_path(args.doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sys.stdin.read())
        print(f"Saved draft {path.relative_to(config.PROJECT_ROOT)}")

    elif args.draft_command == "show":
        path = draft_path(args.doc)
        if not path.is_file():
            sys.exit(f"no draft for {args.doc}")
        print(path.read_text(), end="")

    elif args.draft_command == "note":
        notes.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with notes.open("a") as f:
            f.write(f"\n## {stamp}\n{args.text.strip()}\n")
        print(f"Appended to {notes.relative_to(config.PROJECT_ROOT)}")

    elif args.draft_command == "clear":
        targets = [draft_path(args.doc)] if args.doc else sorted((root / "drafts").rglob("*.md"))
        for path in targets:
            path.unlink(missing_ok=True)
        if not args.doc:
            notes.unlink(missing_ok=True)
        print(f"Cleared {len(targets)} draft(s)" + ("" if args.doc else " and the notes"))

    else:  # list
        drafts = sorted((root / "drafts").rglob("*.md")) if (root / "drafts").exists() else []
        if not drafts and not notes.exists():
            print("No kickoff drafts saved for this project.")
            return
        print(f"Kickoff drafts in {root.relative_to(config.PROJECT_ROOT)}:")
        for path in drafts:
            doc = path.relative_to(root / "drafts")
            changed = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  {doc}  ({len(path.read_text().splitlines())} lines, saved {changed})")
        if notes.exists():
            print(f"  notes.md  ({len(notes.read_text().splitlines())} lines)")
            print("\nLatest notes:")
            print("\n".join(notes.read_text().splitlines()[-25:]))


def cmd_render(args):
    import mockup_render

    path = Path(args.html)
    path.write_text(mockup_render.make_static(path.read_text()))
    for png in mockup_render.render_viewports(path, {"desktop": args.desktop_height, "mobile": args.mobile_height}):
        print(png)


def cmd_mcp(args, rest):
    sys.path.insert(0, str(ENGINE_ROOT / "mcp_servers"))
    sys.argv = [f"sdlc mcp {args.server}", *rest]
    if args.server == "kb":
        import kb_server
        kb_server.main()
    else:
        import trello_server
        trello_server.main()


def main():
    parser = argparse.ArgumentParser(prog="sdlc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="set up the project in the current folder")
    init.add_argument("--board", required=True, help="Trello board URL, short link or id")
    init.add_argument("--name", help="project name (default: folder name)")
    init.add_argument("--create-lists", action="store_true", help="add missing stage lists to the board")
    init.add_argument("--knowledge-base", dest="knowledge_base", help="knowledge base folder, relative to the project")
    init.add_argument("--max-active-agents", dest="max_active_agents", type=int)
    init.add_argument("--bounce-cap", dest="bounce_cap", type=int)
    init.add_argument("--reauth", action="store_true", help="ask for this project's Trello credentials again")
    init.add_argument("--force", action="store_true", help="allow a project inside another project")

    sub.add_parser("status", help="project settings and knowledge base status")
    nxt = sub.add_parser("next", help="process new comments and pick the next ticket")
    nxt.add_argument("--only", help="limit this run to these stages, e.g. 'PO,BA,UIUX' (default: all built stages)")
    nxt.add_argument("--ticket", help="work only this ticket (card URL, short link or id), whatever stage it's in")
    finish = sub.add_parser("finish", help="close out an agent run")
    finish.add_argument("--agent", required=True, choices=config.AGENT_SEQUENCE)
    finish.add_argument("--ticket", required=True)
    sub.add_parser("recover", help="close out runs an interrupted session never finished")

    skip = sub.add_parser("skip", help="skip stages for one ticket or for every ticket")
    skip.add_argument("--ticket", help="skip for this ticket only (card URL, short link or id)")
    skip.add_argument("--project", action="store_true", help="skip for every ticket (writes .sdlc/config.json)")
    skip.add_argument("--stages", help="stages to skip, e.g. 'UI/UX,Code Analyst'")
    skip.add_argument("--reason", help="why, recorded on the card")
    skip.add_argument("--clear", action="store_true", help="stop skipping; without --stages, clears them all")
    skip.add_argument("--show", action="store_true", help="show what's skipped right now")

    render = sub.add_parser("render", help="render a static HTML page to desktop and mobile PNGs")
    render.add_argument("html")
    render.add_argument("--desktop-height", type=int, default=900)
    render.add_argument("--mobile-height", type=int, default=844)

    draft = sub.add_parser("draft", help="/sdlc-kickoff work in progress for this project")
    draft_sub = draft.add_subparsers(dest="draft_command", required=True)
    save = draft_sub.add_parser("save", help="save a draft doc, read from stdin")
    save.add_argument("doc", help="e.g. product/overview")
    show = draft_sub.add_parser("show", help="print a saved draft")
    show.add_argument("doc")
    draft_sub.add_parser("list", help="list saved drafts and the latest notes")
    note = draft_sub.add_parser("note", help="append to the session notes")
    note.add_argument("text")
    clear = draft_sub.add_parser("clear", help="delete drafts once they're recorded")
    clear.add_argument("--doc", help="just this one (default: all drafts and notes)")

    mcp = sub.add_parser("mcp", help="start an agent MCP server (used by agent files)")
    mcp.add_argument("server", choices=["kb", "trello"])

    args, rest = parser.parse_known_args()
    if args.command != "mcp" and rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")

    if args.command == "init":
        cmd_init(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command in ("next", "finish", "recover"):
        cmd_router(args)
    elif args.command == "skip":
        cmd_skip(args)
    elif args.command == "render":
        cmd_render(args)
    elif args.command == "draft":
        cmd_draft(args)
    else:
        cmd_mcp(args, rest)


if __name__ == "__main__":
    main()
