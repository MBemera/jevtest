"""Deterministic scenarios: scripted journeys through DT with expectations, no model needed.

A scenario is JSON:

    {"name": "sign-and-export", "title": "...", "features": ["sign", "export"],
     "app": {"seed": "sample", "network": "mock"},
     "issue": {...}                                   # only for regression scenarios
     "steps": [
        {"do": "select_item", "item": "Riley Ready"},
        {"do": "click", "target": "Sign assessment", "expect": {"dialog": "Sign assessment"}},
        {"do": "expect", "contains": "Riley Ready | signed"}
     ]}

Each step names a tool (the same tools the MCP server and the OpenRouter agent use) plus its
arguments. Targets are visible labels, never refs, so scenarios survive layout changes.
`expect` checks what happened: dialog, message, status, contains, lacks, modal, error, value,
network and no_exception (on by default). Scenarios power the full-system sweep of DT and the
regression checks that tell DT whether an issue is fixed.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import data_file, dt_version
from .tools import ToolRunner

CONTROL_KEYS = {"do", "expect", "optional", "soft", "note", "id", "repeat_until", "on_fail"}
READ_ONLY_TOOLS = {"snapshot", "screenshot", "events", "audit", "read_text", "list_items", "network_log",
                   "sandbox_info", "findings", "note", "report_issue"}


@dataclass
class StepOutcome:
    index: int
    do: str
    ok: bool
    problems: list = field(default_factory=list)
    note: str = ""
    optional: bool = False
    tool_ok: bool = True
    text: str = ""


@dataclass
class ScenarioResult:
    name: str
    title: str
    passed: bool
    run_dir: str
    duration: float
    steps: list
    findings: list
    dt: dict
    issue: dict = None

    def failures(self):
        return [step for step in self.steps if not step["ok"] and not step["optional"]]


def scenario_dirs():
    return [data_file("scenarios")]


def find_scenarios(group=None):
    """Built-in scenarios: data/scenarios/<group>/*.json."""
    found = []
    for base in scenario_dirs():
        folder = base / group if group else base
        found.extend(sorted(folder.rglob("*.json")) if folder.exists() else [])
    return found


def load_scenario(reference):
    path = Path(str(reference)).expanduser()
    if not path.exists():
        wanted = str(reference).replace("\\", "/").removesuffix(".json")
        matches = [candidate for candidate in find_scenarios()
                   if wanted in (candidate.stem, f"{candidate.parent.name}/{candidate.stem}")]
        if not matches:
            raise FileNotFoundError(f"No scenario {reference!r} (built-in: {', '.join(p.stem for p in find_scenarios())})")
        path = matches[0]
    scenario = json.loads(path.read_text(encoding="utf-8"))
    scenario.setdefault("name", path.stem)
    scenario.setdefault("title", scenario["name"])
    scenario["_path"] = str(path)
    return scenario


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def contains(haystack, needle):
    return str(needle).casefold() in str(haystack or "").casefold()


def check_expectations(expect, result, runner, snapshot_text):
    """Return a list of human-readable problems; empty means every expectation held."""
    problems = []
    data = result.data or {}
    events = data.get("events") or []
    opened = [event for event in events if event.get("kind") == "dialog" and event.get("phase") == "opened"]
    messages = [" ".join(filter(None, [str(event.get("message") or ""), str(event.get("informative") or "")]))
                for event in opened] + [str(event.get("message", "")) for event in events if event.get("kind") == "status"]
    state = runner.last_state or {}
    if "error" in expect:
        wanted = expect["error"]
        if not result.is_error:
            problems.append(f"expected the step to fail{'' if wanted is True else f' with {wanted!r}'}, but it succeeded")
        elif wanted is not True and not contains(result.text, wanted):
            problems.append(f"expected an error mentioning {wanted!r}, got: {result.text.splitlines()[0][:200]}")
    elif result.is_error:
        problems.append(f"step failed: {result.text.splitlines()[0][:300] if result.text else 'error'}")
    for wanted in as_list(expect.get("dialog")):
        titles = [event.get("title", "") for event in opened] + [((state.get("modal") or {}).get("title") or "")]
        if not any(contains(title, wanted) for title in titles):
            problems.append(f"expected a dialog titled like {wanted!r}; saw {[t for t in titles if t] or 'none'}")
    for wanted in as_list(expect.get("message")):
        if not any(contains(text, wanted) for text in messages) and not contains(snapshot_text, wanted):
            seen = [text for text in messages if text.strip()][-3:]
            problems.append(f"expected a message containing {wanted!r}; saw {seen or 'no message'}")
    for unwanted in as_list(expect.get("no_message")):
        if any(contains(text, unwanted) for text in messages):
            problems.append(f"did not expect a message containing {unwanted!r}")
    for wanted in as_list(expect.get("status")):
        statuses = [str(event.get("message", "")) for event in events if event.get("kind") == "status"]
        if not any(contains(text, wanted) for text in statuses + [state.get("status", "")]):
            seen = statuses[-3:] or [state.get("status", "")]
            problems.append(f"expected a status bar message containing {wanted!r}; the status bar said {seen}")
    for wanted in as_list(expect.get("contains")):
        if not contains(snapshot_text, wanted):
            problems.append(f"expected the screen to contain {wanted!r}")
    for unwanted in as_list(expect.get("lacks")):
        if contains(snapshot_text, unwanted):
            problems.append(f"expected the screen not to contain {unwanted!r}")
    if "modal" in expect:
        modal = (state.get("modal") or {}).get("title")
        if expect["modal"] in (False, None, "none"):
            if modal:
                problems.append(f"expected no open dialog, but {modal!r} is open")
        elif not modal or not contains(modal, expect["modal"]):
            problems.append(f"expected the open dialog to be {expect['modal']!r}, found {modal!r}")
    if "network" in expect:
        requests = [event for event in events if event.get("kind") == "network"]
        if expect["network"] in ("none", False):
            if requests:
                problems.append(f"expected no network request, saw {[r.get('url') for r in requests]}")
        elif not any(contains(event.get("url"), expect["network"]) for event in requests):
            problems.append(f"expected a network request to {expect['network']!r}")
    if expect.get("no_exception", True):
        for event in events:
            if event.get("kind") == "exception":
                problems.append(f"unhandled {event.get('type')}: {event.get('message')} at {event.get('location')}")
    for check in as_list(expect.get("value")):
        read = runner.run("read_text", {key: check[key] for key in ("target", "role", "index", "tab_hint") if key in check})
        if read.is_error:
            problems.append(f"could not read {check.get('target')!r}: {read.text[:200]}")
            continue
        text = read.text.split(":\n", 1)[-1]
        if "equals" in check and text.strip() != str(check["equals"]).strip():
            problems.append(f"{check.get('target')!r} is {text.strip()[:120]!r}, expected {check['equals']!r}")
        if "contains" in check and not contains(text, check["contains"]):
            problems.append(f"{check.get('target')!r} does not contain {check['contains']!r}")
        if "lacks" in check and contains(text, check["lacks"]):
            problems.append(f"{check.get('target')!r} still contains {check['lacks']!r}")
    return problems


def run_scenario(scenario, out_dir, *, app_overrides=None, quiet=False, runner=None, keep_app=False):
    """Run one scenario in its own sandboxed app (or a supplied runner) and record everything."""
    if not isinstance(scenario, dict):
        scenario = load_scenario(scenario)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    app = dict(scenario.get("app") or {})
    app.update({key: value for key, value in (app_overrides or {}).items() if value is not None})
    owns_runner = runner is None
    if owns_runner:
        runner = ToolRunner(out_dir, app_options=app, reporter=f"scenario:{scenario['name']}",
                            context={"model": "scenario", "mission": scenario["name"], "run": out_dir.name,
                                     "persona": "deterministic"})
    started = time.time()
    outcomes = []
    stop = False
    for index, step in enumerate(scenario.get("steps", []), 1):
        if stop:
            outcomes.append(asdict(StepOutcome(index, step.get("do", ""), False, ["not run: an earlier step failed"],
                                               step.get("note", ""), bool(step.get("optional")))))
            continue
        tool = step.get("do", "")
        expect = dict(step.get("expect") or {})
        arguments = {key: value for key, value in step.items() if key not in CONTROL_KEYS}
        if tool == "expect":
            result = runner.run("snapshot", {})
            expect = {key: value for key, value in step.items() if key not in CONTROL_KEYS}
            snapshot_text = (result.data or {}).get("snapshot") or result.text
        else:
            if tool in runner.ACTIONS and "snapshot" not in arguments:
                arguments["snapshot"] = True
            result = runner.run(tool, arguments)
            snapshot_text = (result.data or {}).get("snapshot") or ""
            if not snapshot_text and tool not in READ_ONLY_TOOLS and not result.is_error:
                snapshot_text = (runner.run("snapshot", {}).data or {}).get("snapshot", "")
        problems = check_expectations(expect, result, runner, snapshot_text)
        outcome = StepOutcome(index, tool, not problems, problems, step.get("note", ""), bool(step.get("optional")),
                              not result.is_error, result.text[:600])
        if problems and not step.get("optional"):
            record_failure(runner, scenario, index, step, expect, problems)
        outcomes.append(asdict(outcome))
        if not quiet:
            mark = "ok " if outcome.ok else ("opt" if outcome.optional else "FAIL")
            print(f"  [{mark}] {index:>2} {tool} {json.dumps({k: v for k, v in arguments.items() if k != 'snapshot'}, ensure_ascii=False)[:90]}"
                  + (f" -> {problems[0]}" if problems else ""), flush=True)
        if problems and not step.get("optional") and not step.get("soft") and not scenario.get("continue_on_error"):
            stop = True
    findings = [finding["id"] for finding in runner.store.findings]
    if owns_runner and not keep_app:
        runner.stop()
    result = ScenarioResult(scenario["name"], scenario.get("title", ""), all(o["ok"] or o["optional"] for o in outcomes),
                            str(out_dir), round(time.time() - started, 1), outcomes, findings, dict(dt_version()),
                            scenario.get("issue"))
    payload = asdict(result)
    payload["features"] = scenario.get("features", [])
    payload["scenario_file"] = scenario.get("_path", "")
    (out_dir / "scenario-result.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return result


def describe_step(step):
    """A plain-English line for a scenario step, used in reproduction steps."""
    do = step.get("do", "")
    target = step.get("target") or step.get("item") or ""
    if do == "click":
        return f"Click \"{target}\"" + (f" in the \"{step['window']}\" window" if step.get("window") else "")
    if do == "type_text":
        text = str(step.get("text", ""))
        return f"Type \"{text[:80]}\" into \"{target}\"" + (f" and press {step['submit'].title()}" if step.get("submit") else "")
    if do == "select_option":
        return f"Choose \"{step.get('option')}\" in \"{target}\""
    if do == "select_item":
        where = f" in \"{step['target']}\"" if step.get("target") else ""
        return f"Select the row \"{step.get('item')}\"{where}" + (f" ({step['action']})" if step.get("action") else "")
    if do == "select_tab":
        return f"Open the \"{step.get('tab')}\" tab"
    if do == "set_checked":
        return f"{'Tick' if step.get('checked', True) else 'Untick'} \"{target}\""
    if do == "press_key":
        return f"Press {step.get('keys')}"
    if do == "draw":
        return f"Draw on \"{target}\""
    if do == "scroll":
        return f"Turn the mouse wheel {step.get('direction', 'down')} {step.get('amount', 3)} notch(es) over \"{target}\""
    if do == "wait":
        return f"Wait up to {step.get('seconds', 2)} s" + (" for the job to finish" if step.get("until") == "idle" else "")
    if do == "set_network_mock":
        return f"(harness) make the mocked {step.get('service', 'all')} service answer '{step.get('scenario')}'"
    if do == "resize_window":
        return f"Resize the window to {step.get('width')}x{step.get('height')}"
    if do == "restart_app":
        return "Restart DT"
    if do == "expect":
        return "Check the screen"
    return f"{do} {json.dumps({k: v for k, v in step.items() if k not in CONTROL_KEYS}, ensure_ascii=False)}"


def describe_expectation(expect):
    parts = []
    for key, value in expect.items():
        if key == "no_exception":
            continue
        parts.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return "; ".join(parts) or "the step completes without errors"


def record_failure(runner, scenario, index, step, expect, problems):
    """A failed expectation in a scripted journey is a finding in its own right."""
    on_fail = step.get("on_fail") or {}
    app = scenario.get("app") or {}
    setup = f"Start DT with {', '.join(f'{k}={v}' for k, v in app.items()) or 'defaults'} (Jev seed/network options)."
    lines = [setup] + [describe_step(earlier) for earlier in scenario.get("steps", [])[:index]
                       if earlier.get("do") not in READ_ONLY_TOOLS]
    title = on_fail.get("title") or (f"{scenario.get('title', scenario['name'])}: step {index} "
                                     f"({describe_step(step)}) did not behave as expected")
    finding = {"source": f"scenario:{scenario['name']}", "title": title[:200],
               "severity": on_fail.get("severity", "medium"), "category": on_fail.get("category", "functional"),
               "steps": lines, "expected": on_fail.get("expected") or describe_expectation(expect),
               "actual": on_fail.get("actual_prefix", "") + "; ".join(problems), "confidence": "confirmed",
               "signature": f"scenario@{scenario['name']}#{on_fail.get('key') or index}",
               "screen": runner.describe_screen(), "step": runner.step}
    issue_id = on_fail.get("issue") or (scenario.get("issue") or {}).get("id")
    if issue_id:
        finding["issue_id"] = issue_id
    finding["evidence"] = runner.capture_evidence(finding)
    runner.store.add(finding)


def read_findings(run_dir):
    path = Path(run_dir) / "findings.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_scenario(run_dir, until_step=None, name=None):
    """Turn a recorded run (steps.jsonl) into a replayable scenario using labels instead of refs."""
    run_dir = Path(run_dir)
    steps = [json.loads(line) for line in (run_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    app = {}
    session_file = run_dir / "app" / "session.json"
    if session_file.exists():
        options = json.loads(session_file.read_text(encoding="utf-8")).get("options", {})
        app = {key: options[key] for key in ("seed", "network", "screen", "idle_timeout_ms", "ffmpeg") if options.get(key)}
    replay = []
    for record in steps:
        if until_step is not None and record["step"] > until_step:
            break
        tool = record["tool"]
        if not record.get("ok") or tool in READ_ONLY_TOOLS or tool in ("finish", "app_start", "app_stop"):
            continue
        arguments = dict(record.get("args") or {})
        target = record.get("target") or {}
        if str(arguments.get("target", "")).strip().lstrip("[").startswith("w") and target:
            arguments.pop("target", None)
            if target.get("name"):
                arguments["target"] = target["name"]
            arguments["role"] = target.get("role")
            if target.get("tab"):
                arguments["tab_hint"] = target["tab"]
        if tool == "select_item" and "target" not in arguments:
            arguments.pop("role", None)
        step = {"do": tool, **{key: value for key, value in arguments.items() if value not in (None, "")}}
        replay.append(step)
    return {"name": name or f"replay-{run_dir.name}", "title": f"Replay of {run_dir.name}"
            + (f" up to step {until_step}" if until_step else ""), "app": app, "steps": replay,
            "recorded_from": str(run_dir)}


def run_suite(scenarios, out_dir, *, app_overrides=None, quiet=False):
    """Run several scenarios, each in a fresh app, and summarise them."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for reference in scenarios:
        scenario = load_scenario(reference)
        if not quiet:
            print(f"== {scenario['name']}: {scenario.get('title', '')}", flush=True)
        results.append(run_scenario(scenario, out_dir / scenario["name"], app_overrides=app_overrides, quiet=quiet))
    write_suite_summary(out_dir, results)
    return results


def write_suite_summary(out_dir, results):
    lines = ["# Jev scenario suite", "", f"DT commit: `{(dt_version().get('commit') or 'unknown')[:12]}`", "",
             "| Scenario | Result | Failed step | Findings | Time |", "|---|---|---|---|---|"]
    for result in results:
        failure = result.failures()
        first = f"{failure[0]['index']}: {failure[0]['problems'][0]}" if failure else ""
        lines.append(f"| {result.name} | {'pass' if result.passed else 'FAIL'} | {first.replace('|', '/')[:160]} | "
                     f"{len(result.findings)} | {result.duration}s |")
    passed = sum(1 for result in results if result.passed)
    lines += ["", f"**{passed}/{len(results)} scenarios passed.**"]
    Path(out_dir, "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(out_dir, "summary.json").write_text(json.dumps([asdict(result) for result in results], indent=2, default=str),
                                             encoding="utf-8")
