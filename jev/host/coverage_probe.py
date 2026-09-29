"""Which lines of DT ran while a tester used it.

Uses coverage.py when the app interpreter has it (fast C tracer), else an optional pure
Python line tracer limited to DT's own files. DT's workers are QThreads rather than Python
threads, so their run() methods are wrapped to join the trace. Results are written to
coverage.json in the session folder periodically and when the app exits.
"""

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path


def dt_package_dir():
    spec = importlib.util.find_spec("dt")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(list(spec.submodule_search_locations)[0]).resolve()


class LineTracer:
    """Records (file, line) for frames inside one package; everything else is skipped cheaply."""

    def __init__(self, package_dir):
        self.prefix = str(package_dir)
        self.lines = {}
        self.lock = threading.Lock()

    def global_trace(self, frame, event, arg):
        if event != "call" or not frame.f_code.co_filename.startswith(self.prefix):
            return None
        return self.local_trace

    def local_trace(self, frame, event, arg):
        if event == "line":
            filename = frame.f_code.co_filename
            lines = self.lines.get(filename)
            if lines is None:
                with self.lock:
                    lines = self.lines.setdefault(filename, set())
            lines.add(frame.f_lineno)
        return self.local_trace

    def start(self):
        threading.settrace(self.global_trace)
        sys.settrace(self.global_trace)

    def stop(self):
        sys.settrace(None)
        threading.settrace(None)

    def data(self):
        with self.lock:
            return {filename: sorted(lines) for filename, lines in self.lines.items()}


class CoverageProbe:
    def __init__(self, session_dir, mode="auto", log=None):
        self.path = Path(session_dir) / "coverage.json"
        self.mode = mode
        self.log = log
        self.package_dir = dt_package_dir()
        self.engine = None
        self.kind = "off"
        self.lock = threading.Lock()
        self.previous = {}

    def start(self):
        if self.mode == "off" or self.package_dir is None:
            return
        # A restarted app reuses its session folder: keep what the earlier process measured.
        try:
            earlier = json.loads(self.path.read_text(encoding="utf-8"))
            if earlier.get("package") == str(self.package_dir):
                self.previous = {key: set(lines) for key, lines in earlier.get("files", {}).items()}
        except (OSError, ValueError, AttributeError):
            self.previous = {}
        try:
            import coverage
            self.engine = coverage.Coverage(data_file=None, source=[str(self.package_dir)], branch=False,
                                            config_file=False)
            self.engine.start()
            self.kind = f"coverage.py {coverage.__version__}"
        except ImportError:
            if self.mode != "on":
                return
            self.engine = LineTracer(self.package_dir)
            self.engine.start()
            self.kind = "python line tracer"
        wrap_qthreads()
        threading.Thread(target=self.periodic_flush, name="jev-coverage", daemon=True).start()

    def periodic_flush(self):
        """The pure-Python tracer can be read safely while running; coverage.py is saved on exit."""
        while self.engine is not None:
            time.sleep(20)
            engine = self.engine
            if isinstance(engine, LineTracer):
                self.write(engine.data())

    @staticmethod
    def collected(engine):
        if isinstance(engine, LineTracer):
            return engine.data()
        data = engine.get_data()
        return {filename: sorted(data.lines(filename) or []) for filename in data.measured_files()}

    def write(self, files):
        base = self.package_dir.parent
        relative = {}
        for filename, lines in files.items():
            try:
                key = Path(filename).resolve().relative_to(base).as_posix()
            except ValueError:
                continue
            relative[key] = lines
        for key, lines in self.previous.items():
            relative[key] = sorted(set(relative.get(key, [])) | lines)
        payload = {"tool": self.kind, "package": str(self.package_dir), "time": time.time(), "files": relative}
        with self.lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.path)

    def finish(self):
        engine, self.engine = self.engine, None
        if engine is None:
            return
        try:
            engine.stop()
            self.write(self.collected(engine))
        except Exception as error:  # noqa: BLE001 - coverage must never break the run
            if self.log is not None:
                self.log.emit("harness_note", note=f"coverage could not be saved: {error!r}")


def wrap_qthreads():
    """QThreads are not threading.Thread, so they never receive threading.settrace hooks."""
    from PySide6.QtCore import QThread

    hook = getattr(threading, "gettrace", lambda: None)()
    if hook is None:
        return
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("dt") or module is None:
            continue
        for value in list(vars(module).values()):
            if not isinstance(value, type) or not issubclass(value, QThread) or value is QThread:
                continue
            original = value.__dict__.get("run")
            if original is None or getattr(original, "_jev_traced", False):
                continue

            def traced(self, _original=original):
                sys.settrace(threading.gettrace())
                return _original(self)

            traced._jev_traced = True
            setattr(value, "run", traced)
