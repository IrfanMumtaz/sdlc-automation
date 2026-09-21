"""
Knowledge base helpers shared by the KB MCP server and the `sdlc` command:
bootstrapping a project's knowledge base from kb_template/, and listing which
project docs are written.

The knowledge base is ordinary files inside the project. Agents write them;
people review the changes and commit them with the rest of the project.
"""

import json
import shutil
from pathlib import Path

import config

# Project-level sections: singleton docs, written only by the Knowledge Base Writer.
PROJECT_SECTIONS = ("product", "architecture", "patterns")


def bootstrap(kb_root):
    """
    Copy the bundled template into kb_root if it has no registry.json yet.
    A deterministic file-exists check, not an agent decision; a no-op once the
    knowledge base exists. Returns True if it bootstrapped.
    """
    kb_root = Path(kb_root)
    if (kb_root / "registry.json").exists():
        return False
    if not config.KB_TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Bundled KB template not found at {config.KB_TEMPLATE_DIR}.")
    kb_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(config.KB_TEMPLATE_DIR, kb_root, dirs_exist_ok=True)
    return True


def project_doc_status(kb_root):
    """One line per registered project doc: path, written/template, tags."""
    registry = json.loads((Path(kb_root) / "registry.json").read_text())
    lines = []
    for section in PROJECT_SECTIONS:
        for name, entry in sorted(registry.get(section, {}).items()):
            status = entry.get("status", "template")
            if entry.get("updated"):
                status += f" {entry['updated']}"
            tags = ", ".join(entry.get("tags", []))
            lines.append(f"{entry['file']}  [{status}]" + (f"  tags: {tags}" if tags else ""))
    return "\n".join(lines)
