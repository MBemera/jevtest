"""Control server inside the app process.

A background thread accepts JSON-lines requests on 127.0.0.1 (token protected) and runs
each command on the Qt GUI thread through a queued signal. Queued signals are delivered by
nested event loops too, so the harness keeps working while a modal dialog is open.
"""

import base64
import contextlib
import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, QRect, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QApplication, QComboBox, QLabel,
                               QLineEdit, QListView, QMainWindow, QPlainTextEdit, QScrollArea, QTabWidget,
                               QTextEdit, QTreeWidget, QWidget)

from . import audits
from .actions import ActionError, Actions, InputScheduler, read_text
from .describe import INPUT_ROLES, LabelIndex, Refs, Snapshotter, clean, is_popup, name_of, role_of
from .monitor import main_thread_stack
from .watch import Watch

HANG_SECONDS = 20.0


class UiUnresponsive(Exception):
    pass


INTERNAL_ARGUMENTS = {"action", "events_since", "snapshot", "settle", "wait_busy", "ref", "nodes", "jev_step"}


def action_arguments(args):
    """The user-level arguments of an action, trimmed for the event log (no internals)."""
    kept = {}
    for key, value in args.items():
        if key in INTERNAL_ARGUMENTS:
            continue
        if key == "strokes":
            value = f"{len(value)} stroke(s)" if isinstance(value, list) else "custom"
        elif isinstance(value, str) and len(value) > 300:
            value = value[:300] + f"... ({len(value)} characters)"
        kept[key] = value
    return kept


class Job:
    def __init__(self, function):
        self.function = function
        self.done = threading.Event()
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.function()
        except BaseException as error:  # noqa: BLE001 - reported to the caller
            self.error = error
            self.error_traceback = traceback.format_exc(limit=8)
        finally:
            self.done.set()


class Bridge(QObject):
    submit = Signal(object)

    def __init__(self):
        super().__init__()
        self.submit.connect(self.execute, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def execute(self, job):
        job.run()


class Host:
    def __init__(self, session_dir, sandbox, log, network, observer, options):
        self.session_dir = session_dir
        self.sandbox = sandbox
        self.log = log
        self.network = network
        self.observer = observer
        self.options = options
        self.token = secrets.token_hex(16)
        self.bridge = None
        self.refs = Refs()
        self.snapshotter = Snapshotter(self.refs)
        self.scheduler = InputScheduler(log)
        self.actions = Actions(self.refs, self.snapshotter, self.scheduler, log)
        # Window mode: show each step on screen before it happens, at a pace a person can follow.
        self.watch = Watch(options.get("pace", 0.5), options.get("label", "")) \
            if options.get("display") == "window" else None
        self.command_lock = threading.Lock()
        self.exited = None
        self.server = None

    # ----- lifecycle -----------------------------------------------------------------
    def attach(self):
        """Called on the GUI thread as soon as QApplication exists."""
        self.bridge = Bridge()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        port = self.server.getsockname()[1]
        threading.Thread(target=self.accept_loop, name="jev-control", daemon=True).start()
        ready = {"port": port, "token": self.token, "pid": os.getpid(), "sandbox": str(self.sandbox),
                 "python": sys.executable, "started": time.time()}
        temporary = os.path.join(self.session_dir, "ready.json.tmp")
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(ready, handle)
        os.replace(temporary, os.path.join(self.session_dir, "ready.json"))

    def accept_loop(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(connection,), daemon=True).start()

    def serve(self, connection):
        with connection:
            stream = connection.makefile("rwb")
            for raw in stream:
                try:
                    request = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.reply(stream, {"ok": False, "error": "invalid JSON request"})
                    continue
                if request.get("token") != self.token:
                    self.reply(stream, {"id": request.get("id"), "ok": False, "error": "bad token"})
                    continue
                response = self.handle(request.get("cmd", ""), request.get("args") or {})
                response["id"] = request.get("id")
                self.reply(stream, response)

    @staticmethod
    def reply(stream, payload):
        try:
            stream.write((json.dumps(payload, default=str) + "\n").encode("utf-8"))
            stream.flush()
        except OSError:
            pass

    # ----- GUI thread access ---------------------------------------------------------
    def gui(self, function, timeout=HANG_SECONDS):
        if self.exited is not None:
            raise RuntimeError(f"the app has exited (code {self.exited})")
        job = Job(function)
        self.bridge.submit.emit(job)
        deadline = time.monotonic() + timeout
        while not job.done.wait(0.05):
            if self.exited is not None:
                raise RuntimeError(f"the app has exited (code {self.exited})")
            if time.monotonic() < deadline:
                continue
            stack = main_thread_stack()
            self.log.emit("hang", seconds=timeout, stack=stack,
                          summary=f"The interface thread did not respond for {timeout:.0f}s")
            raise UiUnresponsive(f"The app's interface thread has not responded for {timeout:.0f}s "
                                 "(the app looks frozen). The stack of the frozen thread is in the events.")
        if job.error is not None:
            raise job.error
        return job.result

    # ----- command dispatch ----------------------------------------------------------
    def handle(self, command, args):
        handler = getattr(self, "cmd_" + command, None)
        if handler is None:
            return {"ok": False, "error": f"unknown command {command!r}"}
        with self.command_lock:
            try:
                return {"ok": True, "result": handler(args)}
            except ActionError as error:
                return {"ok": False, "error": str(error), "kind": "action"}
            except UiUnresponsive as error:
                return {"ok": False, "error": str(error), "kind": "hang"}
            except Exception as error:  # noqa: BLE001
                return {"ok": False, "error": f"{type(error).__name__}: {error}", "kind": "harness",
                        "traceback": traceback.format_exc(limit=8)}

    def cmd_ping(self, args):
        from PySide6 import __version__ as pyside_version
        return {"pid": os.getpid(), "pyside": pyside_version, "sandbox": str(self.sandbox),
                "network_mode": self.network.mode, "seq": self.log.seq}

    def cmd_state(self, args):
        return self.gui(self.state)

    def cmd_snapshot(self, args):
        full = bool(args.get("full"))
        max_items = int(args.get("max_items") or 8)

        def take():
            self.snapshotter.max_items = max(1, min(max_items, 200))
            text, nodes = self.snapshotter.snapshot(full=full, app_state=self.app_state())
            self.snapshotter.max_items = 8
            return {"text": text, "state": self.state(), "nodes": nodes}

        return self.gui(take)

    def cmd_events(self, args):
        since = int(args.get("since") or 0)
        events = self.log.since(since)
        limit = int(args.get("limit") or 200)
        return {"events": events[-limit:], "seq": self.log.seq}

    def cmd_act(self, args):
        action = args.get("action", "")
        settle = float(args.get("settle", self.options.get("settle", 0.35)))
        busy_wait = float(args.get("wait_busy", self.options.get("wait_busy", 10.0)))
        seq = int(args["events_since"]) if args.get("events_since") is not None else self.log.seq
        before = self.gui(lambda: id(QApplication.activeModalWidget()) if QApplication.activeModalWidget() else 0)
        if self.watch is not None:
            self.gui(lambda: self.announce(action, args))
            time.sleep(self.watch.pace)  # the GUI keeps running and painting while this thread waits
        self.log.action = action
        try:
            def perform():
                self.scheduler.last = None
                return self.actions.perform(action, args), self.scheduler.last

            outcome, sequence = self.gui(perform)
            self.log.emit("action", action=action, did=outcome.get("did", ""), target=outcome.get("target"),
                          args=action_arguments(args))
            warnings = self.wait_for_input(sequence, before)
            time.sleep(max(0.0, settle))
            busy = self.wait_while_busy(busy_wait)
        finally:
            self.log.action = ""
            if self.watch is not None:
                self.gui(self.watch.fade_later)  # stays up until the next step, or a few seconds
        result = {"did": outcome.get("did", ""), "target": outcome.get("target"),
                  "notes": outcome.get("notes", []) + warnings,
                  "events": self.log.since(seq), "seq": self.log.seq, "still_busy": busy,
                  "state": self.gui(self.state)}
        if args.get("snapshot", True) or args.get("nodes"):
            text, nodes = self.gui(lambda: self.snapshotter.snapshot(app_state=self.app_state()))
            if args.get("snapshot", True):
                result["snapshot"] = text
            result["nodes"] = nodes  # structured controls for traces and coverage; computed with the text anyway
        return result

    # ----- window mode ------------------------------------------------------------------
    def announce(self, action, args):
        """Frame the control about to be used and say what is about to happen (GUI thread)."""
        try:
            widget = self.watch_target(action, args)
        except Exception:  # noqa: BLE001 - the action itself reports bad targets
            widget = None
        self.watch.show(widget, self.caption(action, args, widget),
                        window=QApplication.activeModalWidget() or self.main_window())

    def watch_target(self, action, args):
        named = args.get("ref") or args.get("name") or args.get("target")
        if action == "select_tab" and not named:
            return self.actions.find_tab_widget(args.get("tab"))
        if action == "press_key" and not named:
            return QApplication.focusWidget()
        if action in ("close_window", "resize") and not named:
            return QApplication.activeModalWidget() or QApplication.activeWindow()
        if action == "select_item" and not named and args.get("item") is not None:
            return self.actions.list_showing(args["item"], args.get("tab_hint"))
        if not named:
            return None
        roles = {"select_option": ["combobox"], "set_checked": ["checkbox", "radio", "button"],
                 "select_item": ["list", "tree", "table"], "select_tab": ["tabs"], "draw": ["canvas", "container"],
                 "set_value": ["slider", "spinbox"]}.get(action)
        return self.actions.resolve_widget(args, roles)

    def caption(self, action, args, widget):
        name = ""
        if widget is not None:
            try:
                name = self.snapshotter.target_info(widget).get("name") or ""
            except Exception:  # noqa: BLE001 - a caption must never break an action
                name = ""
        name = clean(name or args.get("name") or "")[:50]
        quoted = f'"{name}"' if name else ("the list" if action == "select_item" else "the control")
        if action == "type_text":
            text = str(args.get("text", ""))
            if isinstance(widget, QLineEdit) and widget.echoMode() != QLineEdit.EchoMode.Normal:
                text = "\u2022" * min(len(text), 8)
            shown = text if len(text) <= 40 else text[:39] + "\u2026"
            what = f'Type "{shown}" into {quoted}'
        elif action == "select_option":
            what = f'Choose "{args.get("option")}" in {quoted}'
        elif action == "set_checked":
            what = f"{'Tick' if args.get('checked', True) else 'Untick'} {quoted}"
        elif action == "select_item":
            what = f'{str(args.get("mode") or "select").capitalize()} "{args.get("item")}" in {quoted}'
        elif action == "select_tab":
            what = f'Open the "{args.get("tab")}" tab'
        elif action == "press_key":
            what = f"Press {args.get('keys') or args.get('key')}" + (f" in {quoted}" if name else "")
        elif action == "draw":
            what = f"Draw on {quoted}"
        elif action == "scroll":
            what = f"Scroll {args.get('direction') or 'down'} in {quoted}"
        elif action == "set_value":
            what = f"Set {quoted} to {args.get('value')}"
        elif action == "close_window":
            what = f"Close {quoted if name else 'the window'}"
        elif action == "resize":
            what = f"Resize the window to {args.get('width')}x{args.get('height')}"
        else:
            what = f"Click {quoted}"
        prefix = "Jev" + (f" \u00b7 {self.watch.label}" if self.watch.label else "") + \
            (f" \u00b7 step {args['jev_step']}" if args.get("jev_step") else "")
        return f"{prefix}: {what}"

    def wait_for_input(self, sequence, modal_before, timeout=6.0):
        if sequence is None:
            return []
        deadline = time.monotonic() + timeout
        while True:
            done, modal = self.gui(lambda: (
                sequence.done,
                id(QApplication.activeModalWidget()) if QApplication.activeModalWidget() else 0))
            if done:
                return []
            if modal and modal != modal_before:
                return []  # the input opened a modal dialog and waits inside its event loop
            if time.monotonic() > deadline:
                return ["the input was still being processed when the harness stopped waiting"]
            time.sleep(0.03)

    def wait_while_busy(self, seconds):
        deadline = time.monotonic() + max(0.0, seconds)
        busy = self.gui(self.app_busy)
        while busy and time.monotonic() < deadline:
            time.sleep(0.2)
            busy = self.gui(self.app_busy)
        return busy

    def cmd_wait(self, args):
        seconds = max(0.0, min(float(args.get("seconds", 1.0)), 120.0))
        seq = int(args["events_since"]) if args.get("events_since") is not None else self.log.seq
        until = (args.get("until") or "").lower()
        deadline = time.monotonic() + seconds
        if self.watch is not None and seconds >= 1:
            reason = {"idle": "for DT to finish", "dialog": "for a dialog"}.get(until, "")
            self.gui(lambda: self.watch.show(None, f"Jev: waiting {reason} (up to {seconds:g} s)".replace("  ", " "),
                                             window=QApplication.activeModalWidget() or self.main_window()))
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if until == "idle" and not self.gui(self.app_busy):
                break
            if until == "dialog" and self.gui(lambda: QApplication.activeModalWidget() is not None):
                break
        result = {"waited": round(seconds - max(0.0, deadline - time.monotonic()), 2),
                  "events": self.log.since(seq), "seq": self.log.seq, "state": self.gui(self.state)}
        if args.get("snapshot", False):
            result["snapshot"] = self.gui(lambda: self.snapshotter.snapshot(app_state=self.app_state())[0])
        return result

    def cmd_screenshot(self, args):
        return self.gui(lambda: self.screenshot(args.get("ref"), bool(args.get("marks")),
                                                int(args.get("max_width") or 1600)), timeout=60)

    def cmd_read_text(self, args):
        def read():
            widget = self.actions.resolve(args)
            if not widget.isVisible():
                raise ActionError(f"{self.snapshotter.describe(widget)} is not visible on screen.")
            return {"target": self.snapshotter.describe(widget), "text": read_text(widget)}

        return self.gui(read)

    def cmd_list_items(self, args):
        def items():
            widget = self.actions.resolve(args, roles=["list", "tree", "table", "combobox"])
            if not widget.isVisible():
                raise ActionError(f"{self.snapshotter.describe(widget)} is not visible on screen.")
            text = read_text(widget)
            lines = text.splitlines()
            offset = max(0, int(args.get("offset") or 0))
            limit = max(1, min(int(args.get("limit") or 50), 500))
            return {"target": self.snapshotter.describe(widget), "total": len(lines),
                    "items": lines[offset:offset + limit]}

        return self.gui(items)

    def cmd_audit(self, args):
        kind = (args.get("kind") or "all").lower()
        return self.gui(lambda: audits.run(kind, self.snapshotter, self.refs))

    def cmd_set_mock(self, args):
        return self.network.set_scenario(args.get("scenario", "ok"), args.get("service", "all"), args.get("delay"))

    def cmd_network_log(self, args):
        return {"mode": self.network.mode, "scenarios": self.network.scenarios,
                "requests": self.network.recent(int(args.get("count") or 5))}

    def cmd_quit(self, args):
        force = bool(args.get("force", True))

        def close():
            QApplication.closeAllWindows()
            remaining = [w.windowTitle() for w in QApplication.topLevelWidgets() if w.isVisible() and not is_popup(w)]
            if remaining and force:
                QApplication.exit(0)
            return remaining

        try:
            remaining = self.gui(close, timeout=10)
        except (UiUnresponsive, RuntimeError):
            os._exit(3)
        return {"closed": not remaining, "still_open": remaining}

    # ----- state helpers (GUI thread) ---------------------------------------------------
    def main_window(self):
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMainWindow):
                return widget
        return None

    def app_busy(self):
        window = self.main_window()
        busy = getattr(window, "busy", None)
        try:
            return bool(busy()) if callable(busy) else False
        except Exception:  # noqa: BLE001
            return False

    def app_state(self):
        window = self.main_window()
        state = {}
        if window is None:
            return state
        message = window.statusBar().currentMessage() if window.statusBar() else ""
        state["Status bar"] = f'"{message}"' if message else "(empty)"
        if getattr(window, "locked", False):
            state["Records"] = "LOCKED (lock screen showing)"
        if self.app_busy():
            state["Background job"] = "running (the interface holds other tabs until it finishes)"
        editor = getattr(window, "editor", None)
        if editor is not None and getattr(editor, "dirty", False):
            state["Unsaved edits"] = "yes (autosave pending)"
        return state

    def state(self):
        modal = QApplication.activeModalWidget()
        focus = QApplication.focusWidget()
        window = self.main_window()
        windows = []
        for widget in self.snapshotter.windows():
            windows.append({"ref": self.refs.of(widget), "role": role_of(widget), "title": widget.windowTitle(),
                            "size": [widget.width(), widget.height()], "modal": widget is modal})
        tab = ""
        if window is not None:
            tabs = window.findChild(QTabWidget)
            if tabs is not None and tabs.isVisible():
                tab = clean(tabs.tabText(tabs.currentIndex()))
        return {
            "windows": windows,
            "modal": {"ref": self.refs.of(modal), "title": modal.windowTitle(), "role": role_of(modal)} if modal else None,
            "focus": self.snapshotter.describe(focus) if focus is not None else None,
            "status": window.statusBar().currentMessage() if window is not None and window.statusBar() else "",
            "busy": self.app_busy(),
            "locked": bool(getattr(window, "locked", False)) if window is not None else None,
            "tab": tab,
            "screen": "main window" if window is not None else ("unlock dialog" if modal else "none"),
            "display": "window" if self.watch is not None else "headless",
            "highlight": self.watch.caption if self.watch is not None and self.watch.showing() else "",
        }

    # ----- screenshots ----------------------------------------------------------------
    def screenshot(self, ref=None, marks=False, max_width=1600):
        with (self.watch.hidden_for_capture() if self.watch is not None else contextlib.nullcontext()):
            if ref:
                widget = self.refs.find(ref)
                if widget is None:
                    raise ActionError(f"No widget with reference {ref}.")
                pixmap = widget.grab()
                origin = widget.mapToGlobal(QPoint(0, 0))
                windows = [widget]
            else:
                screen = QApplication.primaryScreen().geometry()
                pixmap = QPixmap(screen.size())
                pixmap.fill(QColor("#2e3440"))
                painter = QPainter(pixmap)
                windows = self.snapshotter.windows()
                popup = QApplication.activePopupWidget()
                for window in windows + ([popup] if popup is not None else []):
                    painter.drawPixmap(window.geometry().topLeft() - screen.topLeft(), window.grab())
                painter.end()
                origin = screen.topLeft()
        if marks:
            self.draw_marks(pixmap, windows, origin)
        if pixmap.width() > max_width:
            pixmap = pixmap.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG")
        buffer.close()
        return {"png_base64": base64.b64encode(bytes(data)).decode("ascii"),
                "width": pixmap.width(), "height": pixmap.height()}

    def draw_marks(self, pixmap, windows, origin):
        painter = QPainter(pixmap)
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        modal = QApplication.activeModalWidget()
        for window in windows:
            if modal is not None and window is not modal and not modal.isAncestorOf(window):
                continue
            labels = LabelIndex([window])
            for node in self.snapshotter.collect(window, labels):
                if node.role not in INPUT_ROLES or node.widget.visibleRegion().isEmpty():
                    continue
                ref = self.refs.of(node.widget)
                top_left = node.widget.mapToGlobal(QPoint(0, 0)) - origin
                rect = QRect(top_left, node.widget.size())
                painter.setPen(QPen(QColor("#d10fd1"), 2))
                painter.drawRect(rect)
                tag = QRect(rect.topLeft(), QPoint(rect.left() + 8 + 7 * len(ref), rect.top() + 14))
                painter.fillRect(tag, QColor("#d10fd1"))
                painter.setPen(QColor("white"))
                painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, ref)
        painter.end()
