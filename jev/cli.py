"""Command line interface: `jev <command>` (or `python -m jev <command>`)."""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import dt_path, host_python, load_dotenv, real_ffmpeg_tools, runs_dir, state_dir


# ----- detached CLI sessions -----------------------------------------------------------------
def pointer_file(name):
    folder = state_dir() / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{name}.json"


def session_root(name, fresh=False):
    pointer = pointer_file(name)
    if pointer.exists() and not fresh:
        root = Path(json.loads(pointer.read_text(encoding="utf-8"))["dir"])
        if root.exists():
            return root
    root = runs_dir() / f"cli-{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    root.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"dir": str(root)}), encoding="utf-8")
    return root


def app_options(args):
    options = {}
    for key in ("screen", "network", "seed", "ffmpeg", "idle_timeout_ms"):
        value = getattr(args, key, None)
        if value is not None:
            options[key] = value
    if getattr(args, "visible", False):
        options["visible"] = True
    if getattr(args, "allow_host", None):
        options["allow_hosts"] = args.allow_host
    return options


def start_detached(name, options, fresh=False):
    from .session import AppSession
    root = session_root(name, fresh=fresh)
    session = AppSession(root / "app", owned=False, **options)
    session.start()
    return root, session


def attached_runner(name, auto_start=True):
    """A ToolRunner bound to the named detached session, starting one if needed."""
    from .session import AppSession
    from .tools import ToolRunner
    root = session_root(name)
    app_dir = root / "app"
    session = None
    if (app_dir / "session.json").exists():
        candidate = AppSession.attach(app_dir)
        if candidate.alive():
            session = candidate
    if session is None:
        if not auto_start:
            raise SystemExit(f"No running Jev session {name!r}. Start one with: jev start")
        print(f"(starting a new app session {name!r} with default options)", file=sys.stderr)
        root, session = start_detached(name, {})
    runner = ToolRunner(root, reporter=os.environ.get("JEV_REPORTER", "cli"),
                        context={"model": os.environ.get("JEV_REPORTER", "cli"), "run": root.name})
    runner.session = session
    state = root / "cli-state.json"
    if state.exists():
        session.last_seq = json.loads(state.read_text(encoding="utf-8")).get("last_seq", 0)
    return runner, state


def save_state(runner, state):
    if runner.session is not None:
        state.write_text(json.dumps({"last_seq": runner.session.last_seq}), encoding="utf-8")


def run_tool(args, name, arguments, image_out=None):
    runner, state = attached_runner(args.name)
    result = runner.run(name, {key: value for key, value in arguments.items() if value is not None})
    save_state(runner, state)
    print(result.text)
    if result.image is not None and image_out:
        Path(image_out).write_bytes(result.image)
        print(f"Saved {image_out}")
    return 1 if result.is_error else 0


# ----- commands ----------------------------------------------------------------------------
def cmd_start(args):
    options = app_options(args)
    pointer = pointer_file(args.name)
    if pointer.exists() and not args.fresh:
        from .session import AppSession
        root = Path(json.loads(pointer.read_text(encoding="utf-8"))["dir"])
        if (root / "app" / "session.json").exists():
            existing = AppSession.attach(root / "app")
            if existing.alive():
                existing.stop()
    root, session = start_detached(args.name, options, fresh=args.fresh)
    session.last_seq = session.call("events", {"since": 0, "limit": 1})["seq"]
    (root / "cli-state.json").write_text(json.dumps({"last_seq": session.last_seq}), encoding="utf-8")
    print(f"Jev session {args.name!r} running (pid {session.ready['pid']}).")
    print(f"Folder: {root}")
    print(json.dumps(session.info(), indent=1, ensure_ascii=False))
    print()
    print(session.call("snapshot")["text"])
    return 0


def cmd_stop(args):
    from .session import AppSession
    root = session_root(args.name)
    if not (root / "app" / "session.json").exists():
        print("No session to stop.")
        return 0
    session = AppSession.attach(root / "app")
    session.stop()
    findings_file = root / "findings.jsonl"
    if findings_file.exists():
        from .findings import load_run_findings, render_markdown
        findings = load_run_findings(findings_file)
        report = render_markdown(findings, title=f"Jev QA session {args.name}", base_dir=root)
        (root / "report.md").write_text(report, encoding="utf-8")
        print(f"Report: {root / 'report.md'} ({len(findings)} finding(s))")
    print(f"Stopped session {args.name!r}. Findings, evidence and logs stay in {root}")
    return 0


def cmd_restart(args):
    runner, state = attached_runner(args.name)
    result = runner.run("restart_app", {"fresh": args.fresh, **app_options(args)})
    runner.session.write_state()
    save_state(runner, state)
    print(result.text)
    return 1 if result.is_error else 0


def cmd_status(args):
    from .session import AppSession
    root = session_root(args.name)
    app_dir = root / "app"
    if not (app_dir / "session.json").exists():
        print(f"No session {args.name!r} yet.")
        return 1
    session = AppSession.attach(app_dir)
    alive = session.alive()
    print(f"Session {args.name!r}: {'running' if alive else 'not running'}; folder {root}")
    if alive:
        print(json.dumps(session.call("state"), indent=1))
    return 0 if alive else 1


def cmd_doctor(args):
    load_dotenv()
    ok = True
    print(f"Jev {__version__} on Python {platform.python_version()} ({platform.system()} {platform.machine()})")
    checkout = dt_path()
    print(f"DT checkout: {checkout or 'NOT FOUND - set JEV_DT_PATH to the DT repository'}")
    ok &= checkout is not None
    python = host_python()
    print(f"App interpreter: {python}")
    from .session import AppSession
    probe = AppSession(state_dir() / "doctor", owned=True)
    environment = probe.environment()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    code = ("import PySide6, dt, dt.ui; from PySide6.QtWidgets import QApplication; "
            "app = QApplication([]); print('PySide6', PySide6.__version__, 'DT', dt.__file__)")
    result = subprocess.run([python, "-c", code], capture_output=True, text=True, env=environment, timeout=120)
    if result.returncode == 0:
        print("App imports and Qt offscreen start: OK - " + result.stdout.strip().splitlines()[-1])
    else:
        ok = False
        print("App imports / Qt start: FAILED")
        print("  " + "\n  ".join(result.stderr.strip().splitlines()[-8:]))
        print("  Install DT into that interpreter: python -m pip install -e \"<DT>[desktop]\"; on Linux also "
              "install libegl1 libopengl0 libxkbcommon0 libpulse0 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0")
    tools = real_ffmpeg_tools()
    print(f"FFmpeg for video fixtures and DT media checks: "
          f"{tools.get('ffmpeg', 'not found')} / {tools.get('ffprobe', 'not found')}")
    key = os.environ.get("OPENROUTER_API_KEY", "")
    print(f"OPENROUTER_API_KEY: {'set (' + key[:6] + '…, ' + str(len(key)) + ' characters)' if key else 'not set (needed only for jev run/matrix)'}")
    print(f"Runs folder: {runs_dir()}")
    if args.online:
        from .agent.openrouter import OpenRouter, OpenRouterError
        client = OpenRouter()
        try:
            models = client.models()
            tool_models = [m for m in models if "tools" in (m.get("supported_parameters") or [])]
            print(f"OpenRouter reachable: {len(models)} models, {len(tool_models)} with tool calling")
            if key:
                info = client.key_info()
                print(f"Key: label {info.get('label')!r}, usage ${info.get('usage')}, limit {info.get('limit')}")
        except OpenRouterError as error:
            ok = False
            print(f"OpenRouter check failed: {error}")
    print("\nAll checks passed." if ok else "\nSome checks failed; see above.")
    return 0 if ok else 1


def cmd_models(args):
    load_dotenv()
    from .agent.openrouter import OpenRouter
    models = OpenRouter().models()
    rows = []
    for model in models:
        parameters = set(model.get("supported_parameters") or [])
        modalities = set((model.get("architecture") or {}).get("input_modalities") or [])
        if args.tools and "tools" not in parameters:
            continue
        if args.vision and "image" not in modalities:
            continue
        if args.search and args.search.lower() not in (model["id"] + " " + model.get("name", "")).lower():
            continue
        pricing = model.get("pricing") or {}
        rows.append((model["id"], model.get("context_length") or 0, "tools" in parameters, "image" in modalities,
                     float(pricing.get("prompt") or 0) * 1e6, float(pricing.get("completion") or 0) * 1e6))
    rows.sort(key=lambda row: row[0])
    print(f"{'model':55} {'context':>9} tools vision  $/M in  $/M out")
    for row in rows:
        print(f"{row[0]:55} {row[1]:>9} {'yes' if row[2] else 'no':>5} {'yes' if row[3] else 'no':>6} "
              f"{row[4]:>7.2f} {row[5]:>8.2f}")
    print(f"\n{len(rows)} model(s)")
    return 0


def run_config(args, model):
    from .agent.runner import RunConfig
    return RunConfig(model=model, mission=args.mission if hasattr(args, "mission") else "explore",
                     persona=args.persona if hasattr(args, "persona") else "new-trainer",
                     max_steps=args.max_steps or 0, max_cost=args.max_cost or 0.0, max_minutes=args.max_minutes,
                     temperature=args.temperature, max_tokens=args.max_tokens, vision=args.vision,
                     reasoning=args.reasoning or "", out_dir=args.out or "", app=app_options(args), quiet=args.quiet)


def default_models():
    configured = os.environ.get("JEV_MODELS") or os.environ.get("JEV_MODEL")
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    presets = json.loads((Path(__file__).parent / "data" / "model_presets.json").read_text(encoding="utf-8"))
    return presets["presets"]["default"]


def resolve_models(text):
    presets = json.loads((Path(__file__).parent / "data" / "model_presets.json").read_text(encoding="utf-8"))["presets"]
    models = []
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        models.extend(presets.get(item.removeprefix("preset:"), [item]) if item.startswith("preset:") or item in presets else [item])
    return models or default_models()


def cmd_run(args):
    load_dotenv()
    from .agent.runner import QARun
    models = resolve_models(args.model)
    if len(models) > 1:
        print("Several models given; use `jev matrix` to run them in parallel. Running the first one.", file=sys.stderr)
    summary = QARun(run_config(args, models[0])).execute()
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_matrix(args):
    load_dotenv()
    from .agent.matrix import run_matrix
    models = resolve_models(args.models)
    missions = [item.strip() for item in args.missions.split(",") if item.strip()]
    personas = [item.strip() for item in args.personas.split(",") if item.strip()]
    base = run_config(argparse.Namespace(**{**vars(args), "mission": missions[0], "persona": personas[0], "out": ""}),
                      models[0])
    root, results = run_matrix(base, models, missions, personas, parallel=args.parallel, out_dir=args.out)
    print(f"\nSummary: {root / 'summary.md'}")
    failures = [result for result in results if result.get("error")]
    for failure in failures:
        print(f"FAILED {failure.get('model')} {failure.get('mission')}: {failure.get('error')}", file=sys.stderr)
    return 1 if failures and len(failures) == len(results) else 0


def cmd_report(args):
    from .findings import load_run_findings, render_markdown
    findings = []
    for path in args.paths:
        findings.extend(load_run_findings(path))
    base = Path(args.out).parent if args.out else Path.cwd()
    report = render_markdown(findings, title=args.title, base_dir=base)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Wrote {args.out} ({len(findings)} finding(s))")
    else:
        print(report)
    return 0


def cmd_list(kind):
    def command(args):
        from .agent.prompts import load_document, available
        for name in available(kind):
            meta, body = load_document(kind, name)
            print(f"{name:26} {meta.get('title', '')}")
            if kind == "missions":
                options = {key: meta[key] for key in ("seed", "network", "screen", "idle_timeout_ms", "max_steps") if key in meta}
                print(f"{'':26} {options}")
        return 0
    return command


def cmd_mcp(args):
    from .mcp_server import main as mcp_main
    return mcp_main(args.rest)


# ----- argument parsing ----------------------------------------------------------------------
def add_app_options(parser):
    parser.add_argument("--screen", help="offscreen screen size, e.g. 1366x768 (default), 1024x768, 2560x1440@2")
    parser.add_argument("--network", choices=["block", "mock", "allow"], help="how DT's internet features behave")
    parser.add_argument("--allow-host", action="append", help="with --network allow: only these hosts")
    parser.add_argument("--seed", choices=["none", "empty", "sample"],
                        help="none = first-run unlock screen; empty/sample = unlocked vault (sample has 3 records)")
    parser.add_argument("--ffmpeg", choices=["auto", "none"], help="auto = give DT the machine's FFmpeg; none = hide it")
    parser.add_argument("--idle-timeout-ms", type=int, dest="idle_timeout_ms", help="override DT's 5 minute idle lock")


def add_agent_options(parser):
    parser.add_argument("--max-steps", type=int, help="tool calls per run (default: mission's, else 60)")
    parser.add_argument("--max-cost", type=float, help="stop a run after this many USD")
    parser.add_argument("--max-minutes", type=float, default=45.0)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--vision", choices=["auto", "on", "off"], default="auto",
                        help="send screenshots to the model (auto = when OpenRouter says it accepts images)")
    parser.add_argument("--reasoning", choices=["low", "medium", "high"], help="reasoning effort for thinking models")
    parser.add_argument("--quiet", action="store_true")
    add_app_options(parser)


def build_parser():
    parser = argparse.ArgumentParser(prog="jev", description="AI-driven QA harness for the DT desktop app")
    parser.add_argument("--version", action="version", version=f"jev {__version__}")
    parser.add_argument("--name", default=os.environ.get("JEV_SESSION", "default"),
                        help="CLI session name (default: default)")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, handler, help_text):
        item = sub.add_parser(name, help=help_text, description=help_text)
        item.set_defaults(handler=handler)
        return item

    item = command("doctor", cmd_doctor, "check that DT, Qt, FFmpeg and OpenRouter are ready")
    item.add_argument("--online", action="store_true", help="also contact OpenRouter")
    item = command("start", cmd_start, "start the sandboxed app in the background")
    add_app_options(item)
    item.add_argument("--visible", action="store_true", help="show real windows instead of offscreen rendering")
    item.add_argument("--fresh", action="store_true", help="new session folder and sandbox")
    command("stop", cmd_stop, "stop the background app")
    item = command("restart", cmd_restart, "restart the app, keeping the sandbox unless --fresh")
    add_app_options(item)
    item.add_argument("--fresh", action="store_true")
    command("status", cmd_status, "show whether the app is running and what is on screen")

    def tool(name, tool_name, help_text, arguments, image=False):
        item = command(name, None, help_text)
        for flags, options in arguments:
            item.add_argument(*flags, **options)

        def handler(args):
            values = {}
            for flags, options in arguments:
                destination = options.get("dest") or flags[0].lstrip("-").replace("-", "_")
                values[destination] = getattr(args, destination)
            return run_tool(args, tool_name, translate(tool_name, values), getattr(args, "out", None) if image else None)

        item.set_defaults(handler=handler)
        return item

    tool("snapshot", "snapshot", "print the current screen", [(["--full"], {"action": "store_true"}),
                                                                (["--max-items"], {"type": int, "dest": "max_items"})])
    tool("screenshot", "screenshot", "save a PNG of the screen", [(["--out"], {"default": "jev-screenshot.png"}),
                                                                  (["--marks"], {"action": "store_true"}),
                                                                  (["--target"], {})], image=True)
    tool("click", "click", "click a control", [(["target"], {}), (["--role"], {}), (["--double"], {"action": "store_true"}),
                                               (["--index"], {"type": int})])
    tool("type", "type_text", "type into a field", [(["target"], {}), (["text"], {}),
                                                    (["--append"], {"action": "store_true"}),
                                                    (["--submit"], {"choices": ["enter", "tab"]}),
                                                    (["--paste"], {"action": "store_true"}), (["--repeat"], {"type": int}),
                                                    (["--role"], {})])
    tool("select", "select_option", "choose a dropdown option", [(["target"], {}), (["option"], {})])
    tool("check", "set_checked", "tick (or --off untick) a checkbox", [(["target"], {}), (["--off"], {"action": "store_true"})])
    tool("item", "select_item", "click a list/tree row", [(["target"], {}), (["item"], {}),
                                                          (["--action"], {"default": "select"})])
    tool("tab", "select_tab", "select a tab", [(["tab"], {}), (["--target"], {})])
    tool("key", "press_key", "press keys, e.g. Tab or Ctrl+A", [(["keys"], {}), (["--target"], {})])
    tool("draw", "draw", "draw on a drawing area (signature pad)", [(["target"], {}), (["--strokes"], {})])
    tool("scroll", "scroll", "scroll an area", [(["target"], {}), (["--direction"], {"default": "down"}),
                                                (["--amount"], {"type": int, "default": 3}), (["--to"], {})])
    tool("resize", "resize_window", "resize the main window", [(["width"], {"type": int}), (["height"], {"type": int})])
    tool("close", "close_window", "close the active dialog or a window", [(["target"], {"nargs": "?"})])
    tool("wait", "wait", "wait for the app", [(["seconds"], {"type": float, "nargs": "?", "default": 2.0}),
                                              (["--until"], {"choices": ["idle", "dialog"]})])
    tool("read", "read_text", "read a control's full text", [(["target"], {})])
    tool("items", "list_items", "page through a list", [(["target"], {}), (["--offset"], {"type": int}),
                                                        (["--limit"], {"type": int})])
    tool("events", "events", "show harness events", [(["--since"], {"type": int})])
    tool("audit", "audit", "layout and accessibility heuristics", [(["kind"], {"nargs": "?", "default": "all"})])
    tool("network", "network_log", "show attempted network requests", [(["--count"], {"type": int})])
    tool("mock", "set_network_mock", "set mock service behaviour", [(["scenario"], {}), (["--service"], {}),
                                                                    (["--delay"], {"type": float})])
    tool("info", "sandbox_info", "sandbox folders, fixtures and passphrases", [])
    tool("findings", "findings", "list findings recorded in this session", [])
    tool("report-issue", "report_issue", "record an issue found while driving the app by hand",
         [(["--title"], {"required": True}), (["--severity"], {"required": True}),
          (["--category"], {"required": True}), (["--steps"], {"required": True}), (["--expected"], {"required": True}),
          (["--actual"], {"required": True}), (["--confidence"], {"default": "confirmed"}), (["--target"], {})])

    item = command("run", cmd_run, "run one autonomous OpenRouter tester")
    item.add_argument("--model", default=None, help="OpenRouter model ID or preset (default $JEV_MODEL or the preset)")
    item.add_argument("--mission", default="explore")
    item.add_argument("--persona", default="new-trainer")
    item.add_argument("--out", help="parent folder for the run (default runs/)")
    add_agent_options(item)
    item = command("matrix", cmd_matrix, "run several models x missions x personas in parallel")
    item.add_argument("--models", default=None, help="comma-separated model IDs or preset names (see model_presets.json)")
    item.add_argument("--missions", default="explore")
    item.add_argument("--personas", default="new-trainer")
    item.add_argument("--parallel", type=int, default=2)
    item.add_argument("--out", help="output folder (default runs/matrix-<time>)")
    add_agent_options(item)
    item = command("models", cmd_models, "list OpenRouter models")
    item.add_argument("--tools", action="store_true", help="only models with tool calling")
    item.add_argument("--vision", action="store_true", help="only models that accept images")
    item.add_argument("--search")
    item = command("report", cmd_report, "merge findings from run folders into one report")
    item.add_argument("paths", nargs="+")
    item.add_argument("--out")
    item.add_argument("--title", default="Jev QA report")
    command("missions", cmd_list("missions"), "list built-in missions")
    command("personas", cmd_list("personas"), "list built-in personas")
    item = command("mcp", cmd_mcp, "serve the tools over MCP stdio (for Claude Code, Codex, ...); "
                                   "options: --session-dir, --screen, --network, --seed, --ffmpeg, --idle-timeout-ms")
    item.add_argument("rest", nargs=argparse.REMAINDER)
    return parser


def translate(tool_name, values):
    """Map CLI option names to tool argument names."""
    if tool_name == "type_text":
        values["clear"] = not values.pop("append", False)
    if tool_name == "set_checked":
        values["checked"] = not values.pop("off", False)
    if tool_name == "screenshot":
        values.pop("out", None)
    return values


def main(argv=None):
    load_dotenv()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["mcp"]:
        from .mcp_server import main as mcp_main
        return mcp_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
