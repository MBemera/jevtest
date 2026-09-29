"""Entry point of the app process: ``python -m jev.host.main --session-dir DIR``.

It installs the monitors and sandbox guards, then runs DT's own ``dt.ui.main()`` unchanged.
The only substitution is a QApplication subclass that attaches the control server as soon
as the application object exists.
"""

import argparse
import faulthandler
import json
import os
import sys
import threading
import time
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run DT under the Jev QA harness")
    parser.add_argument("--session-dir", required=True)
    args = parser.parse_args(argv)
    session_dir = Path(args.session_dir).resolve()
    config = json.loads((session_dir / "host-config.json").read_text(encoding="utf-8"))
    sandbox = Path(config["sandbox"]).resolve()
    os.chdir(sandbox)
    fault_log = open(session_dir / "fault.log", "w", encoding="utf-8")
    faulthandler.enable(file=fault_log, all_threads=True)
    if config.get("exit_on_stdin_eof"):
        # The controller holds our stdin open; if it dies, do not linger as an orphan.
        threading.Thread(target=exit_when_stdin_closes, name="jev-parent-watch", daemon=True).start()

    from .monitor import EventLog, StallWatchdog, install_exception_hooks
    log = EventLog(session_dir / "events.jsonl")
    install_exception_hooks(log)

    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    from PySide6.QtWidgets import QApplication

    from .observers import WindowObserver, install_heartbeat, install_qt_message_handler
    install_qt_message_handler(log)

    import dt.ui
    from .guards import FileDialogPatch, NetworkGuard, install_dt_path_guards
    from .coverage_probe import CoverageProbe
    from .seed import seed_vault, write_catalogue_fixtures
    from .server import Host

    write_catalogue_fixtures(sandbox / "fixtures")
    seeded = {}
    if config.get("seed", "none") != "none":
        seeded = seed_vault(Path(config["seed_folder"]), config["seed"])
    (session_dir / "seed.json").write_text(json.dumps(seeded, indent=2), encoding="utf-8")

    observer = WindowObserver(log)
    network = NetworkGuard(log, session_dir, config.get("network", "block"), config.get("allow_hosts", []), observer)
    network.install()
    FileDialogPatch(sandbox, log).install()
    install_dt_path_guards(sandbox, log)
    idle = config.get("idle_timeout_ms")
    if idle:
        base = dt.ui.MainWindow

        class MainWindow(base):
            def __init__(self, vault, *, idle_timeout_ms=None):
                super().__init__(vault, idle_timeout_ms=int(idle))

        MainWindow.__qualname__ = base.__qualname__
        dt.ui.MainWindow = MainWindow

    host = Host(str(session_dir), sandbox, log, network, observer, config)
    watchdog = StallWatchdog(log, float(config.get("stall_seconds", 1.5)))

    class HarnessApplication(QApplication):
        def __init__(self, argv):
            super().__init__(argv)
            self.installEventFilter(observer)
            if config.get("display") == "window" and not config.get("allow_input"):
                # DT is on the real screen: a stray click or keystroke from the laptop's user must not
                # change the run. Jev's own input bypasses the guard.
                from .watch import install_input_guard
                self._jev_guard = install_input_guard(host.scheduler, log)
            self._jev_heartbeat = install_heartbeat(watchdog)
            watchdog.start()
            host.attach()
            log.emit("app", phase="started", pid=os.getpid(), display=config.get("display", "headless"))

    dt.ui.QApplication = HarnessApplication
    # Measure only what testers make DT do: seeding and imports ran before this point.
    probe = CoverageProbe(session_dir, config.get("coverage", "auto"), log)
    probe.start()
    code = 1
    try:
        code = dt.ui.main()
    finally:
        host.exited = code
        watchdog.stop()
        probe.finish()
        log.emit("app", phase="exited", code=code)
        (session_dir / "exit.json").write_text(json.dumps({"code": code, "time": time.time()}), encoding="utf-8")
        time.sleep(0.4)  # let the control thread answer anyone still waiting
    return code


def exit_when_stdin_closes():
    try:
        while sys.stdin.buffer.read(1024):
            pass
    except (OSError, ValueError, AttributeError):
        pass
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
