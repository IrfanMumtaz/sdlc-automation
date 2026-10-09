"""
Stdio MCP server that wraps trello_client.py, so an agent's Trello access is
exactly these scoped operations on the project's board — not raw HTTP, not
the full Trello API surface. Every stage subagent starts it inline:

    sdlc mcp trello                    # get_ticket, post_ticket_event, advance_ticket
    sdlc mcp trello --attach-mockups   # + attach_mockup (UI/UX stage)
    sdlc mcp trello --summary          # + update_ticket_summary (PO stage)
    sdlc mcp trello --test-report      # + post_test_report (Automated QA stage)
    sdlc mcp trello --release          # + record_release (PO stage)
    sdlc mcp trello --merge-release    # + merge_into_release (Deploy stage)
    sdlc mcp trello --ask              # + request_review (PO through Knowledge Base Writer)
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # engine root

from mcp.server.fastmcp import FastMCP

import config
import releases
import trello_client
import worktrees

config.require_project()
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
    # The mockup lives on the ticket's branch, in its worktree.
    kb = worktrees.ticket_kb_root(ticket_id) or config.KB_REPO_PATH
    path = kb / "features" / slug / "mockups" / file_name
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


def record_release(ticket_id: str, version: str) -> str:
    """Record the release this ticket ships in (e.g. '1.4.0') on the Trello
    card, as a [RELEASE] comment. Only record a version the requester or a
    person named, on the card or in a reply; never choose one yourself. A
    newer [RELEASE] comment replaces an older one, so call this again only
    when a person changed the release."""
    version = releases.validate_version(version)
    current = releases.release_of(trello_client.get_card_comments(ticket_id))
    if current == version:
        return f"The card already records release {version}; nothing posted."
    trello_client.add_comment(ticket_id, releases.comment_text(ticket_id, version, "PO"))
    return f"Recorded release {version} on the card" + (f" (was {current})." if current else ".")


def merge_into_release(ticket_id: str) -> str:
    """Merge the ticket's branch into its release branch (release/<version>,
    from the card's latest [RELEASE] comment) in every repository the ticket
    changed, and push each release branch to origin. The release branch starts
    from the development branch the first time. Every repository is checked
    for conflicts first: on a conflict nothing is merged and the error names
    the files. Returns JSON per repository: release worktree path, development
    branch (base), release head commit, origin URL and push result. Only for a
    card in the Deploy list."""
    from state_store import locked, load_state

    card = trello_client.get_card(ticket_id)
    current_list = config.LIST_ID_TO_NAME.get(card["idList"])
    if current_list != "Deploy":
        raise ValueError(f"the card is in '{current_list}', not 'Deploy'; only the Deploy stage merges releases")
    version = releases.release_of(trello_client.get_card_comments(ticket_id))
    if not version:
        raise ValueError("no release is recorded on the card ([RELEASE] comment); escalate so a person sets one")
    with locked():
        try:
            result = releases.merge(load_state(), ticket_id, card["name"], version)
        except worktrees.TicketGitProblem as exc:
            raise ValueError(str(exc)) from exc
    return json.dumps(result, indent=2)


MAX_QUESTIONS = 8
MAX_ASSUMPTIONS = 30


def request_review(ticket_id: str, docs: list[str], assumptions: list[str], questions: list[dict]) -> str:
    """Put your draft in front of the person running /sdlc, the way kickoff
    specialists do, and pause until they respond. Nothing is posted on the
    card and the card stays in your stage's list.

    `docs`: the feature docs this round's draft is in (e.g. ["definition.md",
    "spec.md"]); write them with write_feature_doc first. Empty when the
    draft is your findings (BA) or a single question (Knowledge Base Writer).
    `assumptions`: every point in the draft that no source states (the
    ticket, a person, the knowledge base, the code) and you filled in, one
    sentence each, saying what you assumed. The person confirms or corrects
    them.
    `questions`: up to 8, each {"question": "...", "why": "...", "options":
    ["...", "..."]}: what you can't fill in without the person. `options`
    are 0-3 short answers you'd accept, your recommendation first; empty when
    only the person can supply the value (a release number, a name).

    Then end your turn with a message starting `[REVIEW]` that holds the
    draft (see the stage rules), the numbered assumptions and the questions.
    Don't move the card or post an event comment. You're continued with the
    person's response: revise and call this again, round after round, until
    they approve."""
    from state_store import ASKING_STAGES, busy_stage_for, locked, load_state, save_state, set_review

    docs = [str(d).strip() for d in docs or [] if str(d).strip()]
    assumptions = [str(a).strip() for a in assumptions or [] if str(a).strip()]
    questions = questions or []
    if len(questions) > MAX_QUESTIONS:
        raise ValueError(f"ask at most {MAX_QUESTIONS} questions a round, the most important first")
    if len(assumptions) > MAX_ASSUMPTIONS:
        raise ValueError(f"at most {MAX_ASSUMPTIONS} assumptions a round; a draft that needs more needs "
                         f"questions instead")
    cleaned = []
    for number, item in enumerate(questions, 1):
        question = str(item.get("question", "")).strip()
        options = [str(o).strip() for o in item.get("options") or [] if str(o).strip()]
        if not question:
            raise ValueError(f"question {number} has no text")
        if len(options) > 3:
            raise ValueError(f"question {number} has {len(options)} options; give at most 3")
        if any(len(o) > 60 for o in options):
            raise ValueError(f"question {number}: keep each option under 60 characters")
        cleaned.append({"id": f"Q{number}", "question": question,
                        "why": str(item.get("why", "")).strip(), "options": options})
    with locked():
        state = load_state()
        stage = busy_stage_for(state, ticket_id)
        if stage not in ASKING_STAGES:
            raise ValueError(f"only {', '.join(ASKING_STAGES)} request reviews, and only while the router has "
                             f"them running on this ticket")
        if not (docs or assumptions or cleaned):
            raise ValueError("a review needs a draft (docs), assumptions or questions")
        round_number = set_review(state, ticket_id, stage, docs, assumptions, cleaned)
        save_state(state)
    listed = "\n".join([*(f"A{n}. {a}" for n, a in enumerate(assumptions, 1)),
                         *(f"{q['id']}. {q['question']}" for q in cleaned)])
    return (f"Review round {round_number} saved. End your turn now with a message starting [REVIEW] that "
            f"holds the draft of {', '.join(docs) or 'your findings'} and these, with each question's why and "
            f"options:\n{listed}\nNo card move, no event comment.")


def main():
    parser = argparse.ArgumentParser(prog="sdlc mcp trello")
    parser.add_argument("--attach-mockups", action="store_true", help="add attach_mockup (UI/UX stage)")
    parser.add_argument("--summary", action="store_true", help="add update_ticket_summary (PO stage)")
    parser.add_argument("--test-report", action="store_true", help="add post_test_report (Automated QA stage)")
    parser.add_argument("--release", action="store_true", help="add record_release (PO stage)")
    parser.add_argument("--merge-release", action="store_true", help="add merge_into_release (Deploy stage)")
    parser.add_argument("--ask", action="store_true", help="add request_review (the design stages)")
    args = parser.parse_args()
    if args.attach_mockups:
        mcp.tool()(attach_mockup)
    if args.summary:
        mcp.tool()(update_ticket_summary)
    if args.test_report:
        mcp.tool()(post_test_report)
    if args.release:
        mcp.tool()(record_release)
    if args.merge_release:
        mcp.tool()(merge_into_release)
    if args.ask:
        mcp.tool()(request_review)
    mcp.run()


if __name__ == "__main__":
    main()
