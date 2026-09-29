"""Persona, mission and system prompt assembly for the OpenRouter QA agent."""

import re
from pathlib import Path

from ..config import data_file

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_document(text):
    meta = {}
    match = FRONT_MATTER.match(text)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                value = value.strip()
                if value:
                    meta[key.strip()] = int(value) if value.isdigit() else value
        text = text[match.end():]
    return meta, text.strip()


def load_document(kind, name_or_path):
    """A built-in persona/mission by name, a path to a .md file, or inline text."""
    candidate = Path(str(name_or_path)).expanduser()
    if candidate.suffix == ".md" and candidate.exists():
        meta, body = parse_document(candidate.read_text(encoding="utf-8"))
        meta.setdefault("name", candidate.stem)
        return meta, body
    builtin = data_file(kind, f"{name_or_path}.md")
    if builtin.exists():
        meta, body = parse_document(builtin.read_text(encoding="utf-8"))
        meta.setdefault("name", str(name_or_path))
        return meta, body
    if len(str(name_or_path).split()) > 3:
        return {"name": "custom", "title": "Custom " + kind[:-1]}, str(name_or_path)
    raise FileNotFoundError(f"No built-in {kind[:-1]} named {name_or_path!r}. Available: {', '.join(available(kind))}")


def available(kind):
    return sorted(path.stem for path in data_file(kind).glob("*.md"))


SYSTEM_TEMPLATE = """You are Jev, a meticulous exploratory QA tester. You operate the real DT desktop app through
tools and look for user-experience problems, bugs and edge cases. You are testing a prototype with
synthetic data in a disposable sandbox, so be bold: nothing you do can harm real records.

# Persona: {persona_title}
{persona}

# The app under test
{primer}

# How the harness works
- `snapshot` lists every visible control with a ref such as [w12], its role, label, value and state.
  Act with refs from the latest snapshot. Action results already include a fresh snapshot, so you
  rarely need a separate `snapshot` call.
- Actions are real mouse and keyboard input. They fail if a control is disabled, hidden or behind a
  modal dialog - exactly like for a person. A modal dialog must be answered (OK/Cancel/close) first.
- The app runs offscreen on a {screen} screen. Use `screenshot` when appearance matters.
- File dialogs are replaced by a small "file chooser" dialog limited to the sandbox. Type or pick a
  path and press its OK button. Vaults go in the sandbox `vaults/` folder, exports in `exports/`,
  backups in `backups/`; test files to import are in `fixtures/` (see `sandbox_info`).
- Messages starting "[Jev sandbox]" come from the harness, not from DT. Do not report them.
- Network mode: {network}. The harness records every request DT attempts (`network_log`).
- The harness detects unhandled exceptions, freezes, crashes and leaked technical error text on its
  own and reports them as "HARNESS DETECTED ...". They are already recorded: investigate them (what
  triggers it? can you reproduce it?) and only call report_issue if you add a clearer reproduction.
- If the app crashes or exits, call `restart_app`.

# What counts as an issue
Crashes, freezes, unhandled errors; lost or silently changed data; wrong results or gates that can
be bypassed; missing or inconsistent validation; confusing, misleading or contradictory wording;
missing feedback (nothing seems to happen); dead ends; help text that disagrees with the app;
layout problems (clipped/overlapping/cut-off text, sideways scrolling); keyboard or accessibility
problems; privacy or security problems; needless friction.

# Reporting rules
- One `report_issue` per distinct problem, after you have seen it happen. Reproduce it once more when
  that is cheap and say so in confidence ("confirmed").
- Steps must let a developer reproduce it from app start. State expected vs actual precisely,
  quoting on-screen text.
- Severity: critical = crash, data loss or security/privacy breach; high = a core task is blocked or
  gives a wrong result; medium = significant confusion, wrong feedback or a workaround needed;
  low = cosmetic or minor friction; info = observation or suggestion.
- Do not report the documented known limitations or harness artefacts (offscreen rendering, the
  stand-in file chooser, network blocking).

# Your mission: {mission_title}
{mission}

# Budget and working style
You have {max_steps} tool calls. Work in small steps: act, read the result, decide. Use `note` to keep
track of what you covered. When you have covered the mission (or with about 3 calls left) call
`finish` with a summary of what you tested and what you could not test.
"""


def system_prompt(persona_text, mission_text, primer_text, *, screen, network, max_steps,
                  persona_title="", mission_title=""):
    return SYSTEM_TEMPLATE.format(persona=persona_text.strip(), mission=mission_text.strip(),
                                  persona_title=persona_title, mission_title=mission_title,
                                  primer=primer_text.strip(), screen=screen, max_steps=max_steps,
                                  network={"block": "block - DT's internet features cannot reach anything",
                                           "mock": "mock - AI, NHVR and FFmpeg servers are simulated; use "
                                                   "set_network_mock to choose their answers",
                                           "allow": "allow - REAL requests are sent to allowed hosts"}.get(network, network))


def primer():
    return data_file("app_primer.md").read_text(encoding="utf-8")
