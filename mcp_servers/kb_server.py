"""
Stdio MCP server for touching the project's knowledge base. This is how role
scoping is actually enforced — not by trusting the agent to behave, but by
only exposing the operations and file names each role is allowed to touch.

Each agent starts its own copy, through the `sdlc` command, with its role's
write access:

    sdlc mcp kb --role PO --allow definition.md,spec.md --append-decisions
    sdlc mcp kb --role "Knowledge Base Writer" --project-write

--allow lists the feature docs the role may write; any other doc name is
rejected in code, and only a role that owns definition.md (PO) can create
feature folders. --append-decisions adds the append-only decisions.md tool
for pipeline stages, and --mockups the UI/UX mockup renderer. --project-write
adds the only tools that can write product/, architecture/, patterns/ and
their registry entries; only the Knowledge Base Writer starts the server with
it. Every role can read project and feature docs.

The project is found from the directory Claude Code runs in; see config.py.
Kickoff agents work on the project checkout's knowledge base, which is
bootstrapped from kb_template/ when the server starts if it doesn't exist yet,
and a person commits it.

Pipeline stages pass --ticket-worktree: every call then goes to the knowledge
base inside the worktree of the ticket the router dispatched to this stage
(worktrees.py), bound on the first call and kept for the server's life. The
router commits those changes on the ticket's branch and pushes it when the
stage finishes; agents never commit.
"""

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # engine root

from mcp.server.fastmcp import FastMCP, Image

import config
import knowledge_base
import mockup_render
import worktrees
from knowledge_base import PROJECT_SECTIONS

config.require_project()

# Set in main(): the stage whose dispatched ticket's worktree this server works
# in, or None to work on the project checkout (kickoff agents).
TICKET_STAGE = None
_bound_root = None


def kb_root():
    """The knowledge base this server reads and writes."""
    global _bound_root
    if TICKET_STAGE is None:
        return config.KB_REPO_PATH
    if _bound_root is None:
        ticket_id = worktrees.dispatched_ticket(TICKET_STAGE)
        root = worktrees.ticket_kb_root(ticket_id) if ticket_id else None
        if root is None or not (root / "registry.json").is_file():
            raise ValueError(f"no ticket worktree is prepared for the {TICKET_STAGE} stage. Stage agents only run "
                             f"when /sdlc dispatches them; say so in your report and stop.")
        _bound_root = root
    return _bound_root


def _rel(path):
    return path.relative_to(kb_root())


ALL_FEATURE_DOCS = {
    "definition.md", "spec.md", "technical.md", "ux.md",
    "flow.md", "test-scenarios.md", "decisions.md", "deployment.md",
}

# Design system files beyond patterns/design-system.md, copied from the /sdlc-kickoff
# design workspace by the Knowledge Base Writer: workspace path -> KB file name.
DESIGN_WORKSPACE = config.DESIGN_WORKSPACE_PATH
DESIGN_ASSET_SOURCES = {
    ".impeccable/design.json": "design.json",
    "style-guide.html": "style-guide.html",
    "style-guide-desktop.png": "style-guide-desktop.png",
    "style-guide-mobile.png": "style-guide-mobile.png",
}
MOCKUP_FILE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.(html|png)")


SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _design_assets_dir():
    return kb_root() / "patterns" / "design-system"


def _check_slug(slug, what="slug"):
    """
    Reject anything but plain kebab-case, so a name like '../../patterns' can't
    escape its folder and bypass the per-role write scoping.
    """
    if not SLUG_PATTERN.fullmatch(slug):
        raise ValueError(f"invalid {what} '{slug}'. Use lowercase kebab-case, e.g. 'user-notifications'.")


def _feature_dir(slug):
    _check_slug(slug)
    return kb_root() / "features" / slug


def _mockup_path(slug, file_name):
    if not MOCKUP_FILE_PATTERN.fullmatch(file_name):
        raise ValueError(f"invalid mockup file '{file_name}'. Expected e.g. 'export-dialog-desktop.png'.")
    path = _feature_dir(slug) / "mockups" / file_name
    if not path.exists():
        raise ValueError(f"{_rel(path)} does not exist")
    return path


def _file_content(path):
    """PNG files come back as images the agent can see; everything else as text."""
    return Image(path=str(path)) if path.suffix == ".png" else path.read_text()


def _project_doc_path(section, name):
    if section not in PROJECT_SECTIONS:
        raise ValueError(f"unknown section '{section}'. Valid sections: {list(PROJECT_SECTIONS)}")
    _check_slug(name, "doc name")
    return kb_root() / section / f"{name}.md"


def _load_registry():
    return json.loads((kb_root() / "registry.json").read_text())


def _save_registry(registry):
    (kb_root() / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")


def build_server(role_name: str, allowed_write_docs: set[str], project_write: bool,
                 append_decisions: bool = False, mockups: bool = False) -> FastMCP:
    """
    role_name: used in tool descriptions, error messages and decision log entries.
    allowed_write_docs: subset of ALL_FEATURE_DOCS this role may write to.
                         e.g. PO -> {"definition.md", "spec.md"}
    project_write: register the project-doc write tools (Knowledge Base Writer only).
    append_decisions: register append_decision (pipeline stage agents).
    mockups: register save_mockup (UI/UX stage).
    """
    invalid = allowed_write_docs - ALL_FEATURE_DOCS
    if invalid:
        raise ValueError(f"Unknown doc names in allowed_write_docs: {invalid}")

    mcp = FastMCP("kb")

    @mcp.tool()
    def list_project_docs() -> str:
        """List the project-level docs (product/, architecture/, patterns/) with
        whether each is written or still an unfilled template, and its tags."""
        return knowledge_base.project_doc_status(kb_root())

    @mcp.tool()
    def read_project_doc(section: str, name: str) -> str:
        """Read a project-level doc, e.g. section='product', name='overview'
        for product/overview.md."""
        path = _project_doc_path(section, name)
        if not path.exists():
            raise ValueError(f"{_rel(path)} does not exist")
        return path.read_text()

    @mcp.tool()
    def read_feature_doc(slug: str, doc_name: str) -> str:
        """Read a document from a feature's folder (any of the 8 standard docs)."""
        if doc_name not in ALL_FEATURE_DOCS:
            raise ValueError(f"unknown doc '{doc_name}'. Valid docs: {sorted(ALL_FEATURE_DOCS)}")
        path = _feature_dir(slug) / doc_name
        if not path.exists():
            raise ValueError(f"{_rel(path)} does not exist")
        return path.read_text()

    @mcp.tool()
    def find_feature(ticket_id: str) -> str:
        """Find the feature slug registered for a Trello ticket_id."""
        for slug, entry in _load_registry()["features"].items():
            if entry.get("ticket_id") == ticket_id:
                return f"Feature slug: {slug}"
        raise ValueError(f"no feature is registered for ticket {ticket_id}")

    @mcp.tool()
    def view_mockup(slug: str, file_name: str):
        """View a feature's mockup from features/{slug}/mockups/: a PNG screenshot
        (e.g. 'export-dialog-desktop.png') or its HTML source ('export-dialog.html')."""
        return _file_content(_mockup_path(slug, file_name))

    @mcp.tool()
    def read_design_asset(file_name: str):
        """Read a design system asset from patterns/design-system/: 'design.json'
        (token extensions and component HTML/CSS snippets), 'style-guide.html',
        or the screenshots 'style-guide-desktop.png' / 'style-guide-mobile.png'."""
        if file_name not in DESIGN_ASSET_SOURCES.values():
            raise ValueError(f"unknown design asset '{file_name}'. Valid: {sorted(DESIGN_ASSET_SOURCES.values())}")
        path = _design_assets_dir() / file_name
        if not path.exists():
            raise ValueError(f"{_rel(path)} does not exist; the design system hasn't been recorded")
        return _file_content(path)

    # PO creates feature folders; every other stage finds them with find_feature.
    if "definition.md" in allowed_write_docs:
        _add_feature_create_tool(mcp)
    if allowed_write_docs:
        _add_feature_write_tool(mcp, role_name, allowed_write_docs)
    if append_decisions:
        _add_decision_tool(mcp, role_name)
    if mockups:
        _add_mockup_tool(mcp)
    if project_write:
        _add_project_write_tools(mcp)
    return mcp


def _add_feature_create_tool(mcp):

    @mcp.tool()
    def get_or_create_feature(ticket_id: str, proposed_slug: str, tags: str) -> str:
        """Find the feature slug already registered for a ticket_id, or create
        a new feature folder (from the template) and register it if none
        exists yet. `tags` is a comma-separated list."""
        registry = _load_registry()

        # look for an existing feature already tied to this ticket
        for slug, entry in registry["features"].items():
            if entry.get("ticket_id") == ticket_id:
                return f"Existing feature slug: {slug}"

        feature_dir = _feature_dir(proposed_slug)
        if feature_dir.exists():
            raise ValueError(f"slug '{proposed_slug}' already exists but isn't linked to ticket "
                             f"{ticket_id}. Choose a different slug.")

        shutil.copytree((kb_root() / "features" / "_template"), feature_dir)
        registry["features"][proposed_slug] = {
            "ticket_id": ticket_id,
            "status": "backlog",
            "docs": sorted(str(_rel(p)) for p in feature_dir.glob("*.md")),
            "patterns_used": [],
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
        }
        _save_registry(registry)
        return f"Created and registered new feature slug: {proposed_slug}"


def _add_feature_write_tool(mcp, role_name, allowed_write_docs):

    @mcp.tool(description=(
        f"Write (overwrite) a document in a feature's folder. This {role_name} "
        f"agent may only write: {sorted(allowed_write_docs)}."
    ))
    def write_feature_doc(slug: str, doc_name: str, content: str) -> str:
        if doc_name not in allowed_write_docs:
            raise ValueError(f"{role_name} is not permitted to write '{doc_name}'. "
                             f"Allowed: {sorted(allowed_write_docs)}")
        feature_dir = _feature_dir(slug)
        if not feature_dir.exists():
            raise ValueError(f"feature folder for slug '{slug}' doesn't exist. Call get_or_create_feature first.")
        path = feature_dir / doc_name
        path.write_text(content)
        return f"Wrote {_rel(path)}"


def _add_decision_tool(mcp, role_name):

    @mcp.tool(description=(
        f"Append one entry to a feature's decisions.md, dated and signed as {role_name}. "
        f"Append-only: earlier entries can't be changed. `entry` is '<what happened> | <why>'."
    ))
    def append_decision(slug: str, entry: str) -> str:
        path = _feature_dir(slug) / "decisions.md"
        if not path.exists():
            raise ValueError(f"{_rel(path)} does not exist")
        line = " ".join(entry.split())  # one line per entry
        with path.open("a") as f:
            f.write(f"- {datetime.date.today().isoformat()} | {role_name} | {line}\n")
        return f"Appended to {_rel(path)}"


def _add_mockup_tool(mcp):

    @mcp.tool()
    def save_mockup(slug: str, name: str, html: str, desktop_height: int = 900, mobile_height: int = 844):
        """Save a static HTML mockup as features/{slug}/mockups/{name}.html and render
        it with headless Chrome at desktop (1440px wide) and mobile (390px wide).
        Returns both screenshots so you can check them. The HTML must be
        self-contained: inline CSS, no scripts, no external URLs (a
        Content-Security-Policy blocks them). Heights set how much of the page
        is captured (max 6000). Saving the same name again replaces the files."""
        _check_slug(name, "mockup name")
        feature_dir = _feature_dir(slug)
        if not feature_dir.exists():
            raise ValueError(f"feature folder for slug '{slug}' doesn't exist")
        html_path = feature_dir / "mockups" / f"{name}.html"
        html_path.parent.mkdir(exist_ok=True)
        html_path.write_text(mockup_render.make_static(html))
        pngs = mockup_render.render_viewports(html_path, {"desktop": desktop_height, "mobile": mobile_height})
        listing = ", ".join(str(_rel(p)) for p in [html_path, *pngs])
        return [f"Saved {listing}", *(Image(path=str(p)) for p in pngs)]


def _add_project_write_tools(mcp):
    """Project doc write tools: Knowledge Base Writer only."""

    @mcp.tool()
    def write_project_doc(section: str, name: str, content: str, tags: str = "") -> str:
        """Write (overwrite) a project-level doc, e.g. section='product',
        name='overview' for product/overview.md, and mark it written in
        registry.json. `tags` is a comma-separated list; empty keeps the
        existing tags. Creates the registry entry for a new doc."""
        path = _project_doc_path(section, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

        registry = _load_registry()
        entry = registry.setdefault(section, {}).setdefault(name, {})
        entry["file"] = str(_rel(path))
        new_tags = [t.strip() for t in tags.split(",") if t.strip()]
        if new_tags:
            entry["tags"] = new_tags
        entry["status"] = "written"
        entry["updated"] = datetime.date.today().isoformat()
        _save_registry(registry)
        return f"Wrote {entry['file']} and updated registry.json"

    @mcp.tool()
    def copy_design_assets() -> str:
        """Copy the approved design system's supporting files from the /sdlc-kickoff
        design workspace into patterns/design-system/: the token sidecar
        (.impeccable/design.json) and the style guide HTML and screenshots.
        Record patterns/design-system.md itself with write_project_doc."""
        _design_assets_dir().mkdir(parents=True, exist_ok=True)
        copied, missing = [], []
        for source, dest in DESIGN_ASSET_SOURCES.items():
            src = DESIGN_WORKSPACE / source
            if src.is_file():
                shutil.copyfile(src, _design_assets_dir() / dest)
                copied.append(dest)
            else:
                missing.append(source)
        if not copied:
            raise ValueError(f"no design assets found in the design workspace {DESIGN_WORKSPACE}")
        registry = _load_registry()
        entry = registry.setdefault("patterns", {}).setdefault(
            "design-system", {"file": "patterns/design-system.md", "status": "template"})
        entry["assets"] = sorted(str(_rel(_design_assets_dir() / d)) for d in copied)
        _save_registry(registry)
        return f"Copied {copied} to patterns/design-system/" + (f"; not found in workspace: {missing}" if missing else "")


def main():
    parser = argparse.ArgumentParser(prog="sdlc mcp kb")
    parser.add_argument("--role", required=True)
    parser.add_argument("--allow", default="", help="comma-separated feature doc names this role may write")
    parser.add_argument("--project-write", action="store_true",
                        help="allow writing product/, architecture/, patterns/ (Knowledge Base Writer only)")
    parser.add_argument("--append-decisions", action="store_true",
                        help="allow appending to features' decisions.md (pipeline stage agents)")
    parser.add_argument("--mockups", action="store_true",
                        help="allow saving and rendering feature mockups (UI/UX stage)")
    parser.add_argument("--ticket-worktree", action="store_true",
                        help="work in the worktree of the ticket dispatched to the --role stage (pipeline stages)")
    args = parser.parse_args()

    global TICKET_STAGE
    if args.ticket_worktree:
        if args.role not in config.AGENT_SEQUENCE:
            parser.error(f"--ticket-worktree needs --role to be a stage: {config.AGENT_SEQUENCE}")
        TICKET_STAGE = args.role

    allowed = {d.strip() for d in args.allow.split(",") if d.strip()}
    server = build_server(args.role, allowed, args.project_write, args.append_decisions, args.mockups)
    if TICKET_STAGE is None:
        knowledge_base.bootstrap(config.KB_REPO_PATH)
    server.run()


if __name__ == "__main__":
    main()
