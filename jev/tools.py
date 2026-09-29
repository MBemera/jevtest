"""The QA tool set, shared by the MCP server (Claude Code, Codex) and the OpenRouter agent.

Every tool returns plain text written for a language model, plus an optional PNG image.
Harness-detected problems (uncaught exceptions, freezes, crashes, leaked error text) are
recorded as findings automatically and called out in the tool result.
"""

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .client import HostError
from .findings import CATEGORIES, SEVERITIES, FindingStore, auto_findings
from .session import AppCrashed, AppExited, AppSession, AppStartError

TARGET = {"type": "string", "description": "A ref from the latest snapshot such as \"w12\" (preferred), or the "
                                           "control's visible label/text such as \"Save preparation\"."}
ROLE = {"type": "string", "description": "Optional role to narrow a name match: button, textbox, textarea, "
                                         "combobox, checkbox, list, tree, tabs, canvas."}
SNAPSHOT_FLAG = {"type": "boolean", "description": "Include a fresh snapshot in the result (default true)."}


def spec(name, description, properties=None, required=None, audiences=("agent", "mcp")):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
            "audiences": set(audiences)}


TOOL_SPECS = [
    spec("snapshot", "Describe everything on screen now: open windows and dialogs, every control with its ref "
         "(w12), role, label, value and state (disabled, focused, read-only, scrolled out of view), plus the status "
         "bar. Take one before acting and whenever you are unsure what is on screen.",
         {"full": {"type": "boolean", "description": "Also list windows hidden behind a modal dialog."},
          "max_items": {"type": "integer", "description": "How many list rows to show per list (default 8)."}}),
    spec("screenshot", "Capture the screen as an image to judge visual problems: clipped or overlapping text, "
         "alignment, contrast, spacing, confusing layout. marks=true labels controls with their refs.",
         {"target": {"type": "string", "description": "Optional ref to capture one widget instead of the screen."},
          "marks": {"type": "boolean", "description": "Draw ref labels on interactive controls."}}),
    spec("click", "Click a control with the mouse, as a person would. Use for buttons, checkboxes, list rows, "
         "anything clickable. Blocked if the control is disabled, hidden or behind a modal dialog.",
         {"target": TARGET, "role": ROLE, "double": {"type": "boolean", "description": "Double-click."},
          "index": {"type": "integer", "description": "Which match to use when several controls share a label."},
          "snapshot": SNAPSHOT_FLAG}, ["target"]),
    spec("type_text", "Click into a text field or editable dropdown and type, key by key, like a person. By "
         "default the existing text is selected and replaced. Long text (over 600 characters) is pasted.",
         {"target": TARGET, "role": ROLE, "text": {"type": "string", "description": "Text to type."},
          "clear": {"type": "boolean", "description": "Replace the existing text (default true); false appends."},
          "submit": {"type": "string", "description": "Key to press afterwards: 'enter' or 'tab'. Tab leaves the "
                                                      "field, which triggers on-leave behaviour."},
          "paste": {"type": "boolean", "description": "Paste the text in one go instead of typing it."},
          "repeat": {"type": "integer", "description": "Repeat the text this many times (for long-input tests)."},
          "snapshot": SNAPSHOT_FLAG}, ["target", "text"]),
    spec("select_option", "Open a dropdown (combobox) and choose an option by its text or index.",
         {"target": TARGET, "option": {"type": "string", "description": "Option text (exact, prefix or contained) "
                                                                         "or a zero-based index such as \"2\"."},
          "snapshot": SNAPSHOT_FLAG}, ["target", "option"]),
    spec("set_checked", "Tick or untick a checkbox or radio button by clicking it (no-op if already in that state).",
         {"target": TARGET, "checked": {"type": "boolean", "description": "true to tick, false to untick."},
          "snapshot": SNAPSHOT_FLAG}, ["target", "checked"]),
    spec("select_item", "Click a row in a list or tree. action=activate double-clicks it; check/uncheck/toggle "
         "flip the row's checkbox. For trees, item may be a path such as 'Company / Division / Driver'.",
         {"target": TARGET, "item": {"type": "string", "description": "Row text (exact, prefix or contained) or a "
                                                                       "zero-based row number such as \"3\"."},
          "action": {"type": "string", "description": "select (default), activate, check, uncheck or toggle."},
          "snapshot": SNAPSHOT_FLAG}, ["target", "item"]),
    spec("select_tab", "Click a tab by its label (for example '3 Evidence') or index.",
         {"tab": {"type": "string", "description": "Tab label or zero-based index."},
          "target": {"type": "string", "description": "Optional ref of the tab widget when several are visible."},
          "snapshot": SNAPSHOT_FLAG}, ["tab"]),
    spec("press_key", "Press a key or shortcut, e.g. 'Tab', 'Shift+Tab', 'Return', 'Escape', 'Space', 'F1', "
         "'Ctrl+A', 'Down'. Goes to the focused control unless target is given.",
         {"keys": {"type": "string", "description": "Key combination; several comma-separated combinations are "
                                                    "pressed in order."},
          "target": {"type": "string", "description": "Optional ref to receive the keys."},
          "snapshot": SNAPSHOT_FLAG}, ["keys"]),
    spec("draw", "Drag the mouse across a drawing area (such as the signature pad). Without strokes a short "
         "scribble is drawn.",
         {"target": TARGET, "strokes": {"type": "string", "description": "Optional JSON list of strokes, each a "
                                                                         "list of [x, y] points from 0 to 1."},
          "snapshot": SNAPSHOT_FLAG}, ["target"]),
    spec("scroll", "Turn the mouse wheel over a scrollable area (a page, list or text box), or jump to its top "
         "or bottom. The wheel acts on whatever is under the pointer, as with a real mouse.",
         {"target": TARGET, "direction": {"type": "string", "description": "down (default), up, left or right."},
          "amount": {"type": "integer", "description": "Wheel notches (default 3)."},
          "to": {"type": "string", "description": "top or bottom: drag the scroll bar to the end instead."},
          "snapshot": SNAPSHOT_FLAG}, ["target"]),
    spec("set_value", "Drag a slider to a value.",
         {"target": TARGET, "value": {"type": "integer", "description": "New value."}, "snapshot": SNAPSHOT_FLAG},
         ["target", "value"]),
    spec("resize_window", "Resize the main window (or the window containing target) to test small or large "
         "screens. Limited to the screen size; restart_app with a different screen for bigger displays.",
         {"width": {"type": "integer"}, "height": {"type": "integer"},
          "target": {"type": "string", "description": "Optional ref inside the window to resize."},
          "snapshot": SNAPSHOT_FLAG}, ["width", "height"]),
    spec("close_window", "Close a window or dialog with its title-bar close button (the app may refuse, e.g. with "
         "unsaved edits). Without target, closes the active dialog or window.",
         {"target": {"type": "string", "description": "Optional ref inside the window to close."},
          "snapshot": SNAPSHOT_FLAG}),
    spec("wait", "Wait while the app works (imports, media checks, backups), then report what happened.",
         {"seconds": {"type": "number", "description": "Up to 120 seconds (default 2)."},
          "until": {"type": "string", "description": "Stop early when 'idle' (no background job) or 'dialog' opens."},
          "snapshot": {"type": "boolean", "description": "Include a snapshot afterwards (default true)."}}),
    spec("read_text", "Read the complete text of a control: a long label, text area, help page, list or dropdown.",
         {"target": TARGET}, ["target"]),
    spec("list_items", "Page through the rows of a long list, tree or dropdown.",
         {"target": TARGET, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["target"]),
    spec("events", "Everything the harness observed since a sequence number: dialogs, status messages, network "
         "attempts, sandbox refusals, exceptions, freezes.",
         {"since": {"type": "integer", "description": "Only events after this sequence number (default: last 40)."}}),
    spec("audit", "Run deterministic layout and accessibility checks on the visible window: clipped text, "
         "horizontal scrolling, overlaps, off-screen controls, small targets, unlabelled controls, focus order.",
         {"kind": {"type": "string", "description": "layout, accessibility or all (default)."}}),
    spec("network_log", "Show the most recent outgoing requests the app attempted (URL, decision and the exact "
         "body it would send), to check privacy promises and approval prompts.",
         {"count": {"type": "integer", "description": "How many recent requests (default 3)."}}),
    spec("set_network_mock", "In network=mock mode, choose how fake AI/NHVR/FFmpeg services answer next: ok, slow, "
         "timeout, http_401, http_403, http_429, http_500, unfinished, empty, oversized, invalid_json, injection, "
         "long_draft, not_found, multiple, different_plate.",
         {"scenario": {"type": "string"}, "service": {"type": "string", "description": "ai, nhvr, ffmpeg or all."},
          "delay": {"type": "number", "description": "Seconds for slow/timeout scenarios (default 20)."}},
         ["scenario"]),
    spec("sandbox_info", "Where test files live: sandbox folders for new vaults, exports and backups, the fixture "
         "files available to import (valid, corrupt, empty, oddly named), the seeded vault and its passphrase, "
         "network mode and screen size."),
    spec("restart_app", "Close the app and start it again, keeping the sandbox (vaults, exports) unless fresh=true. "
         "Use to test persistence after a restart, or to recover after a crash or exit. A seeded vault is "
         "unlocked again automatically.",
         {"fresh": {"type": "boolean", "description": "Delete the sandbox and start from nothing."},
          "screen": {"type": "string", "description": "New screen size such as 1024x768 or 2560x1440@2."},
          "network": {"type": "string", "description": "block, mock or allow."},
          "idle_timeout_ms": {"type": "integer", "description": "Override the app's idle auto-lock."},
          "seed": {"type": "string", "description": "none, empty or sample (only used with fresh=true)."}}),
    spec("report_issue", "Record one problem you found. Report each distinct issue once, with steps a developer "
         "can follow. A screenshot, the snapshot and recent events are attached automatically.",
         {"title": {"type": "string", "description": "Short specific summary, e.g. 'Delete accepts an empty "
                                                     "passphrase without explanation'."},
          "severity": {"type": "string", "description": "critical, high, medium, low or info."},
          "category": {"type": "string", "description": ", ".join(CATEGORIES) + "."},
          "steps": {"type": "string", "description": "Numbered steps to reproduce, one per line, from app start."},
          "expected": {"type": "string"}, "actual": {"type": "string"},
          "confidence": {"type": "string", "description": "confirmed (reproduced), likely, or unsure."},
          "target": {"type": "string", "description": "Optional ref of the control involved (for the screenshot)."}},
         ["title", "severity", "category", "steps", "expected", "actual"]),
    spec("note", "Write a short private note to yourself (what you tested, what to try next). Notes stay visible "
         "to you for the rest of the session even when older steps are summarised.",
         {"text": {"type": "string"}}, ["text"], audiences=("agent",)),
    spec("finish", "End the test session with a summary of what you covered and what you could not test.",
         {"summary": {"type": "string"}, "not_tested": {"type": "string"}}, ["summary"], audiences=("agent",)),
    spec("app_start", "Start (or restart with new options) the sandboxed DT app. Other tools start it "
         "automatically with defaults, so use this only to choose options.",
         {"screen": {"type": "string", "description": "e.g. 1366x768 (default), 1024x768, 800x600, 2560x1440@2."},
          "network": {"type": "string", "description": "block (default), mock or allow."},
          "seed": {"type": "string", "description": "none (first run, default), empty (unlocked empty vault) or "
                                                   "sample (unlocked vault with three synthetic assessments)."},
          "ffmpeg": {"type": "string", "description": "auto (default) or none (hide FFmpeg from DT)."},
          "idle_timeout_ms": {"type": "integer", "description": "Override the 5 minute idle auto-lock."},
          "display": {"type": "string", "description": "window (DT on the screen, so the user can watch) or "
                                                      "headless (no windows). Default: the user's setting."},
          "fresh": {"type": "boolean", "description": "Start from an empty sandbox."}}, audiences=("mcp",)),
    spec("app_stop", "Stop the sandboxed DT app.", audiences=("mcp",)),
    spec("findings", "List the findings recorded in this session (reported issues and harness detections).",
         audiences=("mcp",)),
]


def specs_for(audience):
    return [item for item in TOOL_SPECS if audience in item["audiences"]]


def openai_tools(audience="agent"):
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"],
                                              "parameters": item["parameters"]}} for item in specs_for(audience)]


@dataclass
class ToolResult:
    text: str
    image: bytes = None
    is_error: bool = False
    data: dict = field(default_factory=dict)


class ToolRunner:
    """Executes tools against one AppSession and records findings."""

    ACTIONS = {"click": "click", "type_text": "type_text", "select_option": "select_option",
               "set_checked": "set_checked", "select_item": "select_item", "select_tab": "select_tab",
               "press_key": "press_key", "draw": "draw", "scroll": "scroll", "set_value": "set_value",
               "resize_window": "resize", "close_window": "close_window"}

    def __init__(self, session_dir, app_options=None, reporter="agent", context=None, max_snapshot_chars=16000):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.app_options = dict(app_options or {})
        self.reporter = reporter
        self.store = FindingStore(self.session_dir / "findings.jsonl", context=context)
        self.evidence_dir = self.session_dir / "evidence"
        self.session = None
        self.step = 0
        self.notes = []
        self.finished = None
        self.screens = set()
        self.max_snapshot_chars = max_snapshot_chars
        self.last_state = {}
        self.new_findings = []
        self.trace_path = self.session_dir / "steps.jsonl"
        self.snapshot_dir = self.session_dir / "snapshots"
        self.last_target = None

    # ----- app lifecycle ----------------------------------------------------------------
    def ensure_app(self):
        if self.session is None:
            options = dict(self.app_options)
            options.setdefault("label", self.watch_label())
            self.session = AppSession(self.session_dir / "app", **options)
            self.session.start()
        return self.session

    def watch_label(self):
        """Who is driving, shown with each step when DT is on screen (window mode)."""
        context = self.store.context
        mission, model = context.get("mission"), context.get("model")
        parts = [mission] if mission else []
        if model and model not in ("scenario", "crawler", "cli"):
            parts.append(model)
        elif model == "crawler":
            parts.append(context.get("persona") or "")
        return " \u00b7 ".join(part for part in parts if part)

    def stop(self):
        if self.session is not None:
            self.session.stop()
            self.session = None

    # ----- dispatch ---------------------------------------------------------------------
    def run(self, name, args):
        """Run one tool and append a structured record of it to steps.jsonl."""
        self.step += 1
        self.new_findings = []
        args = dict(args or {})
        started = time.monotonic()
        screen_before = self.describe_screen()
        result = self.dispatch(name, args)
        try:
            self.trace(name, args, result, started, screen_before)
        except OSError:
            pass
        return result

    def dispatch(self, name, args):
        try:
            if name in self.ACTIONS:
                return self.action(self.ACTIONS[name], args)
            handler = getattr(self, "tool_" + name, None)
            if handler is None:
                return ToolResult(f"Unknown tool {name!r}.", is_error=True, data={"error_kind": "unknown_tool"})
            return handler(args)
        except AppCrashed as crash:
            return self.crashed(crash)
        except AppExited as exited:
            return ToolResult(f"{exited} Call restart_app to continue testing.", is_error=True,
                              data={"error_kind": "exited"})
        except AppStartError as error:
            return ToolResult(f"The app could not be started: {error}", is_error=True, data={"error_kind": "start"})
        except HostError as error:
            if error.kind == "hang":
                events = self.fetch_events()
                found = self.record_auto(events)
                lines = [self.format_events_block(events, str(error) + " Use restart_app to recover.")]
                return ToolResult("\n".join(lines + self.finding_lines(found)), is_error=True,
                                  data={"error_kind": "hang", "events": events})
            return ToolResult(f"Could not do that: {error}", is_error=True, data={"error_kind": error.kind})
        except Exception as error:  # noqa: BLE001 - a harness fault must not end the session
            import traceback
            detail = traceback.format_exc(limit=6)
            with (self.session_dir / "harness-errors.log").open("a", encoding="utf-8") as handle:
                handle.write(detail + "\n")
            return ToolResult(f"Harness error ({type(error).__name__}: {error}). This is a problem in the test "
                              "harness, not in DT; try another action or restart_app.", is_error=True,
                              data={"error_kind": "harness"})

    def action(self, action, args):
        session = self.ensure_app()
        host_args = {key: value for key, value in args.items() if value is not None}
        if "action" in host_args:  # select_item's row action; "action" names the host command
            host_args["mode"] = host_args.pop("action")
        if "target" in host_args and "ref" not in host_args:
            host_args["ref"] = host_args["target"]
        host_args["jev_step"] = self.step
        if action == "draw" and isinstance(host_args.get("strokes"), str):
            try:
                host_args["strokes"] = json.loads(host_args["strokes"])
            except json.JSONDecodeError:
                return ToolResult("strokes must be JSON, e.g. [[[0.1,0.5],[0.9,0.5]]]", is_error=True)
        result = session.act(action, **host_args)
        self.track(result.get("state"))
        found = self.record_auto(result.get("events", []))
        lines = [f"OK: {result.get('did')}"]
        lines += [f"  note: {note}" for note in result.get("notes", [])]
        if result.get("still_busy"):
            lines.append("  The app is still busy with a background job; use wait to let it finish.")
        lines.append(self.format_events_block(result.get("events", [])))
        lines += self.finding_lines(found)
        if result.get("snapshot"):
            lines += ["", "Snapshot after the action:", self.clip(result["snapshot"])]
        return ToolResult("\n".join(line for line in lines if line is not None),
                          data={"target": result.get("target"), "events": result.get("events", []),
                                "snapshot": result.get("snapshot"), "notes": result.get("notes", []),
                                "nodes": result.get("nodes", [])})

    def tool_snapshot(self, args):
        session = self.ensure_app()
        result = session.call("snapshot", {"full": bool(args.get("full")), "max_items": args.get("max_items") or 8})
        self.track(result.get("state"))
        events = self.fetch_events()
        found = self.record_auto(events)
        text = self.clip(result["text"])
        meanwhile = [format_event(event) for event in events if event.get("kind") not in ("action",)]
        meanwhile = [item for item in meanwhile if item]
        extra = (["", "Since the last action:"] + [f"  - {item}" for item in meanwhile[-15:]] if meanwhile else [])
        extra += self.finding_lines(found)
        return ToolResult(text + ("\n" + "\n".join(extra) if extra else ""),
                          data={"snapshot": result["text"], "events": events, "nodes": result.get("nodes", [])})

    def tool_screenshot(self, args):
        session = self.ensure_app()
        result = session.call("screenshot", {"ref": args.get("target"), "marks": bool(args.get("marks"))})
        image = base64.b64decode(result["png_base64"])
        path = self.save_image(image, f"step{self.step:03d}")
        return ToolResult(f"Screenshot {result['width']}x{result['height']} saved to {path}.", image=image,
                          data={"path": str(path)})

    def tool_wait(self, args):
        session = self.ensure_app()
        result = session.call("wait", {"seconds": args.get("seconds", 2), "until": args.get("until"),
                                       "snapshot": args.get("snapshot", True), "events_since": session.last_seq},
                              timeout=180)
        session.last_seq = max(session.last_seq, result.get("seq", 0))
        self.track(result.get("state"))
        found = self.record_auto(result.get("events", []))
        lines = [f"Waited {result.get('waited')}s.", self.format_events_block(result.get("events", []))]
        lines += self.finding_lines(found)
        if result.get("snapshot"):
            lines += ["", self.clip(result["snapshot"])]
        return ToolResult("\n".join(lines), data={"events": result.get("events", []),
                                                  "snapshot": result.get("snapshot")})

    def tool_read_text(self, args):
        hints = {key: args[key] for key in ("role", "index", "tab_hint") if args.get(key) is not None}
        result = self.ensure_app().call("read_text", {"ref": args.get("target"), **hints})
        return ToolResult(f"{result['target']}:\n{self.clip(result['text'], 12000)}")

    def tool_list_items(self, args):
        result = self.ensure_app().call("list_items", {"ref": args.get("target"), "offset": args.get("offset") or 0,
                                                       "limit": args.get("limit") or 50})
        return ToolResult(f"{result['target']}: {result['total']} rows\n" + "\n".join(result["items"]))

    def tool_events(self, args):
        session = self.ensure_app()
        since = args.get("since")
        result = session.call("events", {"since": since if since is not None else 0, "limit": 40})
        return ToolResult(self.format_events_block(result["events"], header="Events:", verbose=True)
                          + f"\n(latest sequence number {result['seq']})")

    def tool_audit(self, args):
        result = self.ensure_app().call("audit", {"kind": args.get("kind") or "all"})
        lines = [f"Audit of: {', '.join(result['windows'])}"]
        if not result["findings"]:
            lines.append("No layout or accessibility problems detected by the heuristics.")
        for item in result["findings"]:
            lines.append(f"- {item['check']}: {item['widget']} - {item['detail']}")
        if result.get("focus_order"):
            lines += ["", "Tab order from the focused control:"] + [f"  {entry}" for entry in result["focus_order"]]
        lines.append("\nHeuristics can be wrong: confirm with a screenshot before reporting.")
        return ToolResult("\n".join(lines))

    def tool_network_log(self, args):
        result = self.ensure_app().call("network_log", {"count": args.get("count") or 3})
        if not result["requests"]:
            return ToolResult(f"No outgoing requests yet (network mode {result['mode']}).")
        return ToolResult(f"Network mode {result['mode']}, mock scenarios {result['scenarios']}\n" +
                          self.clip(json.dumps(result["requests"], indent=1, default=str), 12000))

    def tool_set_network_mock(self, args):
        result = self.ensure_app().call("set_mock", {"scenario": args.get("scenario"), "service": args.get("service"),
                                                     "delay": args.get("delay")})
        note = "" if result.get("mode") == "mock" else " Note: the app is not in mock mode, so requests are " \
                                                       "blocked anyway; restart_app with network=mock to use this."
        return ToolResult(f"Mock scenarios now: {result}.{note}")

    def tool_sandbox_info(self, args):
        info = self.ensure_app().info()
        return ToolResult(json.dumps(info, indent=1, ensure_ascii=False))

    def tool_restart_app(self, args):
        overrides = {key: args.get(key) for key in ("screen", "network", "idle_timeout_ms") if args.get(key)}
        if args.get("fresh") and args.get("seed"):
            overrides["seed"] = args["seed"]
        if self.session is None:
            self.app_options.update(overrides)
            self.ensure_app()
        else:
            self.session.restart(fresh=bool(args.get("fresh")), **overrides)
        snapshot = self.session.call("snapshot")
        self.track(snapshot.get("state"))
        return ToolResult("The app was restarted" + (" with a fresh sandbox" if args.get("fresh") else
                                                     ", keeping the sandbox") + ".\n\n" + self.clip(snapshot["text"]))

    def tool_app_start(self, args):
        options = {key: args.get(key) for key in ("screen", "network", "seed", "ffmpeg", "idle_timeout_ms", "display")
                   if args.get(key) is not None}
        self.app_options.update(options)
        if self.session is not None:
            self.session.restart(fresh=bool(args.get("fresh")), **options)
        else:
            if args.get("fresh"):
                import shutil
                shutil.rmtree(self.session_dir / "app" / "sandbox", ignore_errors=True)
            self.ensure_app()
        snapshot = self.session.call("snapshot")
        return ToolResult(f"App started with {self.app_options}.\n\n{self.clip(snapshot['text'])}")

    def tool_app_stop(self, args):
        self.stop()
        return ToolResult("App stopped.")

    def tool_findings(self, args):
        if not self.store.findings:
            return ToolResult("No findings recorded yet.")
        return ToolResult("\n".join(self.store.titles()) + f"\n\nFile: {self.store.path}")

    def tool_note(self, args):
        text = str(args.get("text", "")).strip()
        if text:
            self.notes.append(text[:600])
        return ToolResult(f"Noted ({len(self.notes)} notes).")

    def tool_finish(self, args):
        self.finished = {"summary": args.get("summary", ""), "not_tested": args.get("not_tested", "")}
        return ToolResult("Session finished. Thank you.", data={"finished": True})

    def tool_report_issue(self, args):
        severity = str(args.get("severity", "medium")).lower()
        category = str(args.get("category", "other")).lower()
        if severity not in SEVERITIES:
            severity = "medium"
        if category not in CATEGORIES:
            category = "other"
        finding = {"source": self.reporter, "title": str(args.get("title", "")).strip()[:200] or "Untitled issue",
                   "severity": severity, "category": category, "steps": args.get("steps", ""),
                   "expected": args.get("expected", ""), "actual": args.get("actual", ""),
                   "confidence": args.get("confidence", "likely"), "step": self.step,
                   "screen": self.describe_screen()}
        duplicate = self.similar_existing(finding["title"])
        finding["evidence"] = self.capture_evidence(finding, args.get("target"))
        stored, created = self.store.add(finding)
        text = f"Recorded {stored['id']}: [{severity}] {finding['title']}."
        if duplicate:
            text += f" It looks similar to {duplicate}; make sure it is a distinct problem."
        return ToolResult(text, data={"finding": stored})

    # ----- trace -----------------------------------------------------------------------
    def trace(self, name, args, result, started, screen_before):
        data = result.data or {}
        events = data.get("events") or []
        if data.get("target") and not result.is_error:
            self.last_target = {key: data["target"].get(key) for key in ("key", "role", "name", "window", "tab")}
        record = {"step": self.step, "time": round(time.time(), 3), "tool": name, "args": trace_arguments(args),
                  "ok": not result.is_error, "latency_ms": round((time.monotonic() - started) * 1000),
                  "screen_before": screen_before, "screen_after": self.describe_screen(),
                  "target": data.get("target"), "events": summarise_events(events),
                  "findings": [finding["id"] for finding in self.new_findings]}
        if result.is_error:
            record["error"] = result.text.strip().splitlines()[0][:300] if result.text.strip() else ""
            record["error_kind"] = data.get("error_kind", "")
        if data.get("notes"):
            record["notes"] = data["notes"][:5]
        snapshot = data.get("snapshot")
        if snapshot:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            path = self.snapshot_dir / f"step{self.step:04d}.txt"
            path.write_text(snapshot, encoding="utf-8")
            record["snapshot"] = path.relative_to(self.session_dir).as_posix()
        if data.get("nodes"):
            record["controls"] = [node.get("key") for node in data["nodes"] if node.get("interactive", True)
                                  and node.get("role") != "text"][:400]
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

    # ----- helpers ----------------------------------------------------------------------
    def fetch_events(self):
        if self.session is None or self.session.client is None:
            return []
        try:
            result = self.session.call("events", {"since": self.session.last_seq, "limit": 200})
        except (HostError, AppCrashed, AppExited):
            return []
        self.session.last_seq = max(self.session.last_seq, result.get("seq", 0))
        return result.get("events", [])

    def record_auto(self, events):
        found = []
        for finding in auto_findings(events, step=self.step, screen=self.describe_screen()):
            stored, created = self.store.add(finding)
            if created:
                found.append(stored)
                if stored.get("category") in ("copy", "exception", "other", "performance"):
                    # The screen still shows what went wrong; a frozen or crashed app cannot be captured.
                    evidence = self.capture_evidence(stored, stem=stored["id"])
                    if evidence:
                        self.store.update(stored["id"], evidence=evidence)
        self.new_findings.extend(found)
        return found

    def crashed(self, crash):
        where = crash_location(crash.details.get("fault_log") or "")
        finding = {"source": "harness", "title": "The app crashed" + (f" in {where}" if where else ""),
                   "severity": "critical", "category": "crash",
                   "signature": f"crash@{where or crash.details.get('exit_code')}",
                   "actual": str(crash), "step": self.step, "screen": self.describe_screen(),
                   "details": (crash.details.get("fault_log") or "") + "\n--- host log ---\n" +
                              (crash.details.get("log_tail") or "")}
        stored, _ = self.store.add(finding)
        self.new_findings.append(stored)
        return ToolResult(f"{crash}\nRecorded as {stored['id']} (critical). Note what you did just before this, "
                          "then call restart_app to continue.\n--- fault log ---\n" +
                          (crash.details.get("fault_log") or "(empty)")[-3000:], is_error=True,
                          data={"error_kind": "crash"})

    def track(self, state):
        if not state:
            return
        self.last_state = state
        modal = state.get("modal") or {}
        screen = modal.get("title") or state.get("screen", "")
        if state.get("tab") and not modal:
            screen = f"main window / {state['tab']}"
        if screen:
            self.screens.add(screen)

    def describe_screen(self):
        state = self.last_state or {}
        modal = state.get("modal") or {}
        if modal:
            return f"dialog '{modal.get('title')}'"
        if state.get("tab"):
            return f"main window, tab '{state['tab']}'"
        return state.get("screen", "")

    def similar_existing(self, title):
        import difflib
        from .findings import normalise_title
        wanted = normalise_title(title)
        for finding in self.store.findings:
            if difflib.SequenceMatcher(None, wanted, normalise_title(finding["title"])).ratio() > 0.8:
                return f"{finding['id']} ({finding['title']})"
        return ""

    def capture_evidence(self, finding, target=None, stem=None):
        evidence = {}
        if self.session is None or self.session.client is None:
            return evidence
        try:
            number = stem or f"F{len(self.store.findings) + 1:03d}"
            shot = self.session.call("screenshot", {"marks": False})
            evidence["screenshot"] = str(self.save_image(base64.b64decode(shot["png_base64"]), number))
            snapshot = self.session.call("snapshot")
            path = self.evidence_dir / f"{number}-snapshot.txt"
            path.write_text(snapshot["text"], encoding="utf-8")
            evidence["snapshot"] = str(path)
            node = find_node(snapshot.get("nodes") or [], target)
            if node:
                evidence["target"] = {key: node.get(key) for key in ("key", "role", "name", "window", "tab")}
            if self.last_target:
                evidence["last_action_target"] = self.last_target
            events = self.session.call("events", {"since": max(0, self.session.last_seq - 25), "limit": 25})
            path = self.evidence_dir / f"{number}-events.json"
            path.write_text(json.dumps(events["events"], indent=1, default=str), encoding="utf-8")
            evidence["events"] = str(path)
        except Exception as error:  # noqa: BLE001 - evidence is best effort
            evidence["error"] = repr(error)
        return evidence

    def save_image(self, data, stem):
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"{stem}.png"
        path.write_bytes(data)
        return path

    def clip(self, text, limit=None):
        limit = limit or self.max_snapshot_chars
        return text if len(text) <= limit else text[:limit] + f"\n… [snapshot truncated at {limit} characters]"

    def finding_lines(self, found):
        return [f"HARNESS DETECTED {item['id']} [{item['severity']}]: {item['title']} (recorded automatically)"
                for item in found]

    @staticmethod
    def format_events_block(events, header="What happened:", verbose=False):
        lines = []
        for event in events:
            text = format_event(event, verbose)
            if text:
                lines.append(f"  - {text}")
        if not lines:
            return f"{header} no dialogs, messages or errors." if header == "What happened:" else f"{header} none."
        return header + "\n" + "\n".join(lines)


def crash_location(fault_log):
    """The innermost DT frame of the crashing thread in a faulthandler dump, e.g. dt/ui.py:825."""
    import re
    section = fault_log.split("Current thread", 1)[-1]
    for match in re.finditer(r'File "([^"]+)", line (\d+) in (\w+)', section):
        path = match.group(1).replace("\\", "/")
        if "/dt/" in path:
            return f"dt/{path.rsplit('/dt/', 1)[1]}:{match.group(2)} in {match.group(3)}"
    return ""


def trace_arguments(args):
    kept = {}
    for key, value in args.items():
        if key == "snapshot":
            continue
        if isinstance(value, str) and len(value) > 500:
            value = value[:500] + f"... ({len(value)} characters)"
        kept[key] = value
    return kept


def find_node(nodes, target):
    """The snapshot node a tester's target (a ref or a visible label) refers to."""
    if not target:
        return None
    wanted = str(target).strip().strip("[]")
    for node in nodes:
        if node.get("ref") == wanted:
            return node
    folded = wanted.casefold()
    for node in nodes:
        if (node.get("name") or "").casefold() == folded:
            return node
    return None


def summarise_events(events):
    """A compact, analysable digest of the events one step produced."""
    summary = {"counts": {}}
    for event in events:
        kind = event.get("kind", "")
        summary["counts"][kind] = summary["counts"].get(kind, 0) + 1
        if kind == "dialog" and event.get("phase") == "opened":
            item = {"title": event.get("title", ""), "class": event.get("class", "")}
            if event.get("message"):
                item["message"] = str(event["message"])[:300]
                item["icon"] = event.get("icon")
            summary.setdefault("dialogs", []).append(item)
        elif kind == "status":
            summary.setdefault("status", []).append(str(event.get("message", ""))[:200])
        elif kind == "exception":
            summary.setdefault("exceptions", []).append(event.get("signature"))
        elif kind == "network":
            summary.setdefault("network", []).append(f"{event.get('decision')} {event.get('method')} {event.get('host')}")
        elif kind == "stall":
            summary.setdefault("stalls", []).append(event.get("seconds"))
        elif kind == "sandbox":
            summary.setdefault("sandbox", []).append(f"{event.get('decision')} {event.get('what')}")
        elif kind == "suspicious_text":
            summary.setdefault("suspicious_text", []).append(str(event.get("text", ""))[:200])
    if "status" in summary:
        summary["status"] = summary["status"][-4:]
    return summary


def format_event(event, verbose=False):
    kind = event.get("kind")
    if kind == "action" and not verbose:
        return ""
    if kind == "action":
        return f"#{event['seq']} action: {event.get('did')}"
    prefix = f"#{event['seq']} " if verbose else ""
    if kind == "dialog" and event.get("phase") == "opened":
        if event.get("class") == "QMessageBox":
            return (f"{prefix}message box opened ({event.get('icon')}) \"{event.get('title')}\": "
                    f"\"{event.get('message')}\"" + (f" / \"{event.get('informative')}\"" if event.get("informative") else "")
                    + f" buttons {event.get('buttons')}")
        return f"{prefix}dialog opened: \"{event.get('title')}\" ({event.get('class')}{', modal' if event.get('modal') else ''})"
    if kind == "dialog":
        return f"{prefix}dialog closed: \"{event.get('title')}\" ({event.get('outcome')})"
    if kind == "status":
        return f"{prefix}status bar: \"{event.get('message')}\""
    if kind == "exception":
        return (f"{prefix}UNHANDLED EXCEPTION {event.get('type')}: {event.get('message')} at {event.get('location')}"
                + (f"\n{event.get('traceback')}" if verbose else ""))
    if kind == "qt_message":
        return f"{prefix}Qt {event.get('level')}: {event.get('message')}"
    if kind == "network":
        after = event.get("after_dialog")
        return (f"{prefix}network {event.get('decision').upper()}: {event.get('method')} {event.get('url')} "
                f"({event.get('body_bytes', 0)} bytes)" + (f"; last dialog before it: {after}" if after else ""))
    if kind == "sandbox":
        return f"{prefix}sandbox {event.get('decision')}: {event.get('what')} {event.get('path')}"
    if kind == "stall":
        return f"{prefix}INTERFACE FROZE for {event.get('seconds')}s"
    if kind == "hang":
        return f"{prefix}APP HANG: {event.get('summary')}"
    if kind == "file_chooser":
        return f"{prefix}file chooser \"{event.get('caption')}\" -> {event.get('chosen')}"
    if kind == "suspicious_text":
        return f"{prefix}technical error text shown to the user in {event.get('where')}: \"{event.get('text')}\""
    if kind == "layout_warning":
        return f"{prefix}layout warning: {event.get('target')} {event.get('problem')}"
    if kind in ("harness_error", "harness_note"):
        return f"{prefix}harness: {event.get('error') or event.get('note')}"
    if kind == "app":
        return f"{prefix}app {event.get('phase')}" + (f" (code {event.get('code')})" if "code" in event else "")
    return f"{prefix}{kind}: {json.dumps({k: v for k, v in event.items() if k not in ('seq', 'time', 'kind')})[:300]}"
