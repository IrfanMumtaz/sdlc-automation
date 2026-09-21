"""
Configuration for the SDLC pipeline engine and the project it's running in.

The engine (this folder) is installed once per machine. Each project that uses
the pipeline has its own settings in <project>/.sdlc/config.json, created by
`sdlc init`. The project is found by walking up from the current directory,
the same way git finds a repository; SDLC_PROJECT_DIR overrides that.

    <project>/
      .sdlc/config.json        Trello board and lists, concurrency and other settings (commit this)
      .sdlc/.gitignore         keeps state/, design-workspace/ and .env out of git
      .sdlc/.env               optional per-project Trello credentials
      .sdlc/state/             router bookkeeping (disposable)
      .sdlc/design-workspace/  /sdlc-kickoff's impeccable scratch folder
      knowledge-base/          the project's knowledge base (path configurable)

Trello credentials come from the environment, then <project>/.sdlc/.env, then
~/.config/sdlc/.env.
"""

import json
import os
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent
KB_TEMPLATE_DIR = ENGINE_ROOT / "kb_template"
USER_CONFIG_DIR = Path.home() / ".config" / "sdlc"
USER_ENV_FILE = USER_CONFIG_DIR / ".env"

PROJECT_DIR_NAME = ".sdlc"
PROJECT_CONFIG_NAME = "config.json"

# --- Pipeline sequence, in order. This list IS the state machine. ---
# Every project's board has one list per stage, with exactly these names,
# plus the Human list.
AGENT_SEQUENCE = [
    "PO",
    "BA",
    "UI/UX",
    "Solution Architect",
    "Knowledge Base Writer",
    "Senior Developer",
    "Code Analyst",
    "Test Scenario Writer",
    "Automated QA",
    "PO Tester",
    "Deploy",
]
HUMAN_LIST = "Human"
BOARD_LISTS = AGENT_SEQUENCE + [HUMAN_LIST]

# --- Priority, highest first ---
# Trello labels with these names. People set them by hand; agents never change
# them. Within a stage's list the router runs labelled cards before unlabelled
# ones, and otherwise takes the card nearest the top of the list.
# `sdlc init` creates any of these labels the board doesn't have.
PRIORITY_LABELS = ["P0", "P1", "P2"]
PRIORITY_LABEL_COLORS = {"P0": "red", "P1": "orange", "P2": "yellow"}

# --- Stage agents ---
# Role -> Claude Code subagent name (claude/agents/<name>.md). Roles not
# listed here aren't built yet: their cards wait in the list and show up in
# the /sdlc report. All eleven stages are built; removing a line here parks
# that stage's cards without touching the board.
AGENT_SUBAGENTS = {
    "PO": "sdlc-po",
    "BA": "sdlc-ba",
    "UI/UX": "sdlc-ui-ux",
    "Solution Architect": "sdlc-solution-architect",
    "Knowledge Base Writer": "sdlc-kb-writer",
    "Senior Developer": "sdlc-senior-developer",
    "Code Analyst": "sdlc-code-analyst",
    "Test Scenario Writer": "sdlc-test-scenario-writer",
    "Automated QA": "sdlc-automated-qa",
    "PO Tester": "sdlc-po-tester",
    "Deploy": "sdlc-deploy",
}

# --- Comment schema prefixes (must match what agent prompts are told to emit) ---
PREFIX_AGENT_DONE = "[AGENT_DONE]"
PREFIX_BOUNCE = "[BOUNCE]"
PREFIX_MISMATCH = "[MISMATCH]"
PREFIX_ESCALATION = "[ESCALATION"   # note: no closing bracket, escalation has a subtype e.g. "[ESCALATION: bounce-cap]"

# --- Per-project settings and their defaults ---
PROJECT_DEFAULTS = {
    "max_active_agents": 1,          # stage agents running at the same time
    "bounce_cap": 3,                 # bounces on one ticket before it escalates to Human
    "max_dispatches_per_run": 10,    # agent runs per /sdlc invocation
    "stages": None,                  # limit the pipeline to these stages; null means every built stage
    "skip_stages": [],               # stages no ticket goes through: the router moves cards straight
                                     # past them. Different from `stages`, where cards simply wait.
    "models": {},                    # stage -> model for this project, e.g. {"PO": "sonnet"};
                                     # empty means each agent file's own model
    "knowledge_base": "knowledge-base",
    "design_workspace": ".sdlc/design-workspace",
    "chrome_path": None,             # Chrome/Chromium for mockups; found on PATH when unset
    "development_branch": None,      # base branch the coding stages branch from;
                                     # null means the first of develop, development, main, master
}


def _load_dotenv(path):
    """Read KEY=value lines from a .env file. Variables already set win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def find_project_root(start=None):
    """The nearest directory at or above `start` holding .sdlc/config.json."""
    override = os.environ.get("SDLC_PROJECT_DIR")
    if override:
        root = Path(override).resolve()
        return root if (root / PROJECT_DIR_NAME / PROJECT_CONFIG_NAME).is_file() else None
    current = Path(start or os.getcwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / PROJECT_DIR_NAME / PROJECT_CONFIG_NAME).is_file():
            return directory
    return None


class ProjectNotFound(SystemExit):
    def __init__(self):
        super().__init__(
            "No SDLC project here: no .sdlc/config.json in this folder or any folder above it.\n"
            "Run `sdlc init --board <trello board URL>` in the project's root folder."
        )


PROJECT_ROOT = find_project_root()
PROJECT_SETTINGS = None

# Project-dependent values; None until a project is found.
BOARD_ID = None
LIST_IDS = {}
LIST_ID_TO_NAME = {}
MAX_ACTIVE_AGENTS = BOUNCE_CAP = MAX_DISPATCHES_PER_RUN = STAGES = None
MODELS = {}
KB_REPO_PATH = DESIGN_WORKSPACE_PATH = STATE_DIR = STATE_FILE = SEEN_COMMENTS_FILE = None

if PROJECT_ROOT:
    _load_dotenv(PROJECT_ROOT / PROJECT_DIR_NAME / ".env")
    _raw = json.loads((PROJECT_ROOT / PROJECT_DIR_NAME / PROJECT_CONFIG_NAME).read_text())
    PROJECT_SETTINGS = {**PROJECT_DEFAULTS, **_raw}

    BOARD_ID = PROJECT_SETTINGS["trello_board_id"]
    LIST_IDS = PROJECT_SETTINGS["trello_lists"]
    LIST_ID_TO_NAME = {v: k for k, v in LIST_IDS.items()}
    MAX_ACTIVE_AGENTS = int(PROJECT_SETTINGS["max_active_agents"])
    BOUNCE_CAP = int(PROJECT_SETTINGS["bounce_cap"])
    MAX_DISPATCHES_PER_RUN = int(PROJECT_SETTINGS["max_dispatches_per_run"])
    STAGES = PROJECT_SETTINGS["stages"]  # resolved by callers via resolve_stages()
    MODELS = PROJECT_SETTINGS["models"] or {}
    KB_REPO_PATH = (PROJECT_ROOT / PROJECT_SETTINGS["knowledge_base"]).resolve()
    DESIGN_WORKSPACE_PATH = (PROJECT_ROOT / PROJECT_SETTINGS["design_workspace"]).resolve()
    STATE_DIR = PROJECT_ROOT / PROJECT_DIR_NAME / "state"
    STATE_FILE = STATE_DIR / "state.json"
    SEEN_COMMENTS_FILE = STATE_DIR / "seen_comments.json"
    if PROJECT_SETTINGS["chrome_path"]:
        os.environ.setdefault("CHROME_PATH", PROJECT_SETTINGS["chrome_path"])

_load_dotenv(USER_ENV_FILE)
TRELLO_KEY = os.environ.get("TRELLO_KEY", "")
TRELLO_TOKEN = os.environ.get("TRELLO_TOKEN", "")


def resolve_stages(value):
    """
    Stage names as a person would type them -> canonical names.
    Accepts a comma-separated string or a list, ignores case, spaces, slashes
    and dashes ("uiux", "UI/UX", "ui-ux" all mean "UI/UX"), and "all" for
    every built stage. Returns None for "everything".
    """
    if value in (None, "", "all", ["all"]):
        return None
    names = value.split(",") if isinstance(value, str) else list(value)
    canonical = {"".join(ch for ch in name.lower() if ch.isalnum()): name for name in AGENT_SEQUENCE}
    stages, unknown = [], []
    for name in names:
        key = "".join(ch for ch in name.lower() if ch.isalnum())
        if not key:
            continue
        if key not in canonical:
            unknown.append(name.strip())
        elif canonical[key] not in stages:
            stages.append(canonical[key])
    if unknown:
        raise ValueError(f"unknown stage(s) {unknown}. Valid stages: {AGENT_SEQUENCE}")
    return stages or None


def resolve_skip_stages(value):
    """
    Stage names to skip, as a person would type them. Unlike resolve_stages,
    an empty value means "skip nothing" rather than "everything", and "all" is
    refused — a pipeline that skips every stage isn't a pipeline.
    """
    if not value:
        return []
    if value in ("all", ["all"]):
        raise ValueError("skip_stages can't be 'all'; name the stages to skip.")
    return resolve_stages(value) or []


def project_skips():
    """Stages this project skips for every ticket (the `skip_stages` setting)."""
    return resolve_skip_stages(PROJECT_SETTINGS["skip_stages"] if PROJECT_SETTINGS else None)


def next_stage_after(stage):
    """The stage a ticket moves to when `stage` is done or skipped; Human after the last."""
    index = AGENT_SEQUENCE.index(stage)
    return AGENT_SEQUENCE[index + 1] if index + 1 < len(AGENT_SEQUENCE) else HUMAN_LIST


def model_for(stage):
    """The project's model override for a stage, or None to use the agent's own."""
    wanted = "".join(ch for ch in stage.lower() if ch.isalnum())
    for name, model in MODELS.items():
        if "".join(ch for ch in name.lower() if ch.isalnum()) == wanted:
            return model
    return None


def require_project():
    if not PROJECT_ROOT:
        raise ProjectNotFound()
