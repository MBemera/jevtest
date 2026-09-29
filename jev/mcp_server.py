"""Model Context Protocol server (stdio) exposing the Jev QA tools.

Claude Code, Codex and other MCP clients drive the sandboxed DT app through it. The
protocol is newline-delimited JSON-RPC 2.0 on stdin/stdout; logs go to stderr only.
"""

import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import REPO_DIR, load_dotenv, runs_dir
from .findings import render_markdown
from .tools import ToolResult, ToolRunner, spec, specs_for

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = """Jev drives the DT desktop app (PySide6) in a sandbox so you can QA it like a user.
Workflow: snapshot -> act with refs (click, type_text, select_option, select_item, select_tab, press_key,
draw, scroll) -> read the result (it includes what happened and a new snapshot) -> report_issue for each
distinct problem. The app starts automatically with defaults (first-run unlock screen); use app_start to
choose seed=sample (unlocked vault with synthetic records), network=mock, screen size or idle timeout.
Harness-detected exceptions, freezes and crashes are recorded automatically. run_qa_agents launches
OpenRouter-model testers in the background; qa_runs shows their progress and reports. run_campaign runs
everything (DT's tests, the scripted sweep, crawlers, optional AI testers) and rebuilds the improvement
dataset; dataset, issues, set_issue and verify_issues work with the issue registry and DT handoff."""

EXTRA_SPECS = [
    spec("run_qa_agents", "Launch autonomous OpenRouter-model testers in the background (needs "
         "OPENROUTER_API_KEY). Each model x mission x persona gets its own sandboxed app. Returns the output "
         "folder; check progress with qa_runs.",
         {"models": {"type": "string", "description": "Comma-separated OpenRouter model IDs."},
          "missions": {"type": "string", "description": "Comma-separated mission names (default explore)."},
          "personas": {"type": "string", "description": "Comma-separated persona names (default new-trainer)."},
          "max_steps": {"type": "integer"}, "parallel": {"type": "integer"},
          "max_cost": {"type": "number", "description": "Stop each run after this many USD."}},
         ["models"], audiences=("mcp",)),
    spec("qa_runs", "List background QA runs with their status, or show one run's report.",
         {"run": {"type": "string", "description": "Optional run folder name to show its report."}},
         audiences=("mcp",)),
    spec("run_campaign", "Start a full Jev campaign in the background: DT's own tests, the scripted sweep of every "
         "feature, re-verification of known issues, seeded crawlers and (only with a budget and an OpenRouter key) "
         "AI testers, then rebuild the improvement dataset for DT. Follow it with campaign_status.",
         {"budget": {"type": "number", "description": "USD for AI testers (default 0 = none)."},
          "crawls": {"type": "integer", "description": "Crawler runs (default 2)."},
          "crawl_steps": {"type": "integer", "description": "Steps per crawl (default 250)."},
          "models": {"type": "string", "description": "AI tester models (IDs, presets or auto:N)."},
          "missions": {"type": "string", "description": "'gaps' (default), 'all' or a comma list."},
          "dt_tests": {"type": "boolean", "description": "Run DT's own test suites (default true)."},
          "sweep": {"type": "boolean", "description": "Run the scripted sweep (default true)."}},
         audiences=("mcp",)),
    spec("campaign_status", "Progress of the latest (or a named) campaign; its report once finished.",
         {"campaign": {"type": "string", "description": "Optional campaign folder name."}}, audiences=("mcp",)),
    spec("dataset", "Build (action=build) or summarise (action=show, default) the improvement dataset: issues, "
         "coverage gaps, copy and speed problems, ranked for DT.",
         {"action": {"type": "string", "description": "show (default) or build."}}, audiences=("mcp",)),
    spec("issues", "List issues in the registry (status: active (default), all, open, fixed, regressed...), or "
         "show one issue's brief with id.",
         {"status": {"type": "string"}, "id": {"type": "string", "description": "Issue ID such as JEV-0003."}},
         audiences=("mcp",)),
    spec("set_issue", "Update an issue after you triage or reproduce it: status (open, fixed, wontfix, by-design, "
         "known-limitation, harness-artefact), classification, severity, duplicate_of or a note.",
         {"id": {"type": "string"}, "status": {"type": "string"}, "classification": {"type": "string"},
          "severity": {"type": "string"}, "duplicate_of": {"type": "string"}, "note": {"type": "string"}},
         ["id"], audiences=("mcp",)),
    spec("verify_issues", "Replay the scenario behind known issues on the current DT checkout (background). "
         "Passing replays mark issues fixed; failing ones mark fixed issues regressed.",
         {"ids": {"type": "string", "description": "Comma-separated issue IDs (default: every verifiable issue)."}},
         audiences=("mcp",)),
]
BACKGROUND_TOOLS = {"run_campaign", "campaign_status", "dataset", "issues", "set_issue", "verify_issues"}


def log(message):
    sys.stderr.write(f"[jev-mcp] {message}\n")
    sys.stderr.flush()


class McpServer:
    def __init__(self, session_dir=None, app_options=None):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.session_dir = Path(session_dir) if session_dir else runs_dir() / f"mcp-{stamp}"
        self.app_options = dict(app_options or {})
        self.runner = None
        self.client_name = "mcp-client"
        self.write_lock = threading.Lock()
        self.background = []

    # ----- transport ------------------------------------------------------------------------
    def send(self, payload):
        with self.write_lock:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def serve(self):
        for stream in (sys.stdin, sys.stdout):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        log(f"ready; session folder {self.session_dir}")
        try:
            for raw in sys.stdin:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                    continue
                for item in message if isinstance(message, list) else [message]:
                    self.dispatch(item)
        finally:
            self.shutdown()

    def dispatch(self, message):
        method = message.get("method")
        request_id = message.get("id")
        if method is None:
            return  # a response to a request we never send
        try:
            result = self.handle(method, message.get("params") or {})
        except KeyError:
            if request_id is not None:
                self.send({"jsonrpc": "2.0", "id": request_id,
                           "error": {"code": -32601, "message": f"Method not found: {method}"}})
            return
        except Exception as error:  # noqa: BLE001
            log(f"error handling {method}: {error!r}")
            if request_id is not None:
                self.send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(error)}})
            return
        if request_id is not None:
            self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    # ----- methods --------------------------------------------------------------------------
    def handle(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion", SUPPORTED_VERSIONS[0])
            info = params.get("clientInfo") or {}
            self.client_name = info.get("name") or self.client_name
            log(f"client {self.client_name} {info.get('version', '')} protocol {requested}")
            return {"protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "jev", "title": "Jev QA harness for DT", "version": __version__},
                    "instructions": INSTRUCTIONS}
        if method in ("notifications/initialized", "notifications/cancelled", "notifications/roots/list_changed"):
            return None
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": item["name"], "description": item["description"],
                               "inputSchema": item["parameters"]} for item in specs_for("mcp") + EXTRA_SPECS]}
        if method == "tools/call":
            return self.call_tool(params.get("name", ""), params.get("arguments") or {})
        if method in ("resources/list", "resources/templates/list"):
            return {"resources": []} if method == "resources/list" else {"resourceTemplates": []}
        if method == "prompts/list":
            return {"prompts": []}
        if method == "logging/setLevel":
            return {}
        raise KeyError(method)

    def call_tool(self, name, arguments):
        if name == "run_qa_agents":
            result = self.run_qa_agents(arguments)
        elif name == "qa_runs":
            result = self.qa_runs(arguments)
        elif name in BACKGROUND_TOOLS:
            result = getattr(self, "tool_" + name)(arguments)
        else:
            if self.runner is None:
                self.runner = ToolRunner(self.session_dir, app_options=self.app_options, reporter=self.client_name,
                                         context={"model": self.client_name, "run": self.session_dir.name})
            if name == "wait":
                arguments = dict(arguments, seconds=min(float(arguments.get("seconds") or 2), 50))
            result = self.runner.run(name, arguments)
        content = [{"type": "text", "text": result.text}]
        if result.image is not None:
            content.append({"type": "image", "data": base64.b64encode(result.image).decode("ascii"),
                            "mimeType": "image/png"})
        return {"content": content, "isError": bool(result.is_error)}

    # ----- background OpenRouter runs ---------------------------------------------------------
    def run_qa_agents(self, arguments):
        load_dotenv()
        if not os.environ.get("OPENROUTER_API_KEY"):
            return ToolResult("OPENROUTER_API_KEY is not set for the MCP server. Add it to the environment "
                              "or to the jevtest .env file, then try again.", is_error=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = runs_dir() / f"matrix-{stamp}"
        out.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "jev", "matrix", "--models", str(arguments.get("models")),
                   "--missions", str(arguments.get("missions") or "explore"),
                   "--personas", str(arguments.get("personas") or "new-trainer"),
                   "--parallel", str(arguments.get("parallel") or 2), "--out", str(out), "--quiet"]
        if arguments.get("max_steps"):
            command += ["--max-steps", str(arguments["max_steps"])]
        if arguments.get("max_cost"):
            command += ["--max-cost", str(arguments["max_cost"])]
        log_file = open(out / "matrix.log", "w", encoding="utf-8")
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_DIR), os.environ.get("PYTHONPATH")])))
        process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   cwd=str(REPO_DIR), env=environment)
        self.background.append((out, process))
        return ToolResult(f"Started {process.pid}: {' '.join(command[3:])}\nOutput: {out}\n"
                          "Use qa_runs to follow progress; summary.md appears there when all runs finish.")

    def qa_runs(self, arguments):
        root = runs_dir()
        if arguments.get("run"):
            folder = root / arguments["run"]
            for name in ("summary.md", "report.md"):
                if (folder / name).exists():
                    return ToolResult((folder / name).read_text(encoding="utf-8")[:60000])
            runs = sorted(folder.glob("*/report.md"))
            if runs:
                return ToolResult("Finished runs so far:\n" + "\n".join(str(path) for path in runs))
            return ToolResult(f"No report yet in {folder}.")
        lines = []
        for folder in sorted(root.glob("matrix-*"))[-10:]:
            process = next((proc for out, proc in self.background if out == folder), None)
            state = "running" if process is not None and process.poll() is None else (
                "finished" if (folder / "summary.md").exists() else "stopped")
            done = len(list(folder.glob("*/run.json")))
            lines.append(f"{folder.name}: {state}, {done} run(s) complete")
        for folder in sorted(root.glob("2*"))[-10:]:
            if (folder / "run.json").exists():
                data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
                lines.append(f"{folder.name}: {data.get('findings')} finding(s), {data.get('stop_reason')}")
        return ToolResult("\n".join(lines) or "No runs yet.")

    # ----- campaigns, dataset and issues ----------------------------------------------------
    def start_background(self, arguments, out, log_name):
        log_file = open(out / log_name, "w", encoding="utf-8")
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_DIR), os.environ.get("PYTHONPATH")])))
        process = subprocess.Popen([sys.executable, "-m", "jev", *arguments], stdout=log_file, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, cwd=str(REPO_DIR), env=environment)
        self.background.append((out, process))
        return process

    def tool_run_campaign(self, arguments):
        load_dotenv()
        out = runs_dir() / f"campaign-{time.strftime('%Y%m%d-%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        command = ["campaign", "--out", str(out), "--quiet"]
        for key, flag in (("budget", "--budget"), ("crawls", "--crawls"), ("crawl_steps", "--crawl-steps"),
                          ("models", "--models"), ("missions", "--missions")):
            if arguments.get(key) not in (None, ""):
                command += [flag, str(arguments[key])]
        if arguments.get("dt_tests") is False:
            command.append("--no-dt-tests")
        if arguments.get("sweep") is False:
            command.append("--no-sweep")
        process = self.start_background(command, out, "campaign.log")
        return ToolResult(f"Campaign started (process {process.pid}) in {out}. It takes from about 15 minutes "
                          "(no AI testers) upwards. Use campaign_status to follow it.")

    def tool_campaign_status(self, arguments):
        root = runs_dir()
        folders = [root / arguments["campaign"]] if arguments.get("campaign") else sorted(root.glob("campaign-*"))[-1:]
        if not folders or not folders[0].exists():
            return ToolResult("No campaign found.")
        folder = folders[0]
        if (folder / "report.md").exists():
            return ToolResult((folder / "report.md").read_text(encoding="utf-8")[:60000])
        progress = folder / "progress.json"
        if not progress.exists():
            return ToolResult(f"{folder.name}: starting (no progress yet).")
        data = json.loads(progress.read_text(encoding="utf-8"))
        lines = [f"{folder.name}: running stage {data.get('current')!r}"]
        lines += [f"- {stage['name']}: {stage['status']} ({stage['seconds']}s) {str(stage.get('detail') or '')[:200]}"
                  for stage in data.get("stages", [])]
        return ToolResult("\n".join(lines))

    def cli_output(self, argv):
        import contextlib
        import io
        from .cli import build_parser
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            args = build_parser().parse_args(argv)
            code = args.handler(args) or 0
        return ToolResult(buffer.getvalue()[:60000] or "(no output)", is_error=bool(code))

    def tool_dataset(self, arguments):
        action = arguments.get("action") or "show"
        return self.cli_output(["dataset", "build" if action == "build" else "show", *(["--quiet"] if action == "build" else [])])

    def tool_issues(self, arguments):
        if arguments.get("id"):
            return self.cli_output(["issues", "show", str(arguments["id"])])
        return self.cli_output(["issues", "list", "--status", str(arguments.get("status") or "active")])

    def tool_set_issue(self, arguments):
        argv = ["issues", "set", str(arguments["id"])]
        for key, flag in (("status", "--status"), ("classification", "--classification"), ("severity", "--severity"),
                          ("duplicate_of", "--duplicate-of"), ("note", "--note")):
            if arguments.get(key):
                argv += [flag, str(arguments[key])]
        return self.cli_output(argv)

    def tool_verify_issues(self, arguments):
        out = runs_dir() / f"verify-{time.strftime('%Y%m%d-%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        command = ["verify", "--out", str(out), "--quiet"]
        for issue_id in str(arguments.get("ids") or "").split(","):
            if issue_id.strip():
                command += ["--issue", issue_id.strip()]
        process = self.start_background(command, out, "verify.log")
        return ToolResult(f"Verification started (process {process.pid}); results in {out / 'verify-summary.md'} "
                          "when it finishes (about 30 s per issue). Then use issues to see statuses.")

    def shutdown(self):
        if self.runner is not None:
            try:
                findings = self.runner.store.findings
                if findings:
                    report = render_markdown(findings, title="Jev QA session findings",
                                             intro=f"Client: {self.client_name}", base_dir=self.session_dir)
                    (self.session_dir / "report.md").write_text(report, encoding="utf-8")
            finally:
                self.runner.stop()
        log("stopped")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="jev mcp", description="Serve the Jev QA tools over MCP (stdio)")
    parser.add_argument("--session-dir")
    parser.add_argument("--screen")
    parser.add_argument("--network", choices=["block", "mock", "allow"])
    parser.add_argument("--seed", choices=["none", "empty", "sample"])
    parser.add_argument("--ffmpeg", choices=["auto", "none"])
    parser.add_argument("--idle-timeout-ms", type=int)
    args = parser.parse_args(argv)
    load_dotenv()
    options = {key: value for key, value in {"screen": args.screen, "network": args.network, "seed": args.seed,
                                             "ffmpeg": args.ffmpeg, "idle_timeout_ms": args.idle_timeout_ms}.items()
               if value is not None}
    McpServer(args.session_dir, options).serve()
    return 0
