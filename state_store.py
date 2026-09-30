"""
Local bookkeeping only — not a source of truth. Everything here is rebuildable
from Trello's own comment history if this file is lost or the orchestrator
restarts mid-run. Trello remains the only real dependency.

state.json shape:
{
  "agents": {
     "PO": {"status": "idle"},
     "Senior Developer": {"status": "busy", "ticket_id": "abc123"}
  },
  "bounce_counts": {
     "abc123": 2
  },
  "skips": {
     "abc123": ["UI/UX"]
  },
  "branches": {
     "abc123": "feature/42-user-login"
  },
  "pushed_repos": {
     "abc123": ["knowledge-base", "orders-service"]
  }
}

"skips" holds the stages each ticket is marked to skip, rebuilt from the
board's [SKIP] / [UNSKIP] comments if this file is lost. "branches" holds each
ticket's git branch (its workspace is .sdlc/worktrees/<branch without feature/>)
and "pushed_repos" the repositories it's on origin in, both rebuilt from the
router's [BRANCH] comments.

seen_comments.json shape:
{
  "abc123": ["actionId1", "actionId2", ...]
}
Used purely to avoid reprocessing the same comment twice across poll cycles.
"""

import contextlib
import json
import os

try:
    import fcntl  # POSIX only; on Windows the lock is a no-op and /sdlc stays single-session
except ImportError:
    fcntl = None

import config


@contextlib.contextmanager
def locked():
    """
    Hold an exclusive lock on the project's state while a router command runs,
    so two commands never read and write state.json at the same time.
    """
    os.makedirs(config.STATE_DIR, exist_ok=True)
    if fcntl is None:
        yield
        return
    with open(config.STATE_DIR / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _default_state():
    return {
        "agents": {name: {"status": "idle", "ticket_id": None} for name in config.AGENT_SEQUENCE},
        "bounce_counts": {},
        "skips": {},
        "branches": {},
        "pushed_repos": {},
    }


def load_state():
    if not os.path.exists(config.STATE_FILE):
        return _default_state()
    with open(config.STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    # Atomic, because the KB MCP servers read it without the lock to find
    # their ticket's worktree.
    os.makedirs(config.STATE_DIR, exist_ok=True)
    tmp = f"{config.STATE_FILE}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, config.STATE_FILE)


def load_seen_comments():
    if not os.path.exists(config.SEEN_COMMENTS_FILE):
        return {}
    with open(config.SEEN_COMMENTS_FILE, "r") as f:
        return json.load(f)


def save_seen_comments(seen):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(config.SEEN_COMMENTS_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def is_agent_idle(state, agent_name):
    return state["agents"].get(agent_name, {}).get("status", "idle") == "idle"


def mark_agent_busy(state, agent_name, ticket_id, session_id=None, session_pid=None):
    entry = {"status": "busy", "ticket_id": ticket_id}
    if session_id:
        entry["session_id"] = session_id
    if session_pid is not None:
        entry["session_pid"] = session_pid
    state["agents"][agent_name] = entry


def mark_agent_idle(state, agent_name):
    state["agents"][agent_name] = {"status": "idle", "ticket_id": None}


def any_agent_busy_with(state, ticket_id):
    """Prevents double-assigning the same ticket while it's already being worked."""
    for agent, info in state["agents"].items():
        if info.get("status") == "busy" and info.get("ticket_id") == ticket_id:
            return True
    return False


def session_alive(session_pid):
    """Check whether the process that owns a session is still running."""
    if session_pid is None:
        return False
    try:
        os.kill(int(session_pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # process exists but we can't signal it


def increment_bounce(state, ticket_id):
    state["bounce_counts"][ticket_id] = state["bounce_counts"].get(ticket_id, 0) + 1
    return state["bounce_counts"][ticket_id]


def get_bounce_count(state, ticket_id):
    return state["bounce_counts"].get(ticket_id, 0)


def ticket_skips(state, ticket_id):
    """Stages this one ticket is marked to skip, in pipeline order."""
    marked = set(state.setdefault("skips", {}).get(ticket_id, []))
    return [stage for stage in config.AGENT_SEQUENCE if stage in marked]


def add_ticket_skips(state, ticket_id, stages):
    """Mark stages to skip for one ticket. Returns the ticket's full skip list."""
    current = set(state.setdefault("skips", {}).get(ticket_id, [])) | set(stages)
    state["skips"][ticket_id] = [s for s in config.AGENT_SEQUENCE if s in current]
    return state["skips"][ticket_id]


def remove_ticket_skips(state, ticket_id, stages=None):
    """Unmark stages for one ticket; `stages=None` clears every skip on it."""
    skips = state.setdefault("skips", {})
    if stages is None:
        skips.pop(ticket_id, None)
        return []
    remaining = set(skips.get(ticket_id, [])) - set(stages)
    if remaining:
        skips[ticket_id] = [s for s in config.AGENT_SEQUENCE if s in remaining]
    else:
        skips.pop(ticket_id, None)
    return skips.get(ticket_id, [])
