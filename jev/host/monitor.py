"""Event log for everything the harness observes inside the app process.

Events are the main bug signal: uncaught exceptions, Qt warnings, dialogs, status bar
messages, network attempts, sandbox refusals and interface stalls. Each event gets a
sequence number so a caller can ask for "everything since my last action".
"""

import json
import os
import re
import sys
import threading
import time
import traceback

MAX_EVENTS = 5000
MAX_TEXT = 4000

# Phrases that show a raw programming error reached the user instead of a written message.
RAW_ERROR_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in (
        r"traceback \(most recent call last\)",
        r"object has no attribute",
        r"'NoneType' object",
        r"\bNoneType\b",
        r"list index out of range",
        r"string index out of range",
        r"is not subscriptable",
        r"unexpected keyword argument",
        r"missing \d+ required positional argument",
        r"invalid literal for int\(\)",
        r"could not convert string to float",
        r"\[Errno \d+\]",
        r"\bStopIteration\b",
        r"\bKeyError\b",
        r"\bAttributeError\b",
        r"\bTypeError\b",
        r"object is not iterable",
        r"Internal C\+\+ object .* already deleted",
        r"sqlite3\.",
        r"\bJSONDecodeError\b",
        r"Expecting value: line \d+",
        r"\b0x[0-9a-f]{8,}\b",
        r"\[[\w,]+ @ 0x[0-9a-f]+\]",
        r"Invalid data found when processing input",
        r"moov atom not found",
    )
]
# A message that is only a quoted identifier, e.g. "'fleet_id'", is usually str(KeyError).
BARE_KEY_PATTERN = re.compile(r"^\s*['\"]?[A-Za-z_][\w.@:-]*['\"]?\s*$")


def raw_error_reason(text):
    """Return why a user-visible message looks like a leaked programming error, or ''."""
    if not text or not text.strip():
        return ""
    for pattern in RAW_ERROR_PATTERNS:
        if pattern.search(text):
            return f"matches {pattern.pattern!r}"
    stripped = text.strip()
    if BARE_KEY_PATTERN.match(stripped) and (stripped[0] in "'\"" or "_" in stripped):
        return "message is a bare identifier, which is typical of str(KeyError)"
    return ""


def clip(text, limit=MAX_TEXT):
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more characters]"


class EventLog:
    def __init__(self, path=None):
        self._lock = threading.Lock()
        self._events = []
        self._seq = 0
        self._file = open(path, "a", encoding="utf-8") if path else None
        self.action = ""  # description of the harness action in progress, for context

    @property
    def seq(self):
        with self._lock:
            return self._seq

    def emit(self, kind, **data):
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "time": round(time.time(), 3), "kind": kind}
            if self.action:
                event["during"] = self.action
            event.update(data)
            self._events.append(event)
            if len(self._events) > MAX_EVENTS:
                del self._events[: len(self._events) - MAX_EVENTS]
            if self._file:
                try:
                    self._file.write(json.dumps(event, default=str) + "\n")
                    self._file.flush()
                except (OSError, ValueError):
                    pass
            return event

    def since(self, seq):
        with self._lock:
            return [event for event in self._events if event["seq"] > seq]

    def last(self, count):
        with self._lock:
            return list(self._events[-count:])


def frames_of(tb_or_stack):
    frames = []
    for frame in tb_or_stack:
        frames.append({"file": frame.filename, "line": frame.lineno, "function": frame.name,
                       "code": (frame.line or "").strip()})
    return frames


def app_frame(frames, app_marker):
    """The innermost frame that belongs to the app under test, for grouping duplicates."""
    for frame in reversed(frames):
        path = frame["file"].replace("\\", "/")
        if app_marker in path:
            return frame
    return frames[-1] if frames else None


def exception_event(log, exc_type, exc_value, exc_tb, *, thread="main", app_marker="/dt/", source="excepthook"):
    frames = frames_of(traceback.extract_tb(exc_tb)) if exc_tb else []
    where = app_frame(frames, app_marker)
    location = f"{short_path(where['file'])}:{where['line']} in {where['function']}" if where else "unknown"
    signature = f"{exc_type.__name__}@{location}"
    formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return log.emit("exception", source=source, thread=thread, type=exc_type.__name__,
                    message=clip(str(exc_value), 1000), location=location, signature=signature,
                    frames=frames[-12:], traceback=clip(formatted, 6000))


def short_path(path):
    path = path.replace("\\", "/")
    for marker in ("/site-packages/", "/src/"):
        if marker in path:
            return path.split(marker, 1)[1]
    return path.rsplit("/", 3)[-1] if path.count("/") > 3 else path


def install_exception_hooks(log, app_marker="/dt/"):
    previous_hook = sys.excepthook

    def excepthook(exc_type, exc_value, exc_tb):
        exception_event(log, exc_type, exc_value, exc_tb, thread="main", app_marker=app_marker)
        previous_hook(exc_type, exc_value, exc_tb)

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "unknown"
        exception_event(log, args.exc_type, args.exc_value, args.exc_traceback, thread=name,
                        app_marker=app_marker, source="threading")
        sys.__stderr__.write("".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                                 args.exc_traceback)))

    def unraisable_hook(unraisable):
        exception_event(log, type(unraisable.exc_value), unraisable.exc_value, unraisable.exc_traceback,
                        thread="unraisable", app_marker=app_marker, source="unraisable")

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    sys.unraisablehook = unraisable_hook


def main_thread_stack(limit=25):
    """Capture the GUI thread's current Python stack, to explain a freeze."""
    frame = sys._current_frames().get(threading.main_thread().ident)
    if frame is None:
        return []
    return frames_of(traceback.extract_stack(frame))[-limit:]


class StallWatchdog:
    """Reports when the interface thread stops processing events for too long.

    The GUI thread refreshes ``heartbeat`` from a 100 ms timer. A background thread
    notices when it goes stale and records what the GUI thread was doing at that moment.
    """

    def __init__(self, log, threshold_seconds=1.5):
        self.log = log
        self.threshold = threshold_seconds
        self.heartbeat = time.monotonic()
        self.paused = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="jev-stall-watchdog", daemon=True)

    def beat(self):
        self.heartbeat = time.monotonic()

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _watch(self):
        stalled_since = None
        stack = []
        while not self._stop.wait(0.1):
            lag = time.monotonic() - self.heartbeat
            if self.paused:
                stalled_since = None
                continue
            if lag >= self.threshold and stalled_since is None:
                stalled_since = self.heartbeat
                stack = main_thread_stack()
            elif lag < self.threshold and stalled_since is not None:
                duration = round(self.heartbeat - stalled_since, 2)
                self.log.emit("stall", seconds=duration, stack=stack,
                              summary=f"Interface thread did not process events for {duration}s")
                stalled_since = None


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")
