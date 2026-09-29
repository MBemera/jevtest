"""Start, drive, restart and stop one sandboxed DT process."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from .client import HostClient, HostConnectionLost, HostError
from .config import REPO_DIR, dt_path, host_python, real_ffmpeg_tools
from .fixtures import describe_fixtures, install_fixtures

SEED_PASSPHRASE = "jev-synthetic-passphrase-2026"
SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.IGNORECASE)
KEEP_ENV = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
            "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE", "QT_SCALE_FACTOR", "QT_FONT_DPI", "FONTCONFIG_PATH", "FONTCONFIG_FILE",
            "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"}
DEFAULTS = {"screen": "1366x768", "network": "block", "allow_hosts": [], "ffmpeg": "auto", "seed": "none",
            "idle_timeout_ms": None, "visible": False, "stall_seconds": 1.5, "settle": 0.35, "wait_busy": 10.0,
            "isolate_home": True, "unlock": True}


class AppCrashed(Exception):
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


class AppExited(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class AppStartError(Exception):
    pass


def parse_screen(text):
    match = re.fullmatch(r"\s*(\d{3,5})\s*[xX×]\s*(\d{3,5})\s*(?:@\s*([0-9.]+))?\s*", str(text))
    if not match:
        raise ValueError(f"screen must look like 1366x768 or 2560x1440@2, not {text!r}")
    return int(match.group(1)), int(match.group(2)), float(match.group(3) or 1)


class AppSession:
    def __init__(self, session_dir, owned=True, **options):
        self.session_dir = Path(session_dir).resolve()
        self.sandbox = self.session_dir / "sandbox"
        self.options = dict(DEFAULTS)
        self.options.update({key: value for key, value in options.items() if value is not None})
        self.owned = owned
        self.process = None
        self.client = None
        self.ready = None
        self.starts = 0
        self.last_seq = 0

    # ----- preparation ------------------------------------------------------------------
    def prepare(self):
        for folder in ("vaults", "exports", "backups", "fixtures", "home", "tmp"):
            (self.sandbox / folder).mkdir(parents=True, exist_ok=True)
        install_fixtures(self.sandbox / "fixtures")
        width, height, ratio = parse_screen(self.options["screen"])
        screen = {"screens": [{"name": "jev-screen", "x": 0, "y": 0, "width": width, "height": height,
                               "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": ratio}]}
        (self.sandbox / ".jev-screen.json").write_text(json.dumps(screen), encoding="utf-8")
        config = {
            "sandbox": str(self.sandbox),
            "network": self.options["network"],
            "allow_hosts": list(self.options.get("allow_hosts") or []),
            "idle_timeout_ms": self.options.get("idle_timeout_ms"),
            "stall_seconds": self.options["stall_seconds"],
            "settle": self.options["settle"],
            "wait_busy": self.options["wait_busy"],
            "seed": self.options["seed"],
            "seed_folder": str(self.sandbox / "vaults" / "seeded-vault"),
            "exit_on_stdin_eof": self.owned,
        }
        (self.session_dir / "host-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    def environment(self):
        env = {key: value for key, value in os.environ.items()
               if key in KEEP_ENV or not SECRET_ENV.search(key)}
        for key in ("DT_FFMPEG", "DT_FFPROBE", "DT_LOCAL_MODEL_COMMAND", "DT_LOCAL_MODEL_SHA256",
                    "PYTHONPATH", "QT_QPA_PLATFORM", "OPENROUTER_API_KEY"):
            env.pop(key, None)
        paths = [str(REPO_DIR)]
        checkout = dt_path()
        if checkout is not None:
            paths.append(str(checkout / "src"))
        env["PYTHONPATH"] = os.pathsep.join(paths)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONFAULTHANDLER"] = "1"
        if not self.options["visible"]:
            env["QT_QPA_PLATFORM"] = "offscreen:configfile=.jev-screen.json"
        if self.options["isolate_home"]:
            home = self.sandbox / "home"
            env.update({"HOME": str(home), "USERPROFILE": str(home),
                        "XDG_DATA_HOME": str(home / ".local" / "share"), "XDG_CONFIG_HOME": str(home / ".config"),
                        "XDG_CACHE_HOME": str(home / ".cache"),
                        "LOCALAPPDATA": str(home / "AppData" / "Local"), "APPDATA": str(home / "AppData" / "Roaming"),
                        "TMPDIR": str(self.sandbox / "tmp"), "TEMP": str(self.sandbox / "tmp"),
                        "TMP": str(self.sandbox / "tmp")})
            if os.name != "nt" and "XDG_RUNTIME_DIR" not in env:
                runtime = self.sandbox / "tmp" / "runtime"
                runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
                env["XDG_RUNTIME_DIR"] = str(runtime)
        if self.options["ffmpeg"] == "auto":
            tools = real_ffmpeg_tools()
            if "ffmpeg" in tools and "ffprobe" in tools:
                env["DT_FFMPEG"], env["DT_FFPROBE"] = tools["ffmpeg"], tools["ffprobe"]
        elif self.options["ffmpeg"] == "none":
            entries = env.get("PATH", "").split(os.pathsep)
            names = ("ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe")
            env["PATH"] = os.pathsep.join(entry for entry in entries
                                          if not any((Path(entry) / name).exists() for name in names))
        return env

    # ----- lifecycle --------------------------------------------------------------------
    def start(self, timeout=60.0):
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.prepare()
        for stale in ("ready.json", "exit.json"):
            (self.session_dir / stale).unlink(missing_ok=True)
        log = open(self.session_dir / "host.log", "ab")
        log.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
        log.flush()
        command = [host_python(), "-m", "jev.host.main", "--session-dir", str(self.session_dir)]
        kwargs = {"cwd": str(self.sandbox), "env": self.environment(), "stdout": log, "stderr": subprocess.STDOUT,
                  "stdin": subprocess.PIPE if self.owned else subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(command, **kwargs)
        log.close()
        deadline = time.monotonic() + timeout
        ready_file = self.session_dir / "ready.json"
        while not ready_file.exists():
            if self.process.poll() is not None:
                raise AppStartError("The app process exited during start-up.\n" + self.log_tail(40))
            if time.monotonic() > deadline:
                self.kill()
                raise AppStartError("The app did not become ready in time.\n" + self.log_tail(40))
            time.sleep(0.1)
        self.ready = json.loads(ready_file.read_text(encoding="utf-8"))
        self.client = HostClient(self.ready["port"], self.ready["token"])
        self.client.connect()
        self.starts += 1
        self.last_seq = 0
        self.write_state()
        if self.options["seed"] != "none" and self.options.get("unlock", True):
            self.unlock_seeded_vault()
        return self.ready

    def write_state(self):
        state = {"session_dir": str(self.session_dir), "pid": self.process.pid if self.process else None,
                 "port": self.ready["port"] if self.ready else None,
                 "token": self.ready["token"] if self.ready else None, "options": self.options}
        (self.session_dir / "session.json").write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    @classmethod
    def attach(cls, session_dir):
        """Reconnect to a detached session started by an earlier CLI command."""
        session_dir = Path(session_dir)
        state = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        session = cls(session_dir, owned=False, **state.get("options", {}))
        session.ready = {"port": state["port"], "token": state["token"], "pid": state["pid"]}
        session.client = HostClient(state["port"], state["token"])
        session.attached_pid = state["pid"]
        return session

    def alive(self):
        if self.process is not None:
            return self.process.poll() is None
        pid = getattr(self, "attached_pid", None)
        return bool(pid) and pid_alive(pid)

    def stop(self, timeout=8.0):
        if self.client is not None:
            try:
                self.client.call("quit", {"force": True}, timeout=10)
            except (HostError, HostConnectionLost, OSError, ValueError):
                pass
            self.client.close()
        deadline = time.monotonic() + timeout
        while self.alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        if self.alive():
            self.kill()
        self.release_pipes()

    def release_pipes(self):
        if self.process is not None and self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def kill(self):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                pass
        elif getattr(self, "attached_pid", None) and pid_alive(self.attached_pid):
            try:
                os.kill(self.attached_pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
            except OSError:
                pass

    def restart(self, fresh=False, **overrides):
        self.stop()
        self.options.update({key: value for key, value in overrides.items() if value is not None})
        if fresh:
            import shutil
            shutil.rmtree(self.sandbox, ignore_errors=True)
        return self.start()

    # ----- calls ------------------------------------------------------------------------
    def call(self, command, args=None, timeout=120.0):
        if self.client is None:
            raise AppExited("The app is not running. Start or restart it.", None)
        try:
            return self.client.call(command, args or {}, timeout=timeout)
        except HostConnectionLost:
            time.sleep(0.5)
            raise self.termination_error() from None
        except HostError as error:
            if "has exited" in str(error):
                time.sleep(0.6)
                raise self.termination_error() from None
            raise

    def termination_error(self):
        exit_file = self.session_dir / "exit.json"
        code = self.process.poll() if self.process is not None else None
        if exit_file.exists():
            info = json.loads(exit_file.read_text(encoding="utf-8"))
            self.client = None
            return AppExited(f"The app closed normally (exit code {info.get('code')}). Use restart_app to open it again.",
                             info.get("code"))
        if code is None and self.alive():
            return AppCrashed("Lost the connection to the app, but its process is still running.",
                              {"log_tail": self.log_tail(30)})
        self.client = None
        details = {"exit_code": code, "signal": signal_name(code), "fault_log": self.fault_tail(60),
                   "log_tail": self.log_tail(60)}
        return AppCrashed(f"THE APP CRASHED (exit code {code}{', ' + details['signal'] if details['signal'] else ''}).",
                          details)

    def act(self, action_name, **args):
        args["action"] = action_name
        args.setdefault("events_since", self.last_seq)
        result = self.call("act", args)
        self.last_seq = max(self.last_seq, result.get("seq", 0))
        return result

    def unlock_seeded_vault(self):
        folder = self.sandbox / "vaults" / "seeded-vault"
        snapshot = self.call("snapshot")
        if "Open local records" not in snapshot["text"]:
            return
        self.act("type_text", target="Choose a device folder", text=str(folder), snapshot=False)
        self.act("type_text", target="Vault passphrase", text=SEED_PASSPHRASE, snapshot=False)
        result = self.act("click", target="Open", role="button", snapshot=False, wait_busy=2)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = self.call("state")
            if state.get("screen") == "main window":
                return
            time.sleep(0.2)
        raise AppStartError("Could not unlock the seeded vault automatically: " + json.dumps(result.get("events", []))[:800])

    # ----- information ----------------------------------------------------------------
    def info(self):
        seed = {}
        seed_file = self.session_dir / "seed.json"
        if seed_file.exists():
            seed = json.loads(seed_file.read_text(encoding="utf-8") or "{}")
        tools = real_ffmpeg_tools() if self.options["ffmpeg"] == "auto" else {}
        return {
            "sandbox": str(self.sandbox),
            "vault_folders": str(self.sandbox / "vaults") + "  (create new vaults here, e.g. vaults/my-vault)",
            "exports": str(self.sandbox / "exports"),
            "backups": str(self.sandbox / "backups"),
            "fixtures": describe_fixtures(self.sandbox / "fixtures"),
            "fixtures_folder": str(self.sandbox / "fixtures"),
            "seeded_vault": seed or None,
            "suggested_new_passphrase": "correct-horse-battery-staple-42",
            "network": self.options["network"] + (" (requests are recorded and blocked)" if self.options["network"] == "block"
                                                  else " (known provider requests get canned answers)" if self.options["network"] == "mock"
                                                  else " (real requests are sent!)"),
            "ffmpeg": ("available to DT" if tools.get("ffmpeg") and tools.get("ffprobe") else "not available to DT")
                      if self.options["ffmpeg"] != "none" else "hidden from DT on purpose",
            "screen": self.options["screen"],
            "idle_lock_after_ms": self.options.get("idle_timeout_ms") or 300000,
        }

    def log_tail(self, lines=40):
        return tail(self.session_dir / "host.log", lines)

    def fault_tail(self, lines=60):
        return tail(self.session_dir / "fault.log", lines)


def tail(path, lines):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def signal_name(code):
    if code is None or code >= 0:
        return ""
    try:
        return signal.Signals(-code).name
    except ValueError:
        return f"signal {-code}"


def pid_alive(pid):
    if os.name == "nt":
        import ctypes
        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not process:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(process)
        return code.value == 259
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    try:
        finished, _ = os.waitpid(int(pid), os.WNOHANG)
        return finished == 0
    except ChildProcessError:
        return True
