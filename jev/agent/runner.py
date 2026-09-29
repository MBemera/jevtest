"""One autonomous QA session: an OpenRouter model drives DT through the Jev tools."""

import base64
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import runs_dir
from ..findings import load_run_findings, render_markdown
from ..tools import ToolRunner, openai_tools
from . import prompts
from .openrouter import OpenRouter, OpenRouterError, model_capabilities

APP_OPTION_KEYS = ("seed", "network", "screen", "idle_timeout_ms", "ffmpeg")
_models_cache = {}
_models_lock = threading.Lock()


@dataclass
class RunConfig:
    model: str
    mission: str = "explore"
    persona: str = "new-trainer"
    max_steps: int = 0
    max_cost: float = 0.0
    max_minutes: float = 45.0
    temperature: float = 0.4
    max_tokens: int = 4096
    vision: str = "auto"
    reasoning: str = ""
    keep_recent: int = 8
    out_dir: str = ""
    label: str = ""
    app: dict = field(default_factory=dict)
    quiet: bool = False


def slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")[:60] or "run"


def cached_models(client):
    with _models_lock:
        if "models" not in _models_cache:
            try:
                _models_cache["models"] = client.models()
            except OpenRouterError:
                _models_cache["models"] = []
        return _models_cache["models"]


class QARun:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or OpenRouter()
        persona_meta, self.persona_text = prompts.load_document("personas", config.persona)
        mission_meta, self.mission_text = prompts.load_document("missions", config.mission)
        self.persona_name = persona_meta.get("name", "persona")
        self.mission_name = mission_meta.get("name", "mission")
        self.persona_title = persona_meta.get("title", self.persona_name)
        self.mission_title = mission_meta.get("title", self.mission_name)
        self.app_options = {key: mission_meta[key] for key in APP_OPTION_KEYS if key in mission_meta}
        self.app_options.update({key: value for key, value in (config.app or {}).items() if value not in (None, "")})
        self.app_options.setdefault("screen", "1366x768")
        self.app_options.setdefault("network", "block")
        self.max_steps = int(config.max_steps or mission_meta.get("max_steps") or 60)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = config.label or f"{stamp}-{slug(self.mission_name)}-{slug(self.persona_name)}-{slug(config.model)}"
        self.run_dir = Path(config.out_dir) / name if config.out_dir else runs_dir() / name
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.label = config.label or f"{slug(config.model)}/{self.mission_name}"
        self.transcript = self.run_dir / "transcript.jsonl"
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "requests": 0}
        self.vision = False
        self.stop_reason = ""
        self.summary = {}

    # ----- logging ------------------------------------------------------------------------
    def log(self, message):
        if not self.config.quiet:
            print(f"[{self.label}] {message}", flush=True)

    def record(self, kind, **data):
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": kind, "time": round(time.time(), 3), **data}, default=str) + "\n")

    # ----- capability checks ----------------------------------------------------------------
    def check_model(self):
        capabilities = model_capabilities(cached_models(self.client), self.config.model)
        if capabilities is None:
            self.log("model not found in the OpenRouter catalogue (or catalogue unavailable); trying anyway")
        elif not capabilities["tools"]:
            raise OpenRouterError(f"{self.config.model} does not support tool calling on OpenRouter; "
                                  "choose another model (jev models --tools).")
        if self.config.vision == "on":
            self.vision = True
        elif self.config.vision == "auto":
            self.vision = bool(capabilities and capabilities["vision"])
        return capabilities

    # ----- main loop --------------------------------------------------------------------------
    def execute(self):
        started = time.time()
        capabilities = self.check_model()
        context = {"model": self.config.model, "persona": self.persona_name, "mission": self.mission_name,
                   "run": self.run_dir.name}
        runner = ToolRunner(self.run_dir, app_options=self.app_options, reporter=self.config.model, context=context)
        self.record("start", config=asdict(self.config), app=self.app_options, max_steps=self.max_steps,
                    capabilities=capabilities, vision=self.vision)
        self.log(f"starting: persona={self.persona_name} mission={self.mission_name} steps={self.max_steps} "
                 f"vision={self.vision} app={self.app_options}")
        try:
            runner.ensure_app()
            first = runner.run("snapshot", {})
            info = runner.run("sandbox_info", {})
            system = prompts.system_prompt(self.persona_text, self.mission_text, prompts.primer(),
                                           screen=self.app_options.get("screen"),
                                           network=self.app_options.get("network"), max_steps=self.max_steps,
                                           persona_title=self.persona_title, mission_title=self.mission_title)
            kickoff = "Begin testing now.\n\nSandbox:\n" + info.text + "\n\nCurrent screen:\n" + first.text
            if self.vision:
                shot = runner.run("screenshot", {})
                if shot.image:
                    kickoff = [{"type": "text", "text": kickoff}, image_part(shot.image)]
            self.loop(runner, system, kickoff, started)
        except OpenRouterError as error:
            self.stop_reason = f"OpenRouter error: {error}"
            self.log(self.stop_reason)
        except KeyboardInterrupt:
            self.stop_reason = "interrupted"
            raise
        finally:
            runner.stop()
            self.finish(runner, started)
        return self.summary

    def loop(self, runner, system, kickoff, started):
        tools = openai_tools("agent")
        history = []
        steps = 0
        idle_turns = 0
        while True:
            if steps >= self.max_steps:
                self.stop_reason = f"step budget used ({self.max_steps})"
                return
            if self.config.max_cost and self.usage["cost"] >= self.config.max_cost:
                self.stop_reason = f"cost limit reached (${self.usage['cost']:.4f})"
                return
            if time.time() - started > self.config.max_minutes * 60:
                self.stop_reason = f"time limit reached ({self.config.max_minutes} min)"
                return
            messages = self.build_messages(system, kickoff, history, runner, steps)
            payload = {"model": self.config.model, "messages": messages, "tools": tools, "tool_choice": "auto",
                       "temperature": self.config.temperature, "max_tokens": self.config.max_tokens,
                       "usage": {"include": True}, "provider": {"require_parameters": True}}
            if self.config.reasoning:
                payload["reasoning"] = {"effort": self.config.reasoning}
            request_started = time.time()
            response = self.client.chat(payload)
            latency = round(time.time() - request_started, 2)
            self.account(response)
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = normalise_tool_calls(message.get("tool_calls"), steps)
            self.record("model", latency=latency, finish_reason=choice.get("finish_reason"),
                        content=message.get("content"), tool_calls=tool_calls, usage=response.get("usage"))
            assistant = {"role": "assistant", "content": message.get("content") or None}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            if message.get("reasoning_details"):
                assistant["reasoning_details"] = message["reasoning_details"]
            history.append(assistant)
            if not tool_calls:
                idle_turns += 1
                if message.get("content"):
                    self.log(f"model says: {one_line(message['content'], 160)}")
                if idle_turns >= 3:
                    self.stop_reason = "the model stopped calling tools"
                    return
                history.append({"role": "user", "content": "Continue testing by calling a tool. When you have "
                                                           "finished the mission, call finish."})
                continue
            idle_turns = 0
            images = []
            for call in tool_calls:
                name = call["function"]["name"]
                arguments, problem = parse_arguments(call["function"].get("arguments"))
                steps += 1
                if problem:
                    result_text, image, is_error, data = problem, None, True, {}
                else:
                    result = runner.run(name, arguments)
                    result_text, image, is_error, data = result.text, result.image, result.is_error, result.data
                remaining = self.max_steps - steps
                if remaining <= 5:
                    result_text += (f"\n\n[Budget: {remaining} tool call(s) left. Report anything outstanding "
                                    "and call finish.]")
                history.append({"role": "tool", "tool_call_id": call["id"], "content": result_text})
                if image is not None:
                    images.append(image)
                self.record("tool", step=steps, name=name, arguments=arguments, is_error=is_error,
                            result=result_text[:6000])
                self.log(f"{steps:>3}/{self.max_steps} {name} {one_line(json.dumps(arguments), 90)} -> "
                         f"{one_line(result_text, 110)}")
                for finding in runner.new_findings:
                    self.log(f"      finding {finding['id']} [{finding['severity']}] {finding['title']}")
                if data.get("finished"):
                    self.stop_reason = "the tester called finish"
                    self.summary["tester_summary"] = runner.finished
                    return
                if data.get("finding"):
                    self.log(f"      reported {data['finding']['id']} [{data['finding']['severity']}] "
                             f"{data['finding']['title']}")
            if images and self.vision:
                history.append({"role": "user", "content": [{"type": "text", "text": "Screenshot:"}, image_part(images[-1])]})

    def build_messages(self, system, kickoff, history, runner, steps):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": kickoff}]
        compacted = compact(history, self.config.keep_recent)
        memory = self.memory(runner, steps)
        if compacted and compacted[-1]["role"] == "tool":
            compacted[-1] = dict(compacted[-1], content=compacted[-1]["content"] + "\n\n" + memory)
        elif memory:
            compacted.append({"role": "user", "content": memory})
        return messages + compacted

    def memory(self, runner, steps):
        parts = [f"[Session memory] Tool calls used: {steps} of {self.max_steps}."]
        if runner.notes:
            parts.append("Your notes: " + " | ".join(runner.notes[-12:]))
        if runner.store.findings:
            parts.append("Issues already recorded (do not report again): " + "; ".join(runner.store.titles()[-25:]))
        if runner.screens:
            parts.append("Screens visited: " + ", ".join(sorted(runner.screens))[:600])
        return "\n".join(parts)

    def account(self, response):
        usage = response.get("usage") or {}
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        self.usage["cost"] += float(usage.get("cost") or 0)

    # ----- output ------------------------------------------------------------------------------
    def finish(self, runner, started):
        self.stop_reason = self.stop_reason or "stopped"
        duration = round(time.time() - started, 1)
        findings = load_run_findings(self.run_dir / "findings.jsonl") if (self.run_dir / "findings.jsonl").exists() else []
        self.summary.update({
            "run_dir": str(self.run_dir), "model": self.config.model, "persona": self.persona_name,
            "mission": self.mission_name, "stop_reason": self.stop_reason, "duration_seconds": duration,
            "tool_calls": runner.step, "usage": self.usage, "findings": len(findings),
            "screens": sorted(runner.screens), "app": self.app_options,
        })
        self.summary.setdefault("tester_summary", runner.finished)
        (self.run_dir / "run.json").write_text(json.dumps(self.summary, indent=2, default=str), encoding="utf-8")
        tester = runner.finished or {}
        intro = "\n".join(filter(None, [
            f"- **Model:** `{self.config.model}`",
            f"- **Persona:** {self.persona_title}",
            f"- **Mission:** {self.mission_title}",
            f"- **App:** {', '.join(f'{k}={v}' for k, v in self.app_options.items())}",
            f"- **Stopped because:** {self.stop_reason}",
            f"- **Tool calls:** {runner.step}; **duration:** {duration}s; **tokens:** "
            f"{self.usage['prompt_tokens']} in / {self.usage['completion_tokens']} out; **cost:** ${self.usage['cost']:.4f}",
            f"- **Screens visited:** {', '.join(sorted(runner.screens)) or 'none'}",
            f"\n**Tester's summary:** {tester.get('summary')}" if tester.get("summary") else "",
            f"\n**Not tested:** {tester.get('not_tested')}" if tester.get("not_tested") else "",
        ]))
        report = render_markdown(findings, title=f"Jev QA run: {self.mission_title}", intro=intro, base_dir=self.run_dir)
        (self.run_dir / "report.md").write_text(report, encoding="utf-8")
        self.log(f"done: {self.stop_reason}; {len(findings)} finding(s); cost ${self.usage['cost']:.4f}; "
                 f"report {self.run_dir / 'report.md'}")


def image_part(data):
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode("ascii")}}


def normalise_tool_calls(calls, steps):
    normalised = []
    for index, call in enumerate(calls or []):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        normalised.append({"id": call.get("id") or f"call_{steps}_{index}", "type": "function",
                           "function": {"name": function.get("name", ""), "arguments": arguments}})
    return normalised


def parse_arguments(raw):
    if raw in (None, ""):
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        return {}, f"Your tool arguments were not valid JSON ({error}). Send a JSON object."
    if not isinstance(value, dict):
        return {}, "Tool arguments must be a JSON object."
    return value, None


def compact(history, keep_recent):
    """Shorten old tool results and drop old images so long sessions fit the context window."""
    turn_starts = [index for index, message in enumerate(history) if message["role"] == "assistant"]
    if len(turn_starts) <= keep_recent:
        return [dict(message) for message in history]
    cutoff = turn_starts[-keep_recent]
    compacted = []
    for index, message in enumerate(history):
        message = dict(message)
        if index < cutoff:
            if message["role"] == "tool":
                message["content"] = shorten(message["content"])
            elif message["role"] == "user" and isinstance(message.get("content"), list):
                message["content"] = "[older screenshot removed]"
            elif message["role"] == "assistant" and isinstance(message.get("content"), str) and len(message["content"]) > 600:
                message["content"] = message["content"][:600] + " …"
        compacted.append(message)
    return compacted


def shorten(text, limit=500):
    text = str(text)
    cut = text.split("Snapshot after the action:")[0].split("\n\n[Session memory]")[0]
    if len(cut) > limit:
        cut = cut[:limit] + " …"
    if len(cut) < len(text):
        cut += "\n[older result shortened]"
    return cut


def one_line(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
