"""Turn every Jev run into one improvement dataset for DT.

``jev dataset build`` reads all runs under the runs folder (AI testers, matrices, scripted
sweeps, regression checks, crawls, CLI sessions and campaigns) and writes:

- ``registry.json``: stable JEV-#### issues with status history (kept between builds)
- ``jev-dataset.sqlite`` plus CSV/JSONL copies of every table (see ``README.md`` there)
- ``improvements.md``: one ranked backlog of fixes, coverage gaps, copy and speed problems
- ``handoff/``: a brief, a replayable scenario and evidence for each open issue, for DT

It only reads DT's source (to point at code and measure coverage); it never changes DT.
"""

import csv
import hashlib
import json
import math
import re
import shutil
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import __version__
from .config import REPO_DIR, dt_path, dt_version, runs_dir
from .dtsource import SourceIndex, known_limitations, normalise, parse_frames
from .findings import SEVERITY_RANK, canonical_signature, text_signature
from .registry import ACTIVE, Registry, dataset_dir, now

SEVERITY_POINTS = {"critical": 100, "high": 60, "medium": 30, "low": 10, "info": 3}
CATEGORY_WEIGHT = {"data-loss": 1.5, "crash": 1.5, "security-privacy": 1.5, "exception": 1.25, "freeze": 1.25,
                   "functional": 1.1, "validation": 1.05, "accessibility": 1.05}
CONFIDENCE_WEIGHT = {"confirmed": 1.0, "likely": 0.8, "possible": 0.5}
ACTION_TOOLS = {"click", "type_text", "select_option", "set_checked", "select_item", "select_tab", "press_key",
                "draw", "scroll", "set_value", "resize_window", "close_window"}
RUN_MARKERS = ("run.json", "scenario-result.json", "crawl.json", "cli-state.json", "steps.jsonl", "findings.jsonl")
SKIP_DIRS = {"app", "evidence", "snapshots", "repro", "missions", "handoff", "sandbox", "__pycache__"}
NAMED_ROLES = {"textbox", "textarea", "combobox", "list", "tree", "table", "slider", "spinbox", "checkbox",
               "button", "canvas"}
UI_MODULES = ("dt/ui.py", "dt/assessment_ui.py", "dt/playback_ui.py", "dt/registration_ui.py", "dt/report_ui.py",
              "dt/signature_ui.py", "dt/ffmpeg_ui.py", "dt/help_guide.py")

ERROR_LEAK = re.compile(r"Traceback|\[Errno|\bErrno\b|NoneType|object at 0x|\b[A-Z][A-Za-z]+(?:Error|Exception)\b"
                        r"|\bstderr\b|line \d+, in |\b0x[0-9a-f]{8,}\b|\[[\w,]+ @ 0x[0-9a-f]+\]")
TECH_TERMS = re.compile(r"\b(json|sqlite|sql|ssl|tls|payload|endpoint|stdout|subprocess|utf-?8|uuid|codec|mux|crf|"
                        r"sha-?256|http \d{3}|errno)\b", re.I)
PLACEHOLDER_LEAK = re.compile(r"\{[a-z_0-9]*\}|%[sd]\b|\bNone\b|\bnan\b|\bundefined\b")
TERM_GROUPS = [
    ("the encrypted store", ["vault", "records"]),
    ("one driver's assessment", ["assessment", "session"]),
    ("evidence files", ["evidence", "recording", "video"]),
    ("the compressed copy", ["review copy", "compressed copy", "derivative"]),
    ("signing", ["sign", "signature", "sign-off"]),
    ("module list", ["catalogue", "library"]),
]
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with"}
INPUT_CLASSES = [
    ("empty", lambda text: text == ""), ("whitespace", lambda text: not text.strip()),
    ("very long", lambda text: len(text) > 200), ("markup/script", lambda text: "<" in text and ">" in text),
    ("sql-like", lambda text: "'" in text and "--" in text), ("path-like", lambda text: "/" in text or "\\" in text),
    ("format tokens", lambda text: "{" in text or "%" in text), ("invalid date", lambda text: text == "2026-02-30"),
    ("number", lambda text: bool(re.fullmatch(r"-?\d+", text))),
    ("non-ASCII", lambda text: any(ord(char) > 127 for char in text)), ("multi-line", lambda text: "\n" in text),
]


# ----- small helpers ---------------------------------------------------------------------
def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(path):
    items = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return items
    for line in lines:
        if line.strip():
            try:
                items.append(json.loads(line))
            except ValueError:
                continue
    return items


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch)) if epoch else ""


def stable_id(prefix, *parts):
    digest = hashlib.sha1("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def percentile(values, share):
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


def quoted_texts(text):
    found = []
    for match in re.finditer(r'"([^"\n]{4,240})"|\'([^\'\n]{4,240})\'|\u201c([^\u201d\n]{4,240})\u201d', text or ""):
        found.append(next(group for group in match.groups() if group))
    return found


def input_class(text):
    for name, test in INPUT_CLASSES:
        if test(text):
            return name
    return "ordinary"


# ----- discovering runs ------------------------------------------------------------------
def discover(roots):
    """Every run folder under the roots, plus DT unit-test coverage files written by campaigns."""
    runs, test_coverage = [], []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            folder, depth = stack.pop()
            if (folder / ".jev-ignore").exists():
                continue  # e.g. minimiser trials, which break journeys on purpose
            if folder.name == "dt-tests":
                if (folder / "coverage.json").exists():
                    test_coverage.append(folder / "coverage.json")
                if (folder / "findings.jsonl").exists():
                    runs.append((root, folder))
                continue
            if any((folder / marker).exists() for marker in RUN_MARKERS):
                runs.append((root, folder))
                continue
            if depth >= 4:
                continue
            try:
                children = sorted(folder.iterdir())
            except OSError:
                continue
            for child in reversed(children):
                if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith("."):
                    stack.append((child, depth + 1))
    runs.sort(key=lambda item: str(item[1]))
    return runs, test_coverage


def load_run(root, folder, several_roots=False):
    relative = folder.relative_to(root).as_posix() if folder != root else folder.name
    run_id = f"{root.name}/{relative}" if several_roots else relative
    session = read_json(folder / "app" / "session.json", {}) or {}
    dt = session.get("dt") or {}
    options = session.get("options") or {}
    run = {"id": run_id, "path": str(folder), "kind": "other", "group": "", "model": "", "mission": "", "persona": "",
           "seed_profile": options.get("seed", ""), "network": options.get("network", ""),
           "screen": options.get("screen", ""), "dt_commit": dt.get("commit") or "", "dt_branch": dt.get("branch") or "",
           "dt_dirty": bool(dt.get("dirty")), "jev_version": session.get("jev", ""),
           "started": session.get("started") or 0, "duration": 0.0, "steps": 0, "actions": 0, "errors": 0,
           "findings": 0, "cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "outcome": "", "scenario": "",
           "passed": None}
    parent = folder.parent
    agent = read_json(folder / "run.json")
    scenario = read_json(folder / "scenario-result.json")
    crawl = read_json(folder / "crawl.json")
    if agent:
        usage = agent.get("usage") or {}
        run.update(kind="agent", model=agent.get("model", ""), mission=agent.get("mission", ""),
                   persona=agent.get("persona", ""), outcome=agent.get("stop_reason", ""),
                   cost=float(usage.get("cost") or 0), prompt_tokens=int(usage.get("prompt_tokens") or 0),
                   completion_tokens=int(usage.get("completion_tokens") or 0),
                   duration=float(agent.get("duration") or 0), group="matrix" if (parent / "plan.json").exists() else "")
    elif scenario:
        source = str(scenario.get("scenario_file") or "")
        group = "regression" if "regressions" in source else ("sweep" if "sweep" in source else "custom")
        if parent.name.startswith("verify-") or "verify" in parent.name:
            group = "verify"
        run.update(kind="scenario", group=group, scenario=scenario.get("name", ""), passed=scenario.get("passed"),
                   duration=float(scenario.get("duration") or 0), mission=scenario.get("name", ""),
                   model="scenario", persona="deterministic", outcome="passed" if scenario.get("passed") else "failed")
        if not run["dt_commit"] and scenario.get("dt"):
            run.update(dt_commit=scenario["dt"].get("commit") or "", dt_dirty=bool(scenario["dt"].get("dirty")))
    elif crawl:
        run.update(kind="crawl", model="crawler", mission="crawl", persona=f"seed-{crawl.get('seed')}",
                   duration=float(crawl.get("duration") or 0),
                   outcome=f"{crawl.get('controls_used')}/{crawl.get('controls_seen')} controls used")
    elif (folder / "cli-state.json").exists():
        run.update(kind="cli", model="cli")
    elif folder.name == "dt-tests":
        results = read_json(folder / "results.json", {}) or {}
        run.update(kind="dt-tests", model="dt-tests", outcome="; ".join(
            f"{name}: {info.get('summary')}" for name, info in (results.get("suites") or {}).items()))
        commit = (read_json(folder / "coverage.json", {}) or {}).get("commit")
        if commit:
            run["dt_commit"] = commit
    return run


# ----- the build -------------------------------------------------------------------------
class DatasetBuilder:
    def __init__(self, out_dir=None, roots=None, checkout=None, handoff=True, quiet=False):
        self.out = Path(out_dir) if out_dir else dataset_dir()
        self.roots = [Path(root) for root in (roots or [runs_dir()])]
        self.checkout = Path(checkout) if checkout else dt_path()
        self.handoff = handoff
        self.quiet = quiet
        self.notes = []
        self.registry = Registry(self.out / "registry.json")
        self.runs, self.steps, self.findings = [], [], []
        self.run_index = {}

    def log(self, message):
        if not self.quiet:
            print(message, flush=True)

    # ----- loading --------------------------------------------------------------------
    def load(self):
        folders, self.test_coverage_files = discover(self.roots)
        several = len(self.roots) > 1
        for root, folder in folders:
            run = load_run(root, folder, several)
            steps = read_jsonl(folder / "steps.jsonl")
            findings = read_jsonl(folder / "findings.jsonl")
            if not steps and not findings and run["kind"] in ("cli", "other"):
                continue
            if run["kind"] == "dt-tests" and not run["started"]:
                run["started"] = (folder / "findings.jsonl").stat().st_mtime
            run["steps"] = len(steps)
            run["actions"] = sum(1 for step in steps if step.get("tool") in ACTION_TOOLS)
            run["errors"] = sum(1 for step in steps if not step.get("ok"))
            run["findings"] = len(findings)
            if steps:
                run["started"] = run["started"] or steps[0].get("time", 0)
                if not run["duration"]:
                    run["duration"] = round(float(steps[-1].get("time", 0)) - float(steps[0].get("time", 0)), 1)
            run["started_at"] = iso(run["started"])
            for step in steps:
                step["run"] = run["id"]
            for finding in findings:
                finding["run"] = run["id"]
                finding["ref"] = f"{run['id']}#{finding.get('id')}"
                canonical = canonical_signature(finding)
                if canonical and canonical != finding.get("signature"):
                    finding["raw_signature"], finding["signature"] = finding.get("signature"), canonical
            coverage = read_json(folder / "app" / "coverage.json")
            run["coverage"] = coverage.get("files") if coverage else None
            run["coverage_tool"] = coverage.get("tool", "") if coverage else ""
            self.runs.append(run)
            self.run_index[run["id"]] = run
            self.steps.extend(steps)
            self.findings.extend(findings)
        self.log(f"Read {len(self.runs)} run(s): {dict(Counter(run['kind'] for run in self.runs))}, "
                 f"{len(self.steps)} steps, {len(self.findings)} findings.")

    # ----- issues ---------------------------------------------------------------------
    def assign_issues(self):
        ordered = sorted(self.findings, key=lambda item: (str(item.get("time", "")), item.get("ref", "")))
        created = 0
        for finding in ordered:
            run = self.run_index.get(finding["run"], {})
            issue = self.registry.match(finding, finding["ref"])
            if issue is None:
                issue = self.registry.create(finding)
                created += 1
            self.registry.absorb(issue, finding, run)
            self.registry.assignments[finding["ref"]] = issue["id"]
            finding["issue_id"] = issue["id"]
        self.log(f"Issues: {len(self.registry.issues)} in the registry ({created} new).")

    def attach_replays(self):
        """Give every issue a scenario that walks to it: the scripted journey, or a recording of the run."""
        from .scenarios import record_scenario

        folder = self.out / "scenarios"
        by_issue = defaultdict(list)
        for finding in self.findings:
            by_issue[finding["issue_id"]].append(finding)
        made = 0
        for issue_id, issue in self.registry.issues.items():
            reference = issue.get("scenario") or ""
            if reference.startswith("regressions/") or (reference and Path(reference).exists()):
                continue
            for finding in sorted(by_issue.get(issue_id, []), key=lambda item: str(item.get("time", ""))):
                run = self.run_index.get(finding["run"]) or {}
                run_dir = Path(run.get("path", ""))
                scenario = None
                if finding.get("repro_scenario") and Path(finding["repro_scenario"]).exists():
                    scenario = read_json(finding["repro_scenario"])
                elif run.get("kind") == "scenario":
                    result = read_json(run_dir / "scenario-result.json", {}) or {}
                    if result.get("scenario_file") and Path(result["scenario_file"]).exists():
                        scenario = read_json(result["scenario_file"])
                if scenario is None and (run_dir / "steps.jsonl").exists() and finding.get("step"):
                    try:
                        scenario = record_scenario(run_dir, until_step=int(finding["step"]), name=f"replay-{issue_id}")
                    except (OSError, ValueError, KeyError, TypeError):
                        scenario = None
                if not scenario or not scenario.get("steps"):
                    continue
                scenario = dict(scenario)
                scenario["name"] = scenario.get("name") if run.get("kind") == "scenario" else f"replay-{issue_id.lower()}"
                scenario.setdefault("title", f"Replay of {issue_id}")
                scenario["replays_issue"] = {"id": issue_id, "title": issue.get("title"),
                                             "verify_kind": issue.get("verify_kind"),
                                             "signatures": issue.get("signatures", [])}
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{issue_id}.json"
                path.write_text(json.dumps(scenario, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                issue["scenario"] = str(path)
                made += 1
                break
        if made:
            self.log(f"Replays: wrote {made} scenario(s) to {folder}.")

    def issue_rows(self, index):
        by_issue = defaultdict(list)
        for finding in self.findings:
            by_issue[finding["issue_id"]].append(finding)
        rows = []
        for issue_id, issue in self.registry.issues.items():
            findings = by_issue.get(issue_id, [])
            runs = sorted({finding["run"] for finding in findings})
            # Replays that only re-check a known issue do not make it more widespread.
            discovered = [run for run in runs if self.run_index.get(run, {}).get("group") not in ("verify", "regression")]
            reporters = sorted({finding.get("model") or finding.get("source") or "" for finding in findings} - {""})
            occurrences = sum(int(finding.get("occurrences") or 1) for finding in findings)
            best = best_finding(findings)
            row = dict(issue)
            row.update(occurrences=occurrences, runs=len(runs), discovery_runs=len(discovered), run_ids=runs[:50],
                       reporters=reporters,
                       steps=issue.get("minimal_steps") or best_steps(issue, best), evidence=best_evidence(findings),
                       code=self.locate(issue, findings, index), known_limitation=self.limitation_for(issue))
            row["score"] = issue_score(row)
            rows.append(row)
        rows.sort(key=lambda row: (row["status"] not in ACTIVE, -row["score"]))
        rank = 0
        for row in rows:
            if row["status"] in ACTIVE:
                rank += 1
                row["rank"] = rank
        return rows

    def locate(self, issue, findings, index):
        """Where in DT to look: stack frames first, then the code that defines the text involved."""
        places, seen = [], set()

        def add(file, line, function, why):
            key = (file, line)
            if key in seen or len(places) >= 5:
                return
            seen.add(key)
            owner = index.function_at(file, line) if index else None
            places.append({"file": file, "line": line, "function": (owner or {}).get("qualname") or function,
                           "why": why})

        for text in issue.get("suspected") or []:
            for file, line, function in self.resolve_suspected(text, index):
                add(file, line, function, "named in the issue: " + text[:90])
        for finding in findings[:20]:
            frames = parse_frames(str(finding.get("details") or ""))
            if frames:
                add(*frames[-1], "innermost DT frame of the " + (finding.get("category") or "problem"))
                if len(frames) > 1:
                    add(*frames[0], "outermost DT frame")
        if index is None:
            return places
        # Most specific first: text quoted in the report, text shown on screen, the control, the last step.
        texts, controls, steps = [], [], []
        for text in quoted_texts(" ".join(str(issue.get(key) or "") for key in ("title", "expected", "actual"))):
            texts.append((text, f"text '{text[:60]}'"))
        for finding in findings[:10]:
            for text in quoted_texts(" ".join(str(finding.get(key) or "") for key in ("title", "actual", "expected"))):
                texts.append((text, f"text '{text[:60]}'"))
            if finding.get("source") == "harness" and finding.get("category") == "copy":
                shown = str(finding.get("actual") or "")
                head = re.split(r"[\[]|: ", shown, maxsplit=1)[0].strip()
                texts.append((head if len(head) >= 10 else shown[:200], "the text shown on screen"))
            evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
            for key in ("target", "last_action_target"):
                target = evidence.get(key) or {}
                if target.get("name"):
                    controls.append((target["name"], f"the control '{target['name']}'"))
            for step in (finding.get("steps") or [])[-1:] if isinstance(finding.get("steps"), list) else []:
                for text in quoted_texts(str(step)):
                    steps.append((text, f"the step '{str(step)[:60]}'"))
        texts += controls + steps
        done = set()
        for text, why in texts:
            if normalise(text) in done:
                continue
            done.add(normalise(text))
            if " " not in text.strip() and len(text.strip()) < 10:
                continue  # single short words ('Save', 'cancelled') match all over the code base
            for item in index.locate_text(text, limit=2):
                add(item["file"], item["line"], item["function"], f"{item['kind']} {why}")
        return places

    @staticmethod
    def resolve_suspected(text, index):
        """'dt/ui.py: MainWindow.mark_box ...' -> the functions it names, with their lines."""
        if index is None:
            return []
        files = re.findall(r"dt/\w+\.py", text)
        names = re.findall(r"\b([A-Z]\w+\.\w+|[a-z_]\w+(?=\s*\(|\s+(?:sets|keeps|replaces|rebuilds|clears|connects|wires|blocks|raises|shows|returns|calls|sends|ignores|drops|loses|uses)\b))",
                           text)
        found = []
        for name in names:
            for entry in index.functions:
                if (entry["qualname"] == name or entry["qualname"].endswith("." + name) or entry["name"] == name) and \
                        (not files or entry["file"] in files):
                    found.append((entry["file"], entry["start"], entry["qualname"]))
                    break
        return found[:2]

    def limitation_for(self, issue):
        words = set(re.findall(r"[a-z]{4,}", f"{issue.get('title', '')} {issue.get('actual', '')}".lower()))
        for item in self.limitations:
            terms = set(re.findall(r"[a-z]{4,}", item.lower()))
            if terms and len(terms & words) >= max(1, math.ceil(len(terms) * 0.6)):
                return item
        return ""

    # ----- coverage -------------------------------------------------------------------
    def reference_commit(self):
        current = dt_version(str(self.checkout)) if self.checkout else {}
        commits = Counter(run["dt_commit"] for run in self.runs if run.get("coverage") and run["dt_commit"])
        if current.get("commit") in commits:
            return current["commit"], current
        if commits:
            latest = max((run for run in self.runs if run.get("coverage") and run["dt_commit"]),
                         key=lambda run: run["started"])
            return latest["dt_commit"], current
        return current.get("commit"), current

    def code_coverage(self, index, commit):
        used = [run for run in self.runs if run.get("coverage") and run["dt_commit"] == commit]
        skipped = [run for run in self.runs if run.get("coverage") and run["dt_commit"] != commit]
        if skipped:
            self.notes.append(f"Code coverage uses the {len(used)} run(s) on DT {str(commit)[:12]}; "
                              f"{len(skipped)} run(s) on other commits were left out of line coverage.")
        union, runs_hit = defaultdict(set), defaultdict(set)
        by_kind = defaultdict(lambda: defaultdict(set))
        for run in used:
            for file, lines in (run["coverage"] or {}).items():
                union[file].update(lines)
                by_kind[run["kind"]][file].update(lines)
        tests = defaultdict(set)
        for path in self.test_coverage_files:
            data = read_json(path, {}) or {}
            if data.get("commit") and commit and data["commit"] != commit:
                continue
            for file, lines in (data.get("files") or {}).items():
                tests[file].update(lines)
        self.has_test_coverage = bool(tests)
        functions = []
        for entry in index.functions:
            lines = set(entry["lines"])
            if not lines:
                continue
            hit = lines & union.get(entry["file"], set())
            for run in used:
                if lines & set((run["coverage"] or {}).get(entry["file"], ())):
                    runs_hit[(entry["file"], entry["qualname"])].add(run["id"])
            tested = lines & tests.get(entry["file"], set())
            functions.append({"file": entry["file"], "function": entry["qualname"], "start": entry["start"],
                              "end": entry["end"], "statements": len(lines), "hit": len(hit),
                              "percent": round(100.0 * len(hit) / len(lines), 1),
                              "runs": len(runs_hit[(entry["file"], entry["qualname"])]),
                              "by_crawler": len(lines & by_kind["crawl"].get(entry["file"], set())),
                              "by_scenarios": len(lines & by_kind["scenario"].get(entry["file"], set())),
                              "by_agents": len(lines & by_kind["agent"].get(entry["file"], set())),
                              "dt_tests_hit": len(tested) if tests else None,
                              "missed_lines": compress_lines(sorted(lines - hit))})
        files = []
        for file in sorted({entry["file"] for entry in functions}):
            rows = [entry for entry in functions if entry["file"] == file]
            statements = sum(entry["statements"] for entry in rows)
            hit = sum(entry["hit"] for entry in rows)
            tested = sum(entry["dt_tests_hit"] or 0 for entry in rows) if tests else None
            files.append({"file": file, "functions": len(rows), "functions_run": sum(1 for entry in rows if entry["hit"]),
                          "statements": statements, "hit": hit,
                          "percent": round(100.0 * hit / statements, 1) if statements else 0.0,
                          "dt_tests_hit": tested})
        return functions, files, len(used)

    def ui_coverage(self, index):
        controls = {}

        def entry(key):
            if key not in controls:
                parts = split_key(key)
                controls[key] = {"key": key, "window": parts[0], "tab": parts[1], "role": parts[2], "name": parts[3],
                                 "seen_steps": 0, "runs_seen": set(), "used": 0, "used_ok": 0, "used_failed": 0,
                                 "used_by": Counter()}
            return controls[key]

        for step in self.steps:
            run = self.run_index.get(step["run"], {})
            for key in step.get("controls") or []:
                item = entry(key)
                item["seen_steps"] += 1
                item["runs_seen"].add(step["run"])
            target = step.get("target") or {}
            if step.get("tool") in ACTION_TOOLS and target.get("key"):
                item = entry(target["key"])
                item["used"] += 1
                item["used_ok" if step.get("ok") else "used_failed"] += 1
                item["used_by"][run.get("kind", "other")] += 1
                item["runs_seen"].add(step["run"])
        rows = []
        for item in controls.values():
            item["runs_seen"] = len(item["runs_seen"])
            item["used_by"] = dict(item["used_by"])
            item["unlabelled"] = item["role"] in NAMED_ROLES and (not item["name"] or item["name"] == item["role"])
            rows.append(item)
        rows.sort(key=lambda item: (item["window"], item["tab"], item["role"], item["name"]))
        # Labels DT defines that no run has ever shown on screen.
        seen_names = {normalise(item["name"]) for item in rows} | {normalise(item["window"]) for item in rows} | \
                     {normalise(item["tab"]) for item in rows}
        for step in self.steps:
            for dialog in (step.get("events") or {}).get("dialogs", []):
                seen_names.add(normalise(dialog.get("title")))
        unseen = []
        if index is not None:
            for item in index.ui_labels():
                label = normalise(item["text"])
                if not label or len(label) < 3:
                    continue
                if "{}" in label:
                    pattern = re.compile("^" + ".*?".join(re.escape(piece) for piece in label.split("{}")) + "$")
                    if any(pattern.match(name) for name in seen_names):
                        continue
                elif label in seen_names or label.rstrip(":") in seen_names:
                    continue
                unseen.append({"text": item["text"], "kind": item["kind"], "file": item["file"], "line": item["line"],
                               "function": item["function"]})
        return rows, unseen

    # ----- copy, inputs and speed ----------------------------------------------------
    def copy_checks(self, index):
        from .host.monitor import raw_error_reason
        # Leaked error text the harness already reported is an issue in its own right; do not list it twice.
        reported = {finding.get("signature") for finding in self.findings
                    if finding.get("source") == "harness" and finding.get("category") == "copy"}
        texts = {}
        if index is not None:
            for item in index.strings:
                if item["kind"] in ("error", "message", "status", "label", "button", "title", "tab", "field",
                                    "placeholder", "tooltip", "checkbox", "group", "text"):
                    texts.setdefault((item["text"], item["kind"]), {"text": item["text"], "kind": item["kind"],
                                                                     "where": f"{item['file']}:{item['line']}",
                                                                     "function": item["function"], "seen": 0,
                                                                     "origin": "source"})
        for step in self.steps:
            events = step.get("events") or {}
            for dialog in events.get("dialogs", []):
                for text, kind in ((dialog.get("title"), "dialog title"), (dialog.get("message"), "dialog message")):
                    if text:
                        item = texts.setdefault((text, kind), {"text": text, "kind": kind,
                                                               "where": f"{step['run']} step {step.get('step')}",
                                                               "function": "", "seen": 0, "origin": "screen"})
                        item["seen"] += 1
                        if kind == "dialog message":
                            item["signature"] = text_signature(f"dialog '{dialog.get('title')}'", text,
                                                               raw_error_reason(text))
            for text in events.get("status", []):
                item = texts.setdefault((text, "status bar"), {"text": text, "kind": "status bar",
                                                               "where": f"{step['run']} step {step.get('step')}",
                                                               "function": "", "seen": 0, "origin": "screen"})
                item["seen"] += 1
                item["signature"] = text_signature("status bar", text, raw_error_reason(text))
        problems = []
        buttons = [item for item in texts.values() if item["kind"] == "button"]
        sentence = sum(1 for item in buttons if not title_case(item["text"]))
        for item in texts.values():
            text = str(item["text"])
            screen = item["origin"] == "screen"
            if ERROR_LEAK.search(text) and (screen or item["kind"] in ("message", "status")):
                if screen and item.get("signature") in reported:
                    continue
                problems.append(dict(item, check="technical error text", severity="medium",
                                     detail="Shows exception or system error wording to the user."))
            elif TECH_TERMS.search(text) and item["kind"] not in ("error",) and len(text) < 400:
                problems.append(dict(item, check="technical term", severity="info",
                                     detail=f"Uses '{TECH_TERMS.search(text).group(0)}'; check the audience knows it."))
            if screen and PLACEHOLDER_LEAK.search(text):
                problems.append(dict(item, check="unfilled placeholder", severity="medium",
                                     detail=f"Contains '{PLACEHOLDER_LEAK.search(text).group(0)}' as shown on screen."))
            limit = {"button": 40, "status bar": 160, "dialog message": 450, "tab": 28, "title": 60}.get(item["kind"])
            if limit and len(text) > limit:
                problems.append(dict(item, check="too long", severity="low",
                                     detail=f"{len(text)} characters (guide: {limit} for a {item['kind']})."))
            if item["kind"] == "button" and title_case(text) and sentence > len(buttons) / 2:
                problems.append(dict(item, check="inconsistent capitalisation", severity="info",
                                     detail="Title Case, while most DT buttons use sentence case."))
        conflicts = []
        visible = [item for item in texts.values() if item["kind"] not in ("error",)]
        for concept, terms in TERM_GROUPS:
            usage = {}
            for term in terms:
                pattern = re.compile(r"\b" + re.escape(term) + r"s?\b", re.I)
                examples = sorted({str(item["text"])[:80] for item in visible if pattern.search(str(item["text"]))})
                if len(examples) >= 2:
                    usage[term] = examples
            if len(usage) >= 2:
                conflicts.append({"concept": concept, "terms": {term: len(examples) for term, examples in usage.items()},
                                  "examples": {term: examples[:4] for term, examples in usage.items()}})
        return sorted(texts.values(), key=lambda item: (item["origin"], item["kind"], str(item["text"]))), problems, \
            conflicts

    def inputs(self):
        rows = []
        by_run = defaultdict(list)
        for step in self.steps:
            by_run[step["run"]].append(step)
        for run_id, steps in by_run.items():
            steps.sort(key=lambda step: step.get("step", 0))
            for position, step in enumerate(steps):
                if step.get("tool") != "type_text" or not step.get("ok"):
                    continue
                text = str((step.get("args") or {}).get("text", ""))
                reactions = []
                for later in steps[position:position + 3]:
                    events = later.get("events") or {}
                    reactions += [f"dialog: {dialog.get('title')}: {str(dialog.get('message') or '')[:120]}"
                                  for dialog in events.get("dialogs", [])]
                rows.append({"run": run_id, "step": step.get("step"), "field": (step.get("target") or {}).get("key", ""),
                             "input_class": input_class(text), "value": text[:120],
                             "submit": (step.get("args") or {}).get("submit", ""),
                             "reaction": " | ".join(reactions[:3])})
        return rows

    def performance(self):
        groups = defaultdict(list)
        stalls = defaultdict(list)
        for step in self.steps:
            if step.get("tool") not in ACTION_TOOLS or not step.get("ok"):
                continue
            key = (step.get("tool"), (step.get("target") or {}).get("key", ""))
            groups[key].append(int(step.get("latency_ms") or 0))
            for seconds in (step.get("events") or {}).get("stalls", []) or []:
                stalls[key].append(float(seconds or 0))
        rows = []
        for (tool, key), values in groups.items():
            rows.append({"tool": tool, "control": key, "count": len(values),
                         "median_ms": int(statistics.median(values)), "p90_ms": percentile(values, 0.9),
                         "max_ms": max(values), "stalls": len(stalls[(tool, key)]),
                         "worst_stall_s": round(max(stalls[(tool, key)] or [0]), 2)})
        rows.sort(key=lambda row: (-row["worst_stall_s"], -row["p90_ms"]))
        return rows

    # ----- backlog --------------------------------------------------------------------
    def improvements(self, issues, functions, unseen, controls, problems, conflicts, speed):
        items = []
        for issue in issues:
            if issue["status"] not in ACTIVE:
                continue
            where = [f"{place['file']}:{place['line']} ({place['function']})" for place in issue["code"][:3]]
            items.append({"id": issue["id"], "kind": "issue", "priority": issue["score"], "severity": issue["severity"],
                          "title": issue["title"], "detail": issue.get("actual", ""), "where": where,
                          "action": f"Fix, add a DT regression test, then `jev verify --issue {issue['id']}`."
                          if issue.get("scenario") else "Fix, then confirm by replaying the steps in the brief."})
        tests = self.has_test_coverage
        for entry in functions:
            if entry["file"] not in UI_MODULES or entry["hit"] or entry["statements"] < 6:
                continue
            if tests and entry["dt_tests_hit"]:
                continue
            labels = [item["text"] for item in (self.index.strings if self.index else [])
                      if item["function"] == entry["function"] and item["file"] == entry["file"]
                      and item["kind"] not in ("error",)][:4]
            items.append({"id": stable_id("GAP", entry["file"], entry["function"]), "kind": "untested code",
                          "priority": round(8 + min(32, entry["statements"] / 3), 1), "severity": "low",
                          "title": f"No run has executed {entry['function']} ({entry['statements']} statements)"
                                   + (" and DT's own tests do not either" if tests else ""),
                          "detail": ("Texts in it: " + "; ".join(labels)) if labels else "",
                          "where": [f"{entry['file']}:{entry['start']}"],
                          "action": "Point a Jev mission at it (campaign gap missions do this) or add a DT test."})
        if tests:
            for entry in functions:
                if entry["hit"] and entry["dt_tests_hit"] == 0 and entry["statements"] >= 8:
                    items.append({"id": stable_id("TEST", entry["file"], entry["function"]), "kind": "missing unit test",
                                  "priority": round(5 + min(20, entry["statements"] / 5), 1), "severity": "low",
                                  "title": f"{entry['function']} runs when people use DT but no DT test covers it",
                                  "detail": f"Jev runs executed {entry['hit']}/{entry['statements']} statements.",
                                  "where": [f"{entry['file']}:{entry['start']}"],
                                  "action": "Add a DT unit or desktop test; Jev scenarios show realistic inputs."})
        by_function = defaultdict(list)
        for item in unseen:
            by_function[(item["file"], item["function"])].append(item)
        for (file, function), labels in by_function.items():
            items.append({"id": stable_id("UNSEEN", file, function), "kind": "never on screen", "priority": 12.0,
                          "severity": "low",
                          "title": f"{len(labels)} label(s) from {function or file} never appeared in any run",
                          "detail": "; ".join(f"{item['kind']} '{item['text'][:50]}'" for item in labels[:6]),
                          "where": [f"{file}:{labels[0]['line']}"],
                          "action": "Check how people reach this UI; aim a mission or scenario at it."})
        for control in controls:
            if control["unlabelled"]:
                items.append({"id": stable_id("A11Y", control["key"]), "kind": "accessibility", "priority": 20.0,
                              "severity": "medium",
                              "title": f"Unlabelled {control['role']} in {control['window']}"
                                       + (f" / {control['tab']}" if control["tab"] else ""),
                              "detail": "Screen readers and testers cannot name it; give it a label or accessible name.",
                              "where": [], "action": "setAccessibleName or a QLabel with setBuddy."})
        for problem in problems:
            if problem["severity"] == "info":
                continue
            items.append({"id": stable_id("COPY", problem["check"], problem["text"]), "kind": "copy",
                          "priority": {"medium": 30.0, "low": 6.0}.get(problem["severity"], 3.0),
                          "severity": problem["severity"],
                          "title": f"{problem['check'].capitalize()}: {str(problem['text'])[:90]}",
                          "detail": problem["detail"], "where": [problem["where"]] if problem["origin"] == "source" else [],
                          "action": "Reword for the assessor; keep technical detail in logs."})
        for conflict in conflicts:
            items.append({"id": stable_id("TERMS", conflict["concept"]), "kind": "copy", "priority": 8.0,
                          "severity": "low", "title": f"Mixed words for {conflict['concept']}: "
                          + ", ".join(f"'{term}' x{count}" for term, count in conflict["terms"].items()),
                          "detail": "; ".join(f"{term}: {', '.join(examples[:2])}"
                                              for term, examples in conflict["examples"].items()),
                          "where": [], "action": "Pick one term for users and use it everywhere."})
        for row in speed:
            if row["worst_stall_s"] >= 2 or row["p90_ms"] >= 6000:
                items.append({"id": stable_id("PERF", row["tool"], row["control"]), "kind": "performance",
                              "priority": 25.0 if row["worst_stall_s"] >= 2 else 10.0,
                              "severity": "medium" if row["worst_stall_s"] >= 2 else "low",
                              "title": f"{row['tool']} on {row['control'] or 'the app'}: "
                                       + (f"interface froze {row['worst_stall_s']}s" if row["worst_stall_s"] >= 2 else
                                          f"p90 {row['p90_ms']} ms until idle"),
                              "detail": f"{row['count']} action(s); median {row['median_ms']} ms, max {row['max_ms']} ms.",
                              "where": [], "action": "Move the work off the GUI thread or show progress."})
        items.sort(key=lambda item: -item["priority"])
        for rank, item in enumerate(items, 1):
            item["rank"] = rank
        return items

    # ----- main -----------------------------------------------------------------------
    def build(self):
        started = time.time()
        self.out.mkdir(parents=True, exist_ok=True)
        self.limitations = known_limitations(self.checkout)
        self.load()
        commit, current = self.reference_commit()
        index_commit = None if (commit and current.get("commit") == commit and not current.get("dirty")) else commit
        self.index = SourceIndex(self.checkout, commit=index_commit) if self.checkout else None
        if self.index is not None:
            self.notes += self.index.notes
        if self.index is None:
            self.notes.append("The DT checkout was not found, so code locations and coverage are missing.")
        self.assign_issues()
        self.attach_replays()
        issues = self.issue_rows(self.index)
        functions, files, coverage_runs = self.code_coverage(self.index, commit) if self.index else ([], [], 0)
        controls, unseen = self.ui_coverage(self.index)
        texts, problems, conflicts = self.copy_checks(self.index)
        inputs = self.inputs()
        speed = self.performance()
        backlog = self.improvements(issues, functions, unseen, controls, problems, conflicts, speed)
        self.registry.save()
        summary = self.summary(commit, current, issues, functions, files, controls, unseen, problems, conflicts,
                               backlog, coverage_runs, time.time() - started)
        tables = {"runs": [strip(run, ("coverage",)) for run in self.runs], "steps": self.steps,
                  "findings": self.findings, "issues": issues, "ui_controls": controls, "ui_unseen": unseen,
                  "code_functions": functions, "code_files": files, "copy_texts": texts, "copy_problems": problems,
                  "copy_terms": conflicts, "inputs": inputs, "performance": speed, "improvements": backlog}
        self.write_tables(tables)
        history = self.record_history(summary)
        (self.out / "dataset.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        (self.out / "improvements.md").write_text(render_improvements(summary, issues, backlog, files, controls, unseen,
                                                                      problems, conflicts, speed, history),
                                                  encoding="utf-8")
        (self.out / "README.md").write_text(DATASET_README, encoding="utf-8")
        if self.handoff:
            write_handoff(self.out / "handoff", issues, backlog, summary, self.index, self.run_index)
        self.log(f"Dataset written to {self.out} in {time.time() - started:.1f}s.")
        return summary

    def summary(self, commit, current, issues, functions, files, controls, unseen, problems, conflicts, backlog,
                coverage_runs, seconds):
        active = [issue for issue in issues if issue["status"] in ACTIVE]
        statements = sum(row["statements"] for row in files)
        hit = sum(row["hit"] for row in files)
        return {
            "built": now(), "jev": __version__, "seconds": round(seconds, 1), "out": str(self.out),
            "roots": [str(root) for root in self.roots],
            "dt": {"checkout": str(self.checkout) if self.checkout else None, "current": current,
                   "coverage_commit": commit},
            "runs": {"total": len(self.runs), "by_kind": dict(Counter(run["kind"] for run in self.runs)),
                     "cost": round(sum(run["cost"] for run in self.runs), 4),
                     "dt_commits": dict(Counter((run["dt_commit"] or "unknown")[:12] for run in self.runs))},
            "steps": len(self.steps), "findings": len(self.findings),
            "issues": {"total": len(issues), "active": len(active),
                       "by_status": dict(Counter(issue["status"] for issue in issues)),
                       "active_by_severity": dict(Counter(issue["severity"] for issue in active))},
            "code": {"runs_with_coverage": coverage_runs, "statements": statements, "hit": hit,
                     "percent": round(100.0 * hit / statements, 1) if statements else 0.0,
                     "functions": len(functions), "functions_run": sum(1 for row in functions if row["hit"]),
                     "dt_tests": self.has_test_coverage if self.index else False},
            "ui": {"controls": len(controls), "used": sum(1 for row in controls if row["used"]),
                   "unlabelled": sum(1 for row in controls if row["unlabelled"]), "labels_never_seen": len(unseen)},
            "copy": {"problems": len([row for row in problems if row["severity"] != "info"]),
                     "term_conflicts": len(conflicts)},
            "improvements": len(backlog), "notes": self.notes,
        }

    def record_history(self, summary):
        """One line per build, so DT's progress (open issues, coverage) can be followed over time."""
        path = self.out / "history.jsonl"
        entry = {"built": summary["built"], "dt_commit": str((summary["dt"].get("current") or {}).get("commit") or "")[:12],
                 "runs": summary["runs"]["total"], "active_issues": summary["issues"]["active"],
                 "by_status": summary["issues"]["by_status"],
                 "active_by_severity": summary["issues"]["active_by_severity"],
                 "code_percent": summary["code"]["percent"], "functions_run": summary["code"]["functions_run"],
                 "ui_used": summary["ui"]["used"], "unlabelled": summary["ui"]["unlabelled"],
                 "labels_never_seen": summary["ui"]["labels_never_seen"], "copy_problems": summary["copy"]["problems"]}
        history = read_jsonl(path)
        if not history or {k: v for k, v in history[-1].items() if k != "built"} != \
                {k: v for k, v in entry.items() if k != "built"}:
            history.append(entry)
            write_jsonl(path, history[-500:])
        return history

    def write_tables(self, tables):
        database = self.out / "jev-dataset.sqlite"
        if database.exists():
            database.unlink()
        connection = sqlite3.connect(database)
        try:
            for name, rows in tables.items():
                columns = []
                for row in rows:
                    for key in row:
                        if key not in columns:
                            columns.append(key)
                if not columns:
                    columns = ["empty"]
                connection.execute(f"CREATE TABLE {name} ({', '.join(quote(column) for column in columns)})")
                connection.executemany(
                    f"INSERT INTO {name} VALUES ({', '.join('?' for _ in columns)})",
                    [[cell(row.get(column)) for column in columns] for row in rows])
                if name == "steps":
                    write_jsonl(self.out / "steps.jsonl", rows)
                else:
                    write_csv(self.out / f"{name}.csv", columns, rows)
                if name in ("findings", "issues", "improvements"):
                    write_jsonl(self.out / f"{name}.jsonl", rows)
            connection.commit()
        finally:
            connection.close()


# ----- scoring and selection ---------------------------------------------------------
def issue_score(issue):
    points = SEVERITY_POINTS.get(issue.get("severity"), 10)
    weight = CATEGORY_WEIGHT.get(issue.get("category"), 1.0)
    confidence = CONFIDENCE_WEIGHT.get(issue.get("confidence"), 0.7)
    if issue.get("classification") == "confirmed bug":
        confidence = 1.0
    reach = 1 + math.log2(1 + max(1, issue.get("discovery_runs") or issue.get("runs") or 1))
    reporters = 1 + 0.25 * max(0, len(issue.get("reporters") or []) - 1)
    status = 1.3 if issue.get("status") == "regressed" else 1.0
    limitation = 0.3 if issue.get("known_limitation") else 1.0
    return round(points * weight * confidence * reach * reporters * status * limitation, 1)


def best_finding(findings):
    def quality(finding):
        steps = finding.get("steps")
        count = len(steps) if isinstance(steps, list) else len(str(steps or "").splitlines())
        return (finding.get("confidence") == "confirmed", bool((finding.get("evidence") or {}).get("screenshot")
                                                               if isinstance(finding.get("evidence"), dict) else False),
                -SEVERITY_RANK.get(finding.get("severity"), 9), min(count, 12), str(finding.get("time", "")))
    return max(findings, key=quality) if findings else None


def best_steps(issue, finding):
    if finding is None:
        return []
    steps = finding.get("steps") or []
    if isinstance(steps, str):
        steps = [line.strip() for line in steps.splitlines() if line.strip()]
    return [re.sub(r"^\d+[.)]\s*", "", str(step)) for step in steps][:40]


def best_evidence(findings):
    shots = []
    for finding in sorted(findings, key=lambda item: str(item.get("time", "")), reverse=True):
        evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
        if evidence.get("screenshot") and Path(evidence["screenshot"]).exists():
            shots.append({"run": finding["run"], "finding": finding.get("id"), "screenshot": evidence["screenshot"],
                          "snapshot": evidence.get("snapshot", ""), "events": evidence.get("events", "")})
    return shots[:3]


def title_case(text):
    words = [word for word in re.findall(r"[A-Za-z][A-Za-z'-]*", str(text))]
    if len(words) < 3:
        return False
    later = [word for word in words[1:] if word.lower() not in SMALL_WORDS and not word.isupper()]
    return len(later) >= 2 and all(word[0].isupper() for word in later)


def compress_lines(lines):
    ranges, start, previous = [], None, None
    for line in lines:
        if start is None:
            start = previous = line
        elif line == previous + 1:
            previous = line
        else:
            ranges.append(f"{start}-{previous}" if previous != start else str(start))
            start = previous = line
    if start is not None:
        ranges.append(f"{start}-{previous}" if previous != start else str(start))
    return ",".join(ranges)


def split_key(key):
    """window | tab | role | name, where only the window title may itself contain ' | '."""
    parts = str(key).rsplit(" | ", 3)
    return ([""] * (4 - len(parts)) + parts) if len(parts) < 4 else parts


def strip(row, keys):
    return {key: value for key, value in row.items() if key not in keys}


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def cell(value):
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bool):
        return int(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def write_csv(path, columns, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row.get(column) is None else cell(row.get(column)) for column in columns])


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


# ----- reports -----------------------------------------------------------------------
def render_improvements(summary, issues, backlog, files, controls, unseen, problems, conflicts, speed, history=()):
    dt = summary["dt"]
    current = dt.get("current") or {}
    lines = ["# DT improvement backlog (from Jev runs)", "",
             f"Built {summary['built']} by Jev {summary['jev']} from {summary['runs']['total']} runs "
             f"({', '.join(f'{count} {kind}' for kind, count in summary['runs']['by_kind'].items())}), "
             f"{summary['steps']} steps and {summary['findings']} findings.",
             f"DT checkout: `{(current.get('commit') or 'unknown')[:12]}`"
             + (" (uncommitted changes)" if current.get("dirty") else "")
             + f"; coverage measured on `{str(dt.get('coverage_commit') or 'n/a')[:12]}`.", ""]
    code = summary["code"]
    ui = summary["ui"]
    lines += ["## At a glance", "",
              f"- **Open issues:** {summary['issues']['active']} "
              f"({', '.join(f'{count} {severity}' for severity, count in sorted(summary['issues']['active_by_severity'].items(), key=lambda kv: SEVERITY_RANK.get(kv[0], 9)))})",
              f"- **Issue status:** " + ", ".join(f"{count} {status}" for status, count in
                                                   sorted(summary["issues"]["by_status"].items())),
              f"- **DT code run by testers:** {code['percent']}% of statements "
              f"({code['functions_run']}/{code['functions']} functions) over {code['runs_with_coverage']} runs",
              f"- **UI:** {ui['controls']} controls seen, {ui['used']} used, {ui['unlabelled']} unlabelled; "
              f"{ui['labels_never_seen']} labels defined in DT never appeared on screen",
              f"- **Copy:** {summary['copy']['problems']} wording problems, {summary['copy']['term_conflicts']} "
              "mixed-term groups", ""]
    if summary.get("notes"):
        lines += ["Notes: " + " ".join(summary["notes"]), ""]
    if len(history) > 1:
        lines += ["## Trend", "", "| Built | DT | Open issues | Fixed | Code run % | Controls used | Unlabelled |",
                  "|---|---|---|---|---|---|---|"]
        for entry in list(history)[-10:]:
            lines.append(f"| {entry['built']} | `{entry['dt_commit']}` | {entry['active_issues']} | "
                         f"{entry['by_status'].get('fixed', 0)} | {entry['code_percent']} | {entry['ui_used']} | "
                         f"{entry['unlabelled']} |")
        lines.append("")
    lines += ["## Ranked backlog", "", "| # | ID | Kind | Severity | Priority | What | Where |", "|---|---|---|---|---|---|---|"]
    for item in backlog[:60]:
        lines.append(f"| {item['rank']} | {item['id']} | {item['kind']} | {item['severity']} | {item['priority']} | "
                     f"{md(item['title'])} | {md(', '.join(item['where'][:2]))} |")
    if len(backlog) > 60:
        lines.append(f"\n{len(backlog) - 60} more in improvements.csv.")
    lines += ["", "## Open issues", ""]
    active = [issue for issue in issues if issue["status"] in ACTIVE]
    for issue in active:
        lines += [f"### {issue['id']} ({issue['status']}, {issue['severity']} {issue['category']}): {issue['title']}", "",
                  f"Priority {issue['score']}; seen {issue['occurrences']} time(s) in {issue['runs']} run(s) by "
                  f"{', '.join(issue['reporters']) or 'n/a'}; classification: {issue.get('classification')}.", ""]
        if issue.get("expected"):
            lines.append(f"- Expected: {issue['expected']}")
        if issue.get("actual"):
            lines.append(f"- Actual: {issue['actual'][:600]}")
        for place in issue["code"][:3]:
            lines.append(f"- Code: `{place['file']}:{place['line']}` {place['function']} ({place['why']})")
        for text in issue.get("suspected") or []:
            lines.append(f"- Suspected: {text}")
        if issue.get("known_limitation"):
            lines.append(f"- Possibly a documented limitation: \"{issue['known_limitation']}\"")
        lines.append(f"- Brief: handoff/issues/{issue['id']}.md")
        lines.append("")
    closed = [issue for issue in issues if issue["status"] not in ACTIVE]
    if closed:
        lines += ["## Closed or parked issues", "", "| ID | Status | Title |", "|---|---|---|"]
        lines += [f"| {issue['id']} | {issue['status']} | {md(issue['title'])} |" for issue in closed]
        lines.append("")
    if files:
        lines += ["## Code coverage by module", "", "| Module | Functions run | Statements run | % |"
                  + (" DT tests |" if summary["code"]["dt_tests"] else ""),
                  "|---|---|---|---|" + ("---|" if summary["code"]["dt_tests"] else "")]
        for row in sorted(files, key=lambda row: row["percent"]):
            lines.append(f"| {row['file']} | {row['functions_run']}/{row['functions']} | {row['hit']}/{row['statements']} | "
                         f"{row['percent']} |" + (f" {row['dt_tests_hit']} |" if summary["code"]["dt_tests"] else ""))
        lines.append("")
    if unseen:
        lines += ["## Labels DT defines that no run has shown", ""]
        for item in unseen[:40]:
            lines.append(f"- {item['kind']} \"{item['text'][:70]}\" ({item['file']}:{item['line']} {item['function']})")
        lines.append("")
    if conflicts:
        lines += ["## Mixed terminology", ""]
        for conflict in conflicts:
            lines.append(f"- **{conflict['concept']}**: " + "; ".join(
                f"'{term}' in {count} text(s), e.g. \"{conflict['examples'][term][0]}\""
                for term, count in conflict["terms"].items()))
        lines.append("")
    slow = [row for row in speed if row["p90_ms"] >= 3000 or row["worst_stall_s"] >= 1]
    if slow:
        lines += ["## Slowest actions", "", "| Action | Control | Count | Median ms | p90 ms | Worst freeze s |",
                  "|---|---|---|---|---|---|"]
        for row in slow[:15]:
            lines.append(f"| {row['tool']} | {md(row['control'])} | {row['count']} | {row['median_ms']} | {row['p90_ms']} | "
                         f"{row['worst_stall_s']} |")
        lines.append("")
    lines += ["## How to use this", "",
              "1. Take the top backlog items; each issue has a brief in `handoff/issues/` with repro steps, evidence and code.",
              "2. Fix in DT on a branch and add a DT regression test.",
              "3. Run `JEV_DT_PATH=<that checkout> jev verify` to replay the regression scenarios; fixed issues are "
              "marked fixed with the DT commit, and anything that breaks again is marked regressed.",
              "4. Run `jev campaign` again and `jev dataset build` to refresh this backlog.", ""]
    return "\n".join(lines)


def md(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def write_handoff(folder, issues, backlog, summary, index, run_index):
    """One folder DT developers (or a coding agent in the DT repo) can work from."""
    from .scenarios import load_scenario

    if folder.exists():
        shutil.rmtree(folder)
    (folder / "issues").mkdir(parents=True)
    (folder / "scenarios").mkdir()
    (folder / "evidence").mkdir()
    active = [issue for issue in issues if issue["status"] in ACTIVE]
    machine = []
    for issue in active:
        scenario_path = ""
        if issue.get("scenario"):
            try:
                scenario = {key: value for key, value in load_scenario(issue["scenario"]).items() if key != "_path"}
                target = folder / "scenarios" / f"{issue['id']}.json"
                target.write_text(json.dumps(scenario, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                scenario_path = f"scenarios/{issue['id']}.json"
            except (OSError, ValueError, KeyError) as error:
                scenario_path = f"(could not load {issue['scenario']}: {error})"
        shots = []
        for number, evidence in enumerate(issue.get("evidence") or [], 1):
            source = Path(evidence["screenshot"])
            target = folder / "evidence" / f"{issue['id']}-{number}{source.suffix}"
            try:
                shutil.copyfile(source, target)
                shots.append(f"evidence/{target.name}")
            except OSError:
                continue
        brief = render_brief(issue, scenario_path, shots, index, run_index)
        (folder / "issues" / f"{issue['id']}.md").write_text(brief, encoding="utf-8")
        machine.append({key: issue.get(key) for key in (
            "id", "title", "status", "severity", "category", "classification", "confidence", "score", "rank",
            "expected", "actual", "steps", "code", "suspected", "occurrences", "runs", "reporters", "dt_commits",
            "first_seen", "last_seen", "scenario", "verify_kind", "known_limitation", "dt_test")} |
            {"brief": f"issues/{issue['id']}.md", "replay": scenario_path, "screenshots": shots})
    (folder / "issues.json").write_text(json.dumps(machine, indent=2, ensure_ascii=False, default=str) + "\n",
                                        encoding="utf-8")
    others = [item for item in backlog if item["kind"] != "issue"]
    gap_lines = ["# Coverage, copy and speed items", "",
                 "Not bugs as such: places no tester reached, wording to tidy, and slow actions. Ranked.", "",
                 "| # | ID | Kind | What | Where | Suggested action |", "|---|---|---|---|---|---|"]
    gap_lines += [f"| {item['rank']} | {item['id']} | {item['kind']} | {md(item['title'])} | "
                  f"{md(', '.join(item['where'][:2]))} | {md(item['action'])} |" for item in others[:150]]
    (folder / "other-improvements.md").write_text("\n".join(gap_lines) + "\n", encoding="utf-8")
    index_lines = ["# Jev handoff for DT", "",
                   f"Built {summary['built']} from {summary['runs']['total']} Jev runs against DT "
                   f"`{str((summary['dt'].get('current') or {}).get('commit') or 'unknown')[:12]}`.", "",
                   "Each open issue has a brief (`issues/JEV-*.md`) with what happens, how to reproduce it, where in "
                   "the code to look and how to prove the fix. `issues.json` holds the same data for tools and "
                   "coding agents. `scenarios/` holds replayable Jev scenarios; `evidence/` holds screenshots.", "",
                   "## Workflow for a fix", "",
                   "1. Pick the highest-ranked issue below and read its brief.",
                   "2. Fix it in DT on a branch; add a DT regression test (unit or `tests/desktop`).",
                   "3. From the Jev repository: `JEV_DT_PATH=/path/to/that/DT jev verify --issue JEV-XXXX`.",
                   "   A passing replay marks the issue fixed in Jev's registry, tied to your DT commit.",
                   "4. Later runs that see it again mark it regressed automatically.", "",
                   "## Open issues (ranked)", "", "| Rank | ID | Severity | Title | Replay |", "|---|---|---|---|---|"]
    index_lines += [f"| {issue.get('rank')} | [{issue['id']}](issues/{issue['id']}.md) | {issue['severity']} | "
                    f"{md(issue['title'])} | {'yes' if issue.get('scenario') else 'manual'} |" for issue in active]
    index_lines += ["", f"Plus {len(others)} coverage, copy, accessibility and speed items in "
                        "[other-improvements.md](other-improvements.md)."]
    (folder / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def render_brief(issue, scenario_path, shots, index, run_index):
    lines = [f"# {issue['id']}: {issue['title']}", "",
             "| | |", "|---|---|",
             f"| Status | {issue['status']} |",
             f"| Severity / category | {issue['severity']} / {issue['category']} |",
             f"| Classification | {issue.get('classification')} (confidence: {issue.get('confidence')}) |",
             f"| Priority | {issue['score']} (rank {issue.get('rank', '-')}) |",
             f"| Seen | {issue['occurrences']} time(s) in {issue['runs']} run(s); first {issue.get('first_seen') or 'n/a'}, "
             f"last {issue.get('last_seen') or 'n/a'} |",
             f"| Reported by | {', '.join(issue['reporters']) or 'n/a'} |",
             f"| DT commits | {', '.join(issue.get('dt_commits') or []) or 'n/a'} |", ""]
    lines += ["## What happens", ""]
    if issue.get("expected"):
        lines += [f"**Expected:** {issue['expected']}", ""]
    if issue.get("actual"):
        lines += [f"**Actual:** {issue['actual']}", ""]
    if issue.get("known_limitation"):
        lines += [f"> This may be a documented limitation of DT: \"{issue['known_limitation']}\". "
                  "If so, mark it with `jev issues set " + issue["id"] + " --status known-limitation`.", ""]
    if issue.get("steps"):
        minimised = issue.get("minimised") or {}
        heading = "## Reproduce" + (f" (reduced automatically from {minimised['from']} steps)"
                                    if issue.get("minimal_steps") and minimised.get("from") else "")
        lines += [heading, ""] + [f"{number}. {step}" for number, step in enumerate(issue["steps"], 1)] + [""]
    if scenario_path.startswith("scenarios/"):
        lines += [f"Replay with Jev: `jev scenario run {issue.get('scenario')}` (copy in `{scenario_path}`).", ""]
    lines += ["## Where to look", ""]
    for text in issue.get("suspected") or []:
        lines.append(f"- {text}")
    for place in issue.get("code") or []:
        lines.append(f"- `{place['file']}:{place['line']}` in `{place['function']}`: {place['why']}")
    if not (issue.get("suspected") or issue.get("code")):
        lines.append("- No code location found automatically; start from the steps above.")
    lines.append("")
    if index is not None:
        for place in (issue.get("code") or [])[:2]:
            whole_function = str(place.get("why", "")).startswith("named in the issue")
            excerpt = index.excerpt(place["file"], place["line"], 0 if whole_function else 5,
                                    16 if whole_function else 6)
            if excerpt:
                lines += [f"`{place['file']}` around line {place['line']}:", "", "```python", excerpt, "```", ""]
    if shots:
        lines += ["## Evidence", ""] + [f"![screenshot](../{shot})" for shot in shots] + [""]
    runs = [run_index[run] for run in issue.get("run_ids", [])[:6] if run in run_index]
    if runs:
        lines += ["Runs: " + "; ".join(f"{run['id']} ({run['kind']}{', ' + run['model'] if run.get('model') else ''})"
                                       for run in runs), ""]
    if issue.get("dt_test"):
        lines += ["## Suggested DT regression test", "", issue["dt_test"], ""]
    lines += ["## Definition of done", "",
              "1. The fix is on a DT branch with a DT regression test that fails without it.",
              f"2. `JEV_DT_PATH=<that checkout> jev verify --issue {issue['id']}` passes"
              + ("." if issue.get("scenario") else " (no automatic replay yet: re-run the steps above by hand or with "
                                                    "`jev` CLI tools, then `jev issues set " + issue["id"]
                                                    + " --status fixed`)."),
              "3. The next `jev campaign` does not report it again.", "",
              "## Task for a coding agent in the DT repository", "",
              "```text",
              f"Fix {issue['id']} in DT: {issue['title']}.",
              f"Expected: {issue.get('expected') or 'see the brief'}",
              f"Actual: {str(issue.get('actual') or 'see the brief')[:400]}",
              "Start from: " + (", ".join(f"{place['file']}:{place['line']} ({place['function']})"
                                         for place in (issue.get("code") or [])[:3]) or "the steps in the brief") + ".",
              "Work on a branch, follow DT's own AGENTS.md, and add a regression test that fails before the fix"
              + (f" ({issue['dt_test']})" if issue.get("dt_test") else "") + ".",
              "Run DT's unit and desktop test suites before finishing.",
              "```", ""]
    return "\n".join(lines)


DATASET_README = """# Jev improvement dataset for DT

Built by `jev dataset build` from every Jev run under the runs folder. Rebuild it any time; the
issue registry (`registry.json`) keeps issue IDs and status between builds.

| File | What it holds |
|---|---|
| `improvements.md` | Ranked backlog: issues, untested code, labels never shown, copy, accessibility, speed |
| `handoff/` | For DT: a brief, a replay scenario and evidence per open issue (`handoff/README.md`) |
| `registry.json` | Stable JEV-#### issues with status history and verification results |
| `jev-dataset.sqlite` | All tables below in one SQLite file |
| `runs.csv` | One row per run: kind (agent, scenario, crawl, cli), model, mission, DT commit, cost, outcome |
| `steps.jsonl` | Every tool call: tool, arguments, target control, latency, dialogs, status text, findings |
| `findings.jsonl/.csv` | Every raw finding, with the issue it was merged into (`issue_id`) |
| `issues.jsonl/.csv` | Issues with occurrences, reporters, repro steps, evidence, code locations, priority score |
| `ui_controls.csv` | Every control seen on screen: how often seen and used, by which kind of run, unlabelled flag |
| `ui_unseen.csv` | Labels DT's code defines (buttons, tabs, titles...) that no run has seen |
| `code_functions.csv` | Per DT function: statements, statements run by Jev, by kind of run, by DT's own tests |
| `code_files.csv` | The same per module |
| `copy_texts.csv` | User-facing text from the source and from the screen |
| `copy_problems.csv` | Wording checks: leaked errors, unfilled placeholders, jargon, length, capitalisation |
| `copy_terms.csv` | Concepts named with more than one word (for example vault / records) |
| `inputs.csv` | Every value typed into a field, its class (empty, long, script, date...) and DT's reaction |
| `performance.csv` | Per action and control: latency until idle and interface freezes |
| `improvements.csv/.jsonl` | The ranked backlog as data |
| `dataset.json` | Build summary: counts, DT commit, notes |
| `history.jsonl` | One line per build: open issues, coverage and copy numbers, for trends |

Priority scores: issues use severity points (critical 100, high 60, medium 30, low 10) times
category, confidence, reach (runs that hit it) and reporter weights; regressions count 1.3x and
documented limitations 0.3x. Other items use fixed scores so that confirmed bugs rank first.
"""


def export(dataset, target, *, max_screenshots=1, roots=None):
    """A shareable copy of the dataset's reports: no raw runs, no local paths, few screenshots."""
    dataset, target = Path(dataset), Path(target)
    if not (dataset / "dataset.json").exists():
        raise FileNotFoundError(f"No dataset in {dataset}; run `jev dataset build` first")
    summary = json.loads((dataset / "dataset.json").read_text(encoding="utf-8"))
    replacements = [(str(Path(root).resolve()), "<runs>") for root in (roots or summary.get("roots") or [])]
    replacements += [(str(dataset.resolve()), "<dataset>"), (str(REPO_DIR), "<jev>")]
    checkout = (summary.get("dt") or {}).get("checkout")
    if checkout:
        replacements.append((str(checkout), "<DT>"))
    replacements.append((str(Path.home()), "~"))
    replacements.sort(key=lambda pair: -len(pair[0]))

    def clean(text):
        for old, new in replacements:
            text = text.replace(old, new).replace(old.replace("\\", "/"), new)
        return text

    if target.exists():
        shutil.rmtree(target)
    (target / "handoff").mkdir(parents=True)
    files = ["improvements.md", "README.md", "dataset.json", "registry.json", "issues.jsonl", "improvements.jsonl",
             "history.jsonl", "code_files.csv", "copy_problems.csv", "copy_terms.csv", "ui_unseen.csv"]
    for name in files:
        if (dataset / name).exists():
            (target / name).write_text(clean((dataset / name).read_text(encoding="utf-8")), encoding="utf-8")
    handoff = dataset / "handoff"
    for source in sorted(handoff.rglob("*")) if handoff.exists() else []:
        if source.is_dir():
            continue
        relative = source.relative_to(handoff)
        destination = target / "handoff" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() == ".png":
            number = re.search(r"-(\d+)\.png$", source.name)
            if number and int(number.group(1)) > max_screenshots:
                continue
            shutil.copyfile(source, destination)
        else:
            destination.write_text(clean(source.read_text(encoding="utf-8")), encoding="utf-8")
    for brief in (target / "handoff" / "issues").glob("*.md"):
        text = brief.read_text(encoding="utf-8")
        kept = [line for line in text.splitlines()
                if not re.match(r"!\[screenshot\]\(\.\./evidence/.+-(\d+)\.png\)", line)
                or int(re.search(r"-(\d+)\.png", line).group(1)) <= max_screenshots]
        brief.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return target


def build(out_dir=None, roots=None, checkout=None, handoff=True, quiet=False):
    return DatasetBuilder(out_dir=out_dir, roots=roots, checkout=checkout, handoff=handoff, quiet=quiet).build()
