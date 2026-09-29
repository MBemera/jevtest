"""Locations and settings shared by the CLI, the MCP server and the agent runner."""

import os
import shutil
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent
DATA_DIR = PACKAGE_DIR / "data"


def load_dotenv(paths=None):
    """Read KEY=VALUE lines from .env files without overriding the real environment."""
    candidates = paths or [Path.cwd() / ".env", REPO_DIR / ".env"]
    for path in candidates:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def runs_dir():
    configured = os.environ.get("JEV_RUNS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if (REPO_DIR / "pyproject.toml").exists():
        return REPO_DIR / "runs"
    return Path.home() / ".jev" / "runs"


def state_dir():
    configured = os.environ.get("JEV_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".jev"
    base.mkdir(parents=True, exist_ok=True)
    return base


def dt_path():
    """The DT checkout: $JEV_DT_PATH, else a sibling DT folder next to this repository."""
    configured = os.environ.get("JEV_DT_PATH")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates += [REPO_DIR.parent / "DT", REPO_DIR.parent / "dt", Path.cwd() / "DT", Path.cwd()]
    for candidate in candidates:
        if (candidate / "src" / "dt" / "ui.py").exists():
            return candidate.resolve()
    return None


def host_python():
    """Interpreter for the app process. It needs PySide6 and DT's dependencies installed."""
    configured = os.environ.get("JEV_PYTHON")
    if configured:
        return configured
    checkout = dt_path()
    if checkout is not None:
        for relative in ((".venv", "Scripts", "python.exe"), (".venv", "bin", "python")):
            candidate = checkout.joinpath(*relative)
            if candidate.exists():
                return str(candidate)
    return sys.executable


def real_ffmpeg_tools():
    """ffmpeg/ffprobe as DT itself would find them for the real user (before sandboxing)."""
    tools = {}
    for name, variable in (("ffmpeg", "DT_FFMPEG"), ("ffprobe", "DT_FFPROBE")):
        configured = os.environ.get(variable, "").strip()
        if configured and Path(configured).exists():
            tools[name] = configured
            continue
        managed = dt_tools_directory() / (f"{name}.exe" if os.name == "nt" else name)
        if managed.exists():
            tools[name] = str(managed)
            continue
        found = shutil.which(name)
        if found:
            tools[name] = found
    return tools


def dt_tools_directory():
    import platform
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "DT" / "tools"


def data_file(*parts):
    return DATA_DIR.joinpath(*parts)
