"""
Deterministic router for the SDLC pipeline. The /sdlc skill in Claude Code
calls it through the `sdlc` command between subagent runs; it never calls a
model itself.

  sdlc next      Read new event comments, update state, and pick the next ticket.
                 {"action": "dispatch", ...}  start this agent on this ticket
                 {"action": "wait", ...}      agents are running; wait for one to finish
                 {"action": "idle", ...}      nothing running and nothing to do
  sdlc finish    Close out one agent run. If the agent left no event comment,
                 escalate the card to Human so the agent isn't left busy.
  sdlc recover   Close out runs an earlier, interrupted session never finished.

Up to the project's max_active_agents runs can be in progress at once. Every
command holds the project's state lock, so commands never overlap.

Each ticket works on its own branch in its own git worktree (worktrees.py):
`next` prepares it before dispatching, and `finish` commits the stage's
knowledge base changes on it and pushes it.
"""

import logging

import config
import worktrees
from trello_client import (
    get_cards_on_board, get_card, get_card_comments, add_comment, move_card, get_open_lists,
)
from comment_parser import parse_comment
from state_store import (
    locked, load_state, save_state, load_seen_comments, save_seen_comments,
    is_agent_idle, mark_agent_busy, mark_agent_idle,
    any_agent_busy_with, increment_bounce,
    ticket_skips, add_ticket_skips, remove_ticket_skips,
    session_alive,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("orchestrator")


def list_name_for(list_id):
    return config.LIST_ID_TO_NAME.get(list_id, f"UNKNOWN_LIST({list_id})")


def process_new_comments(state, seen, card):
    """Fetch comments for one card, process any not seen before (oldest first)."""
    card_id = card["id"]
    comments = get_card_comments(card_id)  # newest first from Trello
    comments = list(reversed(comments))    # process oldest -> newest

    card_seen = seen.setdefault(card_id, [])
    already_seen = set(card_seen)
    events = []

    for c in comments:
        action_id = c["id"]
        if action_id in already_seen:
            continue

        text = c.get("data", {}).get("text", "")
        parsed = parse_comment(text)
        card_seen.append(action_id)

        if parsed is None:
            continue  # human comment or free-form chatter — ignore

        handle_event(state, seen, card, parsed)
        events.append(parsed)

    return events


def escalate(seen, card, subtype, fields):
    """Post an orchestrator escalation comment and move the card to Human."""
    comment = add_comment(card["id"], f"[ESCALATION: {subtype}] {fields}")
    seen.setdefault(card["id"], []).append(comment["id"])  # our own comment needs no processing
    move_card(card["id"], config.LIST_IDS[config.HUMAN_LIST])
    card["idList"] = config.LIST_IDS[config.HUMAN_LIST]


def stages_to_skip(state, ticket_id):
    """Every stage this ticket skips: the project's own, plus its marked ones."""
    marked = set(config.project_skips()) | set(ticket_skips(state, ticket_id))
    return [stage for stage in config.AGENT_SEQUENCE if stage in marked]


def parse_stage_list(value):
    """Stage names from a comment field, ignoring ones that aren't stages."""
    try:
        return config.resolve_stages(value) or []
    except ValueError:
        log.warning(f"ignoring unknown stage name(s) in skip comment: {value!r}")
        return []


def apply_skips(state, seen, cards):
    """
    Move every card sitting in a stage it skips to the next stage, one stage at
    a time, recording each with a [SKIPPED] comment. No agent runs, so a skip
    costs nothing but the two API calls that move and record it.
    """
    moved = []
    for card in cards:
        if any_agent_busy_with(state, card["id"]):
            continue
        skips = stages_to_skip(state, card["id"])
        if not skips:
            continue

        where = list_name_for(card["idList"])
        while where in config.AGENT_SEQUENCE and where in skips:
            target = config.next_stage_after(where)
            reason = ("this project skips the stage" if where in config.project_skips()
                      else "the ticket is marked to skip the stage")
            log.info(f"SKIP: {where} skipped for ticket '{card['name']}' ({card['id']}) -> {target}")
            comment = add_comment(
                card["id"],
                f'[SKIPPED] agent="{where}" ticket=#{card["id"]} moved_to="{target}" reason="{reason}"')
            seen.setdefault(card["id"], []).append(comment["id"])  # our own comment needs no processing
            move_card(card["id"], config.LIST_IDS[target])
            card["idList"] = config.LIST_IDS[target]
            moved.append({"agent": where, "ticket_id": card["id"], "ticket_name": card["name"],
                          "moved_to": target, "reason": reason})
            where = target
    return moved


def free_agent(state, agent, card):
    if agent not in config.AGENT_SEQUENCE:
        log.warning(f"Event on ticket {card['name']} ({card['id']}) names unknown agent '{agent}'; "
                    f"agent names must match config.AGENT_SEQUENCE (quote names with spaces).")
        return
    mark_agent_idle(state, agent)


def handle_event(state, seen, card, event):
    card_id = card["id"]
    etype = event["type"]
    agent = event.get("agent")

    if etype == "AGENT_DONE":
        log.info(f"AGENT_DONE: {agent} finished ticket {card['name']} ({card_id})")
        if agent:
            free_agent(state, agent, card)

    elif etype == "BOUNCE":
        target = event.get("target")
        reason = event.get("reason", "")
        count = increment_bounce(state, card_id)
        log.info(
            f"BOUNCE: {agent} bounced ticket {card['name']} ({card_id}) "
            f"-> {target} | reason: {reason} | bounce_count={count}"
        )
        if agent:
            free_agent(state, agent, card)
        if count >= config.BOUNCE_CAP:
            log.warning(f"Bounce cap ({config.BOUNCE_CAP}) hit for ticket {card_id}. Escalating to Human.")
            escalate(seen, card, "bounce-cap", f"ticket=#{card_id} bounces={count}")
        elif target and target in stages_to_skip(state, card_id):
            # Skipping it forward again would land it back on the stage that
            # bounced it, and so on until the bounce cap. A person decides.
            log.warning(f"Ticket {card_id} was bounced to {target}, which it skips. Escalating to Human.")
            escalate(seen, card, "bounce-to-skipped-stage",
                     f'ticket=#{card_id} target="{target}" '
                     f'reason="{agent} needs the {target} stage, but it is skipped for this ticket"')

    elif etype == "SKIP":
        stages = parse_stage_list(event.get("stages", ""))
        if stages:
            marked = add_ticket_skips(state, card_id, stages)
            log.info(f"SKIP marked on ticket {card['name']} ({card_id}): {stages} | now skipping {marked}")

    elif etype == "UNSKIP":
        raw = event.get("stages", "")
        stages = None if raw in ("", "all") else parse_stage_list(raw)
        remaining = remove_ticket_skips(state, card_id, stages)
        log.info(f"UNSKIP on ticket {card['name']} ({card_id}): {raw or 'all'} | still skipping {remaining}")

    elif etype == "SKIPPED":
        pass  # the router's own record; the card was already moved

    elif etype == "BRANCH":
        if event.get("name"):
            state.setdefault("branches", {})[card_id] = event["name"]
        pushed = [r for r in event.get("repos", "").split(",") if r]
        if pushed:
            known = state.setdefault("pushed_repos", {}).setdefault(card_id, [])
            known += [r for r in pushed if r not in known]

    elif etype == "MISMATCH":
        log.warning(
            f"MISMATCH: {agent} reported wrong assignment on ticket "
            f"{card['name']} ({card_id}). Escalating to Human."
        )
        if agent:
            free_agent(state, agent, card)
        escalate(seen, card, "routing-mismatch", f"ticket=#{card_id}")

    elif etype == "ESCALATION":
        log.info(
            f"ESCALATION ({event.get('subtype')}) already recorded on ticket "
            f"{card['name']} ({card_id}) — no orchestrator action needed, "
            f"card should already be in Human list."
        )
        # agent-stuck escalations come from the agent itself, which frees itself
        # by escalating (bounce-cap / routing-mismatch have no agent= field)
        if agent:
            free_agent(state, agent, card)


def settle(state, seen, agent_name, card_id):
    """
    Close out one agent run. Its own event comment normally frees the agent;
    if there isn't one (the subagent errored, hit its turn limit, or the
    session was interrupted), escalate to Human rather than leave the agent
    busy forever, which would stall the board at MAX_ACTIVE_AGENTS=1.
    """
    card = get_card(card_id)
    events = process_new_comments(state, seen, card)

    if not any_agent_busy_with(state, card_id):
        # the agent may have moved the card after we fetched it
        return {"result": "recorded", "events": events, "list": list_name_for(get_card(card_id)["idList"])}

    log.warning(f"{agent_name} ended on ticket {card['name']} ({card_id}) without an event comment. Escalating.")
    escalate(seen, card, "agent-stuck",
             f'agent="{agent_name}" ticket=#{card_id} reason="agent run ended without posting an event comment"')
    mark_agent_idle(state, agent_name)
    return {"result": "escalated", "events": events, "list": config.HUMAN_LIST}


def requested_stages(only=None):
    """
    The stages asked for, in the order they were asked for: `sdlc next --only`
    first, else the project's `stages` setting, else pipeline order. The second
    value says whether that order was chosen by a person rather than inherited
    from the pipeline.
    """
    for chosen in (config.resolve_stages(only), config.resolve_stages(config.STAGES)):
        if chosen:
            return chosen, True
    return list(config.AGENT_SEQUENCE), False


def runnable_stages(only=None):
    """The requested stages that actually have an agent built, in that order."""
    stages, _ = requested_stages(only)
    return [s for s in stages if s in config.AGENT_SUBAGENTS]


def stages_without_agents(only=None):
    stages, explicit = requested_stages(only)
    return [s for s in stages if s not in config.AGENT_SUBAGENTS] if explicit else []


def dispatch_order(state, only=None):
    """
    Stages to try, in order. When a person named the order, start after the
    stage dispatched last so the run rotates through their list instead of one
    stage draining every card before the next gets a turn.
    """
    stages = runnable_stages(only)
    _, explicit = requested_stages(only)
    last = state.get("last_stage")
    if explicit and last in stages:
        start = stages.index(last) + 1
        stages = stages[start:] + stages[:start]
    return stages


def priority_of(card):
    """The card's priority label, or None. The first one listed in
    config.PRIORITY_LABELS wins if a card somehow carries two."""
    names = {(label.get("name") or "").strip() for label in card.get("labels", [])}
    return next((p for p in config.PRIORITY_LABELS if p in names), None)


def work_order(card):
    """
    Sort key for tickets competing for the same agent: priority label first
    (P0 before P1 before P2, unlabelled last), then position in the list, so
    an unprioritised board still runs the card a person dragged to the top.
    """
    priority = priority_of(card)
    rank = config.PRIORITY_LABELS.index(priority) if priority else len(config.PRIORITY_LABELS)
    return (rank, card.get("pos", float("inf")), card.get("dateLastActivity", ""))


def pick_next(state, cards, only=None):
    """
    Return (agent_name, card) for the next ticket to work, or None. Only
    runnable stages are dispatched; cards in other lists wait. Respects
    MAX_ACTIVE_AGENTS globally.
    """
    active_count = sum(1 for a in state["agents"].values() if a["status"] == "busy")
    if active_count >= config.MAX_ACTIVE_AGENTS:
        return None

    for agent_name in dispatch_order(state, only):
        if not is_agent_idle(state, agent_name):
            continue

        agent_list_id = config.LIST_IDS[agent_name]
        eligible = [
            c for c in cards
            if c["idList"] == agent_list_id and not any_agent_busy_with(state, c["id"])
        ]
        if not eligible:
            continue

        eligible.sort(key=work_order)
        return agent_name, eligible[0]

    return None


def board_list_name(list_id):
    """
    A list's name as it reads on the board, including lists that aren't
    pipeline stages (a backlog, an icebox). Costs one call, so it's only for
    the single-ticket path, where naming the list is the whole point.
    """
    if list_id in config.LIST_ID_TO_NAME:
        return config.LIST_ID_TO_NAME[list_id]
    try:
        for lst in get_open_lists(config.BOARD_ID):
            if lst["id"] == list_id:
                return lst["name"]
    except Exception:  # noqa: BLE001 - naming a list is a nicety, never a failure
        pass
    return list_name_for(list_id)


def pick_ticket(state, cards, ticket_id):
    """
    Return (agent_name, card) for one named ticket, or a dict saying why it
    can't run. Stage filters don't apply: naming a ticket means moving that
    ticket, wherever it currently sits.
    """
    card = next((c for c in cards if c["id"] == ticket_id), None)
    if card is None:
        return {"action": "idle", "ticket_id": ticket_id,
                "reason": "that ticket isn't an open card on this project's board"}

    where = board_list_name(card["idList"])
    detail = {"ticket_id": ticket_id, "ticket_name": card["name"], "list": where}

    if any_agent_busy_with(state, ticket_id):
        return {"action": "wait", "running": busy_runs(state), **detail}
    if where == config.HUMAN_LIST:
        return {"action": "idle", "reason": "the ticket is with Human; a person has to move it on", **detail}
    if where not in config.AGENT_SEQUENCE:
        return {"action": "idle", "reason": f"'{where}' isn't a pipeline stage, so no agent runs there", **detail}
    if where not in config.AGENT_SUBAGENTS:
        return {"action": "idle", "reason": f"no agent is built for the {where} stage", **detail}
    if not is_agent_idle(state, where):
        return {"action": "wait", "running": busy_runs(state), **detail}
    if sum(1 for a in state["agents"].values() if a["status"] == "busy") >= config.MAX_ACTIVE_AGENTS:
        return {"action": "wait", "running": busy_runs(state), **detail}

    return where, card


def prepare_worktree(state, seen, card, stage):
    """
    The ticket's worktree for a dispatch, or None after escalating the card
    because its branch needs a person. A ProjectGitProblem propagates: nothing
    can run until the repository is fixed.
    """
    try:
        info, new_branch = worktrees.prepare(state, card, stage)
    except worktrees.TicketGitProblem as exc:
        log.warning(f"Branch problem on ticket {card['name']} ({card['id']}): {exc}. Escalating.")
        reason = str(exc).replace('"', "'")
        escalate(seen, card, "branch", f'ticket=#{card["id"]} reason="{reason}"')
        return None
    if new_branch:
        state.setdefault("branches", {})[card["id"]] = info["branch"]
        record_branch(seen, card["id"], info["branch"], [])
    return info


def record_branch(seen, ticket_id, branch, pushed_repos):
    """The card's record of its branch and the repositories it's pushed to, for every machine."""
    comment = add_comment(ticket_id, f'[BRANCH] ticket=#{ticket_id} name="{branch}" '
                                     f'repos="{",".join(pushed_repos)}"')
    seen.setdefault(ticket_id, []).append(comment["id"])  # the caller already applied it


def busy_runs(state):
    runs = []
    for name, info in state["agents"].items():
        if info["status"] == "busy":
            run = {"agent": name, "ticket_id": info["ticket_id"]}
            if info.get("session_id"):
                run["session_id"] = info["session_id"]
            if info.get("session_pid") is not None:
                run["session_pid"] = info["session_pid"]
            runs.append(run)
    return runs


def cmd_next(only=None, ticket_id=None, session_id=None, session_pid=None):
    with locked():
        state = load_state()
        seen = load_seen_comments()

        cards = get_cards_on_board()
        for card in cards:
            process_new_comments(state, seen, card)

        # Skips first, so a card that skips its stage can be picked up by the
        # next one in the same run.
        skipped = apply_skips(state, seen, [c for c in cards if not ticket_id or c["id"] == ticket_id])

        stages = runnable_stages(only)
        escalated = []
        while True:
            if ticket_id:
                chosen = pick_ticket(state, cards, ticket_id)
                if isinstance(chosen, dict):  # can't run: the dict says why
                    save_state(state)
                    save_seen_comments(seen)
                    return {**chosen, "ticket_only": ticket_id, **({"skipped": skipped} if skipped else {}),
                            **({"escalated": escalated} if escalated else {})}
            else:
                chosen = pick_next(state, cards, only)
            if not chosen:
                break
            try:
                tree = prepare_worktree(state, seen, chosen[1], chosen[0])
            except worktrees.ProjectGitProblem:
                save_state(state)
                save_seen_comments(seen)
                raise
            if tree:
                break
            # Escalated to Human (the card has moved), so pick again.
            escalated.append({"ticket_id": chosen[1]["id"], "ticket_name": chosen[1]["name"],
                              "reason": "its branch needs a person; see the card's escalation comment"})

        if chosen:
            agent_name, card = chosen
            mark_agent_busy(state, agent_name, card["id"], session_id, session_pid)
            state["last_stage"] = agent_name  # so the next dispatch moves along the requested order
            log.info(f"DISPATCH: {agent_name} -> ticket '{card['name']}' ({card['id']})")
            result = {
                "action": "dispatch",
                "agent": agent_name,
                "subagent": config.AGENT_SUBAGENTS[agent_name],
                "ticket_id": card["id"],
                "ticket_name": card["name"],
                "priority": priority_of(card) or "none",
                **tree,
            }
            model = config.model_for(agent_name)
            if model and config.is_model_family(model):
                result["model"] = model.strip().lower()
            # a version is on the project's copy of the agent file (agent_versions.py)
            if ticket_id:
                result["ticket_only"] = ticket_id
        elif busy_runs(state):
            result = {"action": "wait", "running": busy_runs(state)}
        else:
            waiting = {}
            for c in sorted(cards, key=work_order):
                name = list_name_for(c["idList"])
                if name not in stages:
                    priority = priority_of(c)
                    waiting.setdefault(name, []).append(
                        f"{c['name']} ({c['id']})" + (f" [{priority}]" if priority else ""))
            result = {"action": "idle", "stages": stages, "waiting": waiting}
            missing = stages_without_agents(only)
            if missing:
                result["no_agent_built"] = missing

        if skipped:
            result["skipped"] = skipped
        if escalated:
            result["escalated"] = escalated
        if config.project_skips():
            result["skipped_stages"] = config.project_skips()

        save_state(state)
        save_seen_comments(seen)
        return result


def record_work(state, seen, agent_name, ticket_id, outcome):
    """
    Commit and push what the stage left on its ticket's branch, and note on the
    card any repository the branch reached for the first time, so another
    machine knows to expect it on origin. Never fails the finish.
    """
    try:
        name = get_card(ticket_id)["name"]
    except Exception:  # noqa: BLE001 - the commit message can do without the title
        name = f"ticket {ticket_id}"
    try:
        result = worktrees.record_stage(state, agent_name, ticket_id, name, outcome)
        known = state.setdefault("pushed_repos", {}).setdefault(ticket_id, [])
        new = [r for r in result.pop("pushed_repos", []) if r not in known]
        if new:
            known += new
            record_branch(seen, ticket_id, result["branch"], known)
        return result
    except Exception as exc:  # noqa: BLE001 - report it; the run itself is already settled
        log.warning(f"Couldn't record {agent_name}'s work on ticket {ticket_id}: {exc}")
        return {"error": str(exc)}


def cmd_finish(agent_name, ticket_id):
    with locked():
        state = load_state()
        seen = load_seen_comments()
        result = {"agent": agent_name, "ticket_id": ticket_id, **settle(state, seen, agent_name, ticket_id)}
        result["git"] = record_work(state, seen, agent_name, ticket_id, result["result"])
        save_state(state)
        save_seen_comments(seen)
        return result


def cmd_recover(session_id=None, session_pid=None):
    """
    Settle runs still marked busy whose owning session is no longer alive.
    Skips runs from the caller's own session (they're between dispatch and
    finish) and runs from other sessions whose process is still running.
    Without a session_id, falls back to the old behaviour: recover everything.
    """
    with locked():
        state = load_state()
        seen = load_seen_comments()
        recovered, skipped = [], []
        for run in busy_runs(state):
            if session_id:
                if run.get("session_id") == session_id:
                    skipped.append(run)
                    continue
                if run.get("session_pid") is not None and session_alive(run["session_pid"]):
                    skipped.append(run)
                    continue
            settled = {**run, **settle(state, seen, run["agent"], run["ticket_id"])}
            settled["git"] = record_work(state, seen, run["agent"], run["ticket_id"], settled["result"])
            recovered.append(settled)
        save_state(state)
        save_seen_comments(seen)
        result = {"recovered": recovered}
        if skipped:
            result["active_in_other_sessions"] = [
                {"agent": r["agent"], "ticket_id": r["ticket_id"]} for r in skipped]
        return result
