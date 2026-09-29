"""One command that exercises all of DT and refreshes the improvement dataset.

Stages, each recorded in ``progress.json`` and the campaign ``report.md``:

1. environment  - DT commit, interpreters, FFmpeg, whether an OpenRouter key is present
2. dt-tests     - DT's own unit and desktop suites under coverage (read-only; DT's git status
                  is compared before and after), optionally its mutation check
3. sweep        - every scripted feature journey, with soft checks on known issues
4. verify       - replays the scenario behind every known issue: fixed, still open, regressed
5. crawl        - seeded crawlers on different starting states (sample records, first run, empty)
6. minimise     - shrinks the replays of new harness-detected issues to the few steps that matter
7. gaps         - writes missions aimed at code and screens nobody reached (for AI testers)
8. ai-testers   - OpenRouter testers on core and gap missions, only with --budget and a key
9. dataset      - the final dataset, backlog and DT handoff
"""

import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__
from .config import dt_path, dt_version, host_python, real_ffmpeg_tools, runs_dir
from .registry import dataset_dir

CORE_MISSIONS = ["first-run", "prepare-assessment", "assess-marking", "evidence-media", "finalise-sign-export"]
CRAWL_PROFILES = ["sample", "none", "empty"]


@dataclass
class CampaignOptions:
    out: str = None
    budget: float = 0.0
    models: str = "auto:3"
    missions: str = "gaps"
    personas: str = "new-trainer,edge-case-hunter"
    max_steps: int = 45
    parallel: int = 2
    crawls: int = 2
    crawl_steps: int = 250
    dt_tests: bool = True
    dt_mutation: bool = False
    sweep: bool = True
    verify: bool = True
    gap_missions: int = 3
    minimise: int = 3
    minimise_minutes: float = 4.0
    dataset: str = None
    app: dict = field(default_factory=dict)
    quiet: bool = False
    random_seed: int = None


class Campaign:
    def __init__(self, options):
        self.options = options
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.root = Path(options.out) if options.out else runs_dir() / f"campaign-{stamp}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.dataset = Path(options.dataset) if options.dataset else dataset_dir()
        self.seed = options.random_seed if options.random_seed is not None else int(time.strftime("%j%H%M"))
        self.stages = []
        self.facts = {}
        self.started = time.time()
        # Scenarios and crawlers choose their own starting records; the campaign may still change the
        # screen size, network mode, FFmpeg availability or idle timeout for all of them.
        self.app = {key: value for key, value in (options.app or {}).items() if key != "seed" and value is not None}

    # ----- plumbing -------------------------------------------------------------------
    def log(self, message):
        # Stage progress always prints; --quiet only silences the step-by-step output of each stage.
        print(f"[campaign {time.strftime('%H:%M:%S')}] {message}", flush=True)

    def progress(self, current=None):
        payload = {"root": str(self.root), "started": self.started, "current": current, "stages": self.stages,
                   "facts": self.facts, "options": asdict(self.options), "pid": os.getpid()}
        (self.root / "progress.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def stage(self, name, function, skip_reason=None):
        if skip_reason:
            self.stages.append({"name": name, "status": "skipped", "seconds": 0, "detail": skip_reason})
            self.log(f"{name}: skipped ({skip_reason})")
            self.progress()
            return None
        self.log(f"{name}: starting")
        self.progress(name)
        started = time.time()
        try:
            detail = function()
            status = "ok"
        except Exception as error:  # noqa: BLE001 - a failed stage must not stop the campaign
            detail = f"{type(error).__name__}: {error}\n{traceback.format_exc(limit=5)}"
            status = "failed"
        entry = {"name": name, "status": status, "seconds": round(time.time() - started, 1), "detail": detail}
        self.stages.append(entry)
        self.log(f"{name}: {status} in {entry['seconds']}s" + (f" - {summarise(detail)}" if detail else ""))
        self.progress()
        return detail if status == "ok" else None

    # ----- stages -----------------------------------------------------------------------
    def environment(self):
        dt = dict(dt_version())
        tools = real_ffmpeg_tools()
        facts = {"jev": __version__, "python": platform.python_version(), "platform": platform.platform(),
                 "dt": dt, "app_python": host_python(), "ffmpeg": bool(tools.get("ffmpeg")),
                 "openrouter_key": bool(os.environ.get("OPENROUTER_API_KEY"))}
        if dt_path() is None:
            raise RuntimeError("DT checkout not found; set JEV_DT_PATH")
        self.facts["environment"] = facts
        return f"DT {str(dt.get('commit'))[:12]}{' (dirty)' if dt.get('dirty') else ''}, FFmpeg " \
               f"{'yes' if facts['ffmpeg'] else 'no'}, OpenRouter key {'yes' if facts['openrouter_key'] else 'no'}"

    def dt_tests(self):
        results = run_dt_tests(self.root / "dt-tests", mutation=self.options.dt_mutation, log=self.log)
        self.facts["dt_tests"] = results
        settle_test_issues(self.dataset / "registry.json", results)
        parts = [f"{name}: {info.get('summary')}" for name, info in results["suites"].items()]
        if results.get("dt_tree_changed"):
            parts.append("WARNING: DT's working tree changed during its tests")
        return "; ".join(parts)

    def sweep(self):
        from .scenarios import find_scenarios, run_suite
        results = run_suite(find_scenarios("sweep"), self.root / "sweep", app_overrides=self.app,
                            quiet=self.options.quiet)
        passed = sum(1 for result in results if result.passed)
        self.facts["sweep"] = {"passed": passed, "total": len(results),
                               "failed": [result.name for result in results if not result.passed]}
        return f"{passed}/{len(results)} scenarios passed"

    def verify(self):
        from .verify import verify
        _, rows = verify(out_dir=self.root / "verify", registry_path=self.dataset / "registry.json",
                         app_overrides=self.app, quiet=self.options.quiet)
        counts = {}
        for row in rows:
            counts[row["result"]] = counts.get(row["result"], 0) + 1
        self.facts["verify"] = {"counts": counts, "results": rows}
        return ", ".join(f"{count} {result}" for result, count in sorted(counts.items())) or "nothing to verify"

    def crawl(self):
        from .crawler import Crawler
        done = []
        for number in range(self.options.crawls):
            profile = CRAWL_PROFILES[number % len(CRAWL_PROFILES)]
            seed = self.seed + number
            options = {"seed": profile, "network": "mock"}
            options.update(self.app)
            summary = Crawler(self.root / f"crawl-{profile}-r{seed}", steps=self.options.crawl_steps, seed=seed,
                              app_options=options, quiet=True).run()
            done.append({"profile": profile, "seed": seed, "controls_used": summary["controls_used"],
                         "controls_seen": summary["controls_seen"], "findings": summary["findings"],
                         "restarts": summary["restarts"]})
            self.log(f"  crawl {profile} seed {seed}: {summary['controls_used']}/{summary['controls_seen']} controls, "
                     f"{summary['findings']} finding(s)")
        self.facts["crawls"] = done
        return "; ".join(f"{item['profile']} r{item['seed']}: {item['controls_used']} controls, "
                         f"{item['findings']} findings" for item in done)

    def interim_dataset(self):
        if not self.facts.get("interim_dataset"):
            from .dataset import build
            build(out_dir=self.dataset, handoff=False, quiet=True)
            self.facts["interim_dataset"] = True

    def minimise(self):
        """Shrink the replays of new harness-detected issues to the steps that matter."""
        from .minimise import minimisable, minimise_issue
        from .registry import ACTIVE, Registry
        self.interim_dataset()
        registry = Registry(self.dataset / "registry.json")
        pending = [issue for issue in registry.issues.values() if issue.get("status") in ACTIVE
                   and minimisable(issue) and issue.get("scenario") and not issue.get("minimised")]
        pending.sort(key=lambda issue: issue["id"])
        results = []
        for issue in pending[:self.options.minimise]:
            try:
                result = minimise_issue(registry, issue["id"], self.root / "minimise",
                                        scenarios_dir=self.dataset / "scenarios", max_minutes=self.options.minimise_minutes,
                                        app_overrides=self.app, log=self.log)
                results.append(f"{issue['id']} {result['original']}->{len(result['steps'])}"
                               if result["reproduced"] else f"{issue['id']} not reproducible")
            except (KeyError, ValueError, OSError) as error:
                results.append(f"{issue['id']} skipped ({error})")
            registry.save()
        self.facts["minimise"] = results
        return "; ".join(results) or "nothing new to minimise"

    def gaps(self):
        self.interim_dataset()
        written = write_gap_missions(self.dataset, self.root / "missions", self.options.gap_missions)
        self.facts["gap_missions"] = [str(path) for path in written]
        return f"{len(written)} gap mission(s): " + ", ".join(path.stem for path in written)

    def ai_testers(self):
        from .agent.matrix import run_matrix
        from .agent.runner import RunConfig
        from .cli import resolve_models
        models = resolve_models(self.options.models)
        missions = self.mission_list()
        personas = [item.strip() for item in self.options.personas.split(",") if item.strip()]
        models, missions, personas = fit_budget(models, missions, personas, self.options.budget)
        runs = len(models) * len(missions) * len(personas)
        per_run = round(self.options.budget / max(1, runs), 4)
        base = RunConfig(model=models[0], max_steps=self.options.max_steps, max_cost=per_run,
                         app=dict(self.app),
                         quiet=self.options.quiet)
        root, results = run_matrix(base, models, missions, personas, parallel=self.options.parallel,
                                   out_dir=self.root / "matrix")
        cost = sum(float((result.get("usage") or {}).get("cost") or 0) for result in results)
        self.facts["ai_testers"] = {"models": models, "missions": missions, "personas": personas, "runs": runs,
                                    "max_cost_per_run": per_run, "cost": round(cost, 4)}
        return f"{runs} run(s) with {', '.join(models)}; cost ${cost:.4f} of ${self.options.budget:.2f}"

    def mission_list(self):
        from .agent.prompts import available
        text = self.options.missions.strip()
        if text == "all":
            return available("missions")
        if text == "gaps":
            return CORE_MISSIONS[:2] + list(self.facts.get("gap_missions") or [])
        return [item.strip() for item in text.split(",") if item.strip()]

    def final_dataset(self):
        from .dataset import build
        summary = build(out_dir=self.dataset, quiet=True)
        self.facts["dataset"] = {key: summary[key] for key in ("issues", "code", "ui", "copy", "improvements")}
        return (f"{summary['issues']['active']} open issues, {summary['improvements']} backlog items, "
                f"DT code exercised {summary['code']['percent']}%")

    # ----- main -----------------------------------------------------------------------
    def run(self):
        options = self.options
        self.log(f"folder {self.root}; dataset {self.dataset}; random seed {self.seed}")
        self.stage("environment", self.environment)
        self.stage("dt-tests", self.dt_tests, None if options.dt_tests else "disabled with --no-dt-tests")
        self.stage("sweep", self.sweep, None if options.sweep else "disabled with --no-sweep")
        self.stage("verify", self.verify, None if options.verify else "disabled with --no-verify")
        self.stage("crawl", self.crawl, None if options.crawls > 0 else "--crawls 0")
        self.stage("minimise", self.minimise, None if options.minimise > 0 else "--minimise 0")
        key = bool(os.environ.get("OPENROUTER_API_KEY"))
        ai_skip = None
        if options.budget <= 0:
            ai_skip = "no --budget given (AI testers cost money)"
        elif not key:
            ai_skip = "OPENROUTER_API_KEY is not set"
        wants_gaps = ai_skip is None and options.missions == "gaps" and options.gap_missions > 0
        self.stage("gaps", self.gaps, None if wants_gaps else "only needed for AI gap missions")
        self.stage("ai-testers", self.ai_testers, ai_skip)
        self.stage("dataset", self.final_dataset)
        report = self.write_report()
        ok = all(stage["status"] != "failed" for stage in self.stages)
        self.progress("done")
        self.log(f"done in {time.time() - self.started:.0f}s; report {report}")
        return {"ok": ok, "report": str(report), "root": str(self.root), "stages": self.stages, "facts": self.facts}

    def write_report(self):
        lines = ["# Jev campaign", "", f"Folder: `{self.root}`  ", f"Dataset: `{self.dataset}`  ",
                 f"Random seed: {self.seed} (pass --random-seed to repeat the crawls)  ",
                 f"Duration: {time.time() - self.started:.0f}s", "", "| Stage | Result | Time | Detail |", "|---|---|---|---|"]
        for stage in self.stages:
            lines.append(f"| {stage['name']} | {stage['status']} | {stage['seconds']}s | "
                         f"{summarise(stage['detail']).replace('|', '/')} |")
        dataset = self.facts.get("dataset")
        if dataset:
            issues = dataset["issues"]
            lines += ["", "## Dataset", "",
                      f"- Open or regressed issues: {issues['active']} of {issues['total']} ({issues['by_status']})",
                      f"- DT code exercised by Jev: {dataset['code']['percent']}% of statements, "
                      f"{dataset['code']['functions_run']}/{dataset['code']['functions']} functions",
                      f"- UI: {dataset['ui']['controls']} controls seen, {dataset['ui']['used']} used, "
                      f"{dataset['ui']['unlabelled']} unlabelled, {dataset['ui']['labels_never_seen']} labels never shown",
                      f"- Backlog: {dataset['improvements']} items in `{self.dataset / 'improvements.md'}`",
                      f"- DT handoff: `{self.dataset / 'handoff' / 'README.md'}`"]
        tests = self.facts.get("dt_tests")
        if tests:
            lines += ["", "## DT's own tests", ""]
            for name, info in tests["suites"].items():
                lines.append(f"- {name}: {info.get('summary')} (log `{info.get('log')}`)")
                for failure in info.get("failures", [])[:10]:
                    lines.append(f"  - {failure}")
            if tests.get("dt_tree_changed"):
                lines.append("- WARNING: DT's working tree changed while its tests ran: "
                             + ", ".join(tests["dt_tree_changed"][:10]))
        verify = self.facts.get("verify")
        if verify:
            lines += ["", "## Known issues re-checked", "", "| Issue | Result | Status | Why |", "|---|---|---|---|"]
            for row in verify["results"]:
                lines.append(f"| {row['id']} | {row['result']} | {row.get('status')} | "
                             f"{str(row.get('reason', '')).replace('|', '/')[:140]} |")
        ai = self.facts.get("ai_testers")
        if ai:
            lines += ["", "## AI testers", "", f"- Models: {', '.join(ai['models'])}",
                      f"- Missions: {', '.join(Path(item).stem for item in ai['missions'])}",
                      f"- Personas: {', '.join(ai['personas'])}",
                      f"- Runs: {ai['runs']}, cap ${ai['max_cost_per_run']} each; spent ${ai['cost']}"]
        path = self.root / "report.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.root / "campaign.json").write_text(json.dumps({"stages": self.stages, "facts": self.facts,
                                                             "options": asdict(self.options), "seed": self.seed},
                                                            indent=2, default=str), encoding="utf-8")
        return path


def summarise(detail):
    text = str(detail or "").strip().splitlines()
    return text[0][:220] if text else ""


def fit_budget(models, missions, personas, budget, floor=0.05):
    """Trim the matrix so each run can spend at least `floor` USD: personas first, then models, then missions."""
    models, missions, personas = list(models), list(missions), list(personas)
    while len(models) * len(missions) * len(personas) * floor > budget:
        if len(personas) > 1:
            personas.pop()
        elif len(models) > 1:
            models.pop()
        elif len(missions) > 1:
            missions.pop()
        else:
            break
    return models, missions, personas


def write_gap_missions(dataset, folder, count):
    """Missions for AI testers aimed at the screens and code no run has reached yet."""
    path = Path(dataset) / "improvements.jsonl"
    if not path.exists() or count <= 0:
        return []
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = [item for item in items if item["kind"] in ("never on screen", "untested code")]
    groups = {}
    for item in targets:
        where = (item.get("where") or ["?"])[0].split(":")[0]
        groups.setdefault(where, []).append(item)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for number, (module, entries) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))[:count], 1):
        wanted = []
        for entry in entries[:8]:
            detail = entry.get("detail") or ""
            wanted.append(f"- {entry['title']}" + (f" ({detail[:160]})" if detail else ""))
        body = ["---", f"title: Reach untested parts of {module}", "max_steps: 45", "seed: sample", "network: mock", "---",
                f"Earlier Jev runs never reached some of DT's screens and code in {module}. Find out how a trainer "
                "gets there and use them properly, then try their edge cases (empty, very long and unusual input, "
                "cancelling half way, repeating an action, doing things out of order). Things nobody has reached yet:",
                *wanted,
                "If something cannot be reached from the interface, report that as a finding with what you tried."]
        target = folder / f"gap-{number}-{re.sub(r'[^a-z0-9]+', '-', module.lower()).strip('-')}.md"
        target.write_text("\n".join(body) + "\n", encoding="utf-8")
        written.append(target)
    return written


def run_dt_tests(folder, mutation=False, log=print):
    """DT's own suites under coverage. Reads DT only: bytecode caches off, DT's git status checked."""
    from .session import KEEP_ENV, SECRET_ENV
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    checkout = dt_path()
    python = host_python()
    home = folder / "home"
    home.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key in KEEP_ENV or not SECRET_ENV.search(key)}
    env.pop("OPENROUTER_API_KEY", None)
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(checkout / "src"), "QT_QPA_PLATFORM": "offscreen",
                "PYTHONIOENCODING": "utf-8", "HOME": str(home), "USERPROFILE": str(home),
                "XDG_DATA_HOME": str(home / "share"), "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_CACHE_HOME": str(home / "cache"), "APPDATA": str(home / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(home / "AppData" / "Local")})
    tools = real_ffmpeg_tools()
    if tools.get("ffmpeg") and tools.get("ffprobe"):
        env["DT_FFMPEG"], env["DT_FFPROBE"] = tools["ffmpeg"], tools["ffprobe"]
    before = git_status(checkout)
    have_coverage = subprocess.run([python, "-c", "import coverage"], capture_output=True, env=env).returncode == 0
    data_file = folder / "dt-tests.coverage"
    if data_file.exists():
        data_file.unlink()
    results = {"python": python, "coverage": have_coverage, "suites": {}}
    suites = [("core", "tests"), ("desktop", "tests/desktop")]
    for name, start in suites:
        if not (checkout / start).is_dir():
            continue
        command = [python]
        if have_coverage:
            command += ["-m", "coverage", "run", "--append", f"--data-file={data_file}", "--source=dt"]
        command += ["-m", "unittest", "discover", "-s", start]  # as DT's README runs them
        log(f"  DT {name} tests: {' '.join(command[1:])}")
        started = time.time()
        try:
            completed = subprocess.run(command, cwd=checkout, env=env, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=1800)
            output, code = completed.stdout + completed.stderr, completed.returncode
        except subprocess.TimeoutExpired as error:
            output, code = str(error.stdout or "") + str(error.stderr or "") + "\nTIMED OUT after 1800s", -1
        log_path = folder / f"{name}.log"
        log_path.write_text(output, encoding="utf-8")
        results["suites"][name] = parse_unittest(output, code) | {"log": str(log_path),
                                                                  "seconds": round(time.time() - started, 1)}
    if mutation and (checkout / "scripts" / "mutation_check.py").exists():
        started = time.time()
        try:
            completed = subprocess.run([python, "scripts/mutation_check.py"], cwd=checkout, env=env,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5400)
            output, code = completed.stdout + completed.stderr, completed.returncode
        except subprocess.TimeoutExpired as error:
            output, code = str(error.stdout or "") + "\nTIMED OUT", -1
        (folder / "mutation.log").write_text(output, encoding="utf-8")
        results["suites"]["mutation"] = {"summary": ("all mutations caught" if code == 0 else
                                                     f"exit code {code}; see mutation.log"),
                                         "ok": code == 0, "log": str(folder / "mutation.log"),
                                         "seconds": round(time.time() - started, 1), "failures": []}
    if have_coverage and data_file.exists():
        raw = folder / "coverage-raw.json"
        subprocess.run([python, "-m", "coverage", "json", f"--data-file={data_file}", "-o", str(raw), "-q"],
                       cwd=checkout, env=env, capture_output=True)
        convert_coverage(raw, folder / "coverage.json", dt_version().get("commit"))
    after = git_status(checkout)
    changed = sorted(set(after) ^ set(before))
    results["dt_tree_changed"] = changed
    write_test_findings(folder, results)
    (folder / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return results


def settle_test_issues(registry_path, results):
    """Issues raised by failing DT tests are fixed once those suites pass again."""
    from .registry import ACTIVE, Registry
    registry = Registry(registry_path)
    failing = {f"dt-test@{failure}" for info in results["suites"].values() for failure in info.get("failures", [])}
    suites_ok = {f"dt-suite@{name}" for name, info in results["suites"].items() if info.get("tests")}
    commit = dt_version().get("commit", "")
    changed = False
    for issue in registry.issues.values():
        if issue.get("origin") != "dt-tests" or issue.get("status") not in ACTIVE:
            continue
        signatures = set(issue.get("signatures") or [])
        tests = {item for item in signatures if item.startswith("dt-test@")}
        suites = {item for item in signatures if item.startswith("dt-suite@")}
        if (tests and not tests & failing and results["suites"]) or (suites and suites <= suites_ok):
            registry.set_status(issue["id"], "fixed", by="dt-tests", commit=commit,
                                note="DT's own tests pass again on this commit.")
            changed = True
    if changed:
        registry.save()


def git_status(checkout):
    try:
        output = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], capture_output=True,
                                text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in output.splitlines() if line.strip()]


def parse_unittest(output, code):
    ran = re.findall(r"^Ran (\d+) tests? in ([\d.]+)s", output, re.M)
    verdict = re.findall(r"^(OK|FAILED)(?: \(([^)]*)\))?\s*$", output, re.M)
    failures = re.findall(r"^(?:FAIL|ERROR): (\S+) \(([^)]+)\)", output, re.M)
    summary = f"{ran[-1][0]} tests" if ran else "did not run"
    if verdict:
        summary += f", {verdict[-1][0]}" + (f" ({verdict[-1][1]})" if verdict[-1][1] else "")
    elif code not in (0, None):
        summary += f", exit code {code}"
    return {"summary": summary, "ok": code == 0, "tests": int(ran[-1][0]) if ran else 0,
            "failures": [f"{test} ({where})" for test, where in failures]}


def convert_coverage(raw, target, commit):
    try:
        data = json.loads(Path(raw).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    files = {}
    for path, info in (data.get("files") or {}).items():
        normalised = path.replace("\\", "/")
        if "/dt/" in normalised:
            key = "dt/" + normalised.split("/dt/")[-1]
        elif normalised.startswith("dt/"):
            key = normalised
        else:
            continue
        files[key] = sorted(info.get("executed_lines") or [])
    Path(target).write_text(json.dumps({"tool": "coverage.py (DT tests)", "commit": commit, "time": time.time(),
                                        "files": files}), encoding="utf-8")


def write_test_findings(folder, results):
    """A failing DT test is a finding for DT like any other."""
    lines = []
    for name, info in results["suites"].items():
        for failure in info.get("failures", []):
            lines.append({"id": f"T{len(lines) + 1:03d}", "source": "dt-tests", "model": "dt-tests",
                          "title": f"DT {name} test fails: {failure}"[:200], "severity": "high",
                          "category": "functional", "confidence": "confirmed",
                          "signature": f"dt-test@{failure}", "expected": "DT's own test passes.",
                          "actual": f"The test failed; see {info.get('log')}",
                          "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "occurrences": 1})
        if not info.get("ok") and not info.get("failures") and name != "mutation":
            lines.append({"id": f"T{len(lines) + 1:03d}", "source": "dt-tests", "model": "dt-tests",
                          "title": f"DT {name} test suite did not complete: {info.get('summary')}"[:200],
                          "severity": "high", "category": "functional", "confidence": "confirmed",
                          "signature": f"dt-suite@{name}", "actual": f"See {info.get('log')}",
                          "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "occurrences": 1})
    path = folder / "findings.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def main():  # pragma: no cover - convenience for `python -m jev.campaign`
    from .cli import main as cli_main
    return cli_main(["campaign", *sys.argv[1:]])
