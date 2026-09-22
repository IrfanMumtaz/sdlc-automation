"""
Stdio MCP server that wraps trello_client.py, so an agent's Trello access is
exactly these scoped operations on the project's board — not raw HTTP, not
the full Trello API surface. Every stage subagent starts it inline:

    sdlc mcp trello                    # get_ticket, post_ticket_event, advance_ticket
    sdlc mcp trello --attach-mockups   # + attach_mockup (UI/UX stage)
    sdlc mcp trello --summary          # + update_ticket_summary (PO stage)
    sdlc mcp trello --test-report      # + post_test_report (Automated QA stage)
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # engine root

from mcp.server.fastmcp import FastMCP

import config
import trello_client

config.require_project()
KB_ROOT = config.KB_REPO_PATH
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MOCKUP_PNG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.png")

# The PO's block always sits at the end of a card's description, under this
# heading. Everything above it is the requester's text and is never touched.
SUMMARY_HEADER = "**Spec summary — written by the PO agent.**"
SUMMARY_NOTE = "Anything above this line is kept; this section is rewritten whenever PO runs."
MAX_DESCRIPTION = 16000  # Trello's limit is 16384
MAX_COMMENT = 16000      # the same limit applies to comments

# Automated QA's report opens with this, so it can never be read as an event comment.
TEST_REPORT_HEADER = "**Test report — Automated QA.**"

mcp = FastMCP("trello")


@mcp.tool()
def get_ticket(ticket_id: str) -> str:
    """Fetch a Trello card's title, description, current list name, and comment history."""
    card = trello_client.get_card(ticket_id)
    comments = trello_client.get_card_comments(ticket_id)
    comment_texts = [c.get("data", {}).get("text", "") for c in reversed(comments)]
    current_list = config.LIST_ID_TO_NAME.get(card["idList"], f"UNKNOWN_LIST({card['idList']})")
    return (
        f"Title: {card['name']}\n"
        f"Current list: {current_list}\n\n"
        f"Description:\n{card.get('desc') or '(empty)'}\n\n"
        + ("Comments (oldest first):\n" + "\n---\n".join(comment_texts) if comment_texts
           else "No comments yet on this card.")
    )


@mcp.tool()
def post_ticket_event(ticket_id: str, text: str) -> str:
    """Post a structured event comment on a Trello card. `text` must follow the
    fixed comment schema, e.g. '[AGENT_DONE] agent="PO" ticket=#123 moved_to="BA"'
    or '[BOUNCE] agent="BA" ticket=#123 target="PO" reason="..."'."""
    trello_client.add_comment(ticket_id, text)
    return "Comment posted."


@mcp.tool()
def advance_ticket(ticket_id: str, target_list_name: str) -> str:
    """Move a Trello card to another list by exact list name (e.g. 'BA', 'Human')."""
    if target_list_name not in config.LIST_IDS:
        raise ValueError(f"unknown list name '{target_list_name}'. Valid names: {list(config.LIST_IDS)}")
    trello_client.move_card(ticket_id, config.LIST_IDS[target_list_name])
    return f"Card moved to '{target_list_name}'."


def attach_mockup(ticket_id: str, slug: str, file_name: str) -> str:
    """Attach a rendered mockup screenshot from the knowledge base
    (features/{slug}/mockups/{file_name}, e.g. 'export-dialog-desktop.png') to
    the Trello card. An earlier attachment with the same name is replaced, so
    reruns don't pile up copies."""
    if not SLUG_PATTERN.fullmatch(slug) or not MOCKUP_PNG_PATTERN.fullmatch(file_name):
        raise ValueError("slug must be kebab-case and file_name a kebab-case .png, e.g. 'export-dialog-desktop.png'")
    path = KB_ROOT / "features" / slug / "mockups" / file_name
    if not path.is_file():
        raise ValueError(f"features/{slug}/mockups/{file_name} does not exist; save the mockup first")
    for existing in trello_client.get_attachments(ticket_id):
        if existing.get("name") == file_name:
            trello_client.delete_attachment(ticket_id, existing["id"])
    trello_client.add_attachment(ticket_id, path, file_name)
    return f"Attached {file_name} to the card."


def update_ticket_summary(ticket_id: str, summary: str) -> str:
    """Write the PO's spec summary onto the Trello card, so the board shows what
    the ticket actually is. `summary` is markdown: purpose, actors, priority,
    acceptance criteria, out of scope, and where the full spec lives. It
    replaces only the PO block at the end of the description; the requester's
    own text above it is kept exactly as it is."""
    description = trello_client.get_card(ticket_id).get("desc") or ""
    kept = description.split(SUMMARY_HEADER)[0].rstrip()
    if kept.endswith("---"):
        kept = kept[:-3].rstrip()
    updated = f"{kept}\n\n---\n{SUMMARY_HEADER} {SUMMARY_NOTE}\n\n{summary.strip()}\n".lstrip()
    if len(updated) > MAX_DESCRIPTION:
        raise ValueError(f"the description would be {len(updated)} characters, over Trello's limit; "
                         f"shorten the summary and keep the detail in spec.md")
    trello_client.update_card_description(ticket_id, updated)
    return "Card description updated with the spec summary."


def post_test_report(ticket_id: str, report: str) -> str:
    """Post this run's test report on the Trello card as its own comment, so
    the board shows what was tested and what failed. `report` is markdown: the
    run (date, branch, commit, commands), per-level counts, every failed
    scenario with expected and actual, what didn't run and why, the manual
    scenarios left for the PO Tester, and the passed scenario IDs. It's posted
    under a fixed header, so it's never read as an event; post the event
    comment separately with post_ticket_event."""
    text = f"{TEST_REPORT_HEADER}\n\n{report.strip()}"
    if len(text) > MAX_COMMENT:
        raise ValueError(f"the report is {len(text)} characters, over Trello's limit; list passed scenarios "
                         f"as ID ranges (FLD-01–FLD-24) and keep the full detail for failures")
    trello_client.add_comment(ticket_id, text)
    return "Test report posted."


def main():
    parser = argparse.ArgumentParser(prog="sdlc mcp trello")
    parser.add_argument("--attach-mockups", action="store_true", help="add attach_mockup (UI/UX stage)")
    parser.add_argument("--summary", action="store_true", help="add update_ticket_summary (PO stage)")
    parser.add_argument("--test-report", action="store_true", help="add post_test_report (Automated QA stage)")
    args = parser.parse_args()
    if args.attach_mockups:
        mcp.tool()(attach_mockup)
    if args.summary:
        mcp.tool()(update_ticket_summary)
    if args.test_report:
        mcp.tool()(post_test_report)
    mcp.run()


if __name__ == "__main__":
    main()
