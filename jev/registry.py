"""The issue registry: one stable JEV-#### record per distinct problem, across every run.

Findings come from many places (harness detections, scripted scenarios, the crawler, AI
testers). The registry merges them into issues that keep their ID from build to build, carry
their status (open, fixed, regressed, ...) with a history tied to DT commits, and point at the
scenario that verifies them. It is a plain JSON file so it can be shared or committed.
"""

import difflib
import json
import os
import re
import time
from pathlib import Path

from .config import DATA_DIR, runs_dir
from .findings import SEVERITY_RANK, normalise_title

STATUSES = ("open", "regressed", "fixed", "wontfix", "by-design", "known-limitation", "harness-artefact", "duplicate")
ACTIVE = ("open", "regressed")
CLASSIFICATIONS = ("confirmed bug", "ux issue", "by design", "known limitation", "harness artefact", "unconfirmed")
HARNESS_KINDS = ("exception", "crash", "freeze", "performance")


def dataset_dir():
    configured = os.environ.get("JEV_DATASET_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return runs_dir().parent / "dataset"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def builtin_issues():
    """Known issues shipped with Jev, each verified by a regression scenario."""
    found = []
    for path in sorted((DATA_DIR / "scenarios" / "regressions").glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        issue = scenario.get("issue") or {}
        if issue.get("id"):
            found.append((issue, scenario, f"regressions/{path.stem}"))
    return found


def sweep_signatures():
    """Soft checks in the sweep that watch a known issue: issue id -> finding signatures."""
    found = {}
    for path in sorted((DATA_DIR / "scenarios").rglob("*.json")):
        try:
            scenario = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = scenario.get("name", path.stem)
        for index, step in enumerate(scenario.get("steps") or [], 1):
            on_fail = step.get("on_fail") or {}
            if on_fail.get("issue"):
                found.setdefault(on_fail["issue"], []).append(f"scenario@{name}#{on_fail.get('key') or index}")
    return found


class Registry:
    def __init__(self, path=None):
        self.path = Path(path) if path else dataset_dir() / "registry.json"
        self.issues = {}
        self.assignments = {}  # "run-id#F001" -> issue id, so rebuilding never re-matches a finding
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.issues = data.get("issues", {})
            self.assignments = data.get("assignments", {})
        self.seed_builtin()

    # ----- persistence ----------------------------------------------------------------
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = dict(sorted(self.issues.items(), key=lambda item: issue_number(item[0])))
        payload = {"format": 1, "updated": now(), "issues": ordered, "assignments": self.assignments}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def next_id(self):
        numbers = [issue_number(key) for key in self.issues] or [0]
        return f"JEV-{max(max(numbers) + 1, 101 if max(numbers) < 100 else 0):04d}"

    def seed_builtin(self):
        step_signatures = sweep_signatures()
        for block, scenario, reference in builtin_issues():
            issue = self.issues.get(block["id"])
            if issue is None:
                issue = {"id": block["id"], "status": "open", "classification": "confirmed bug",
                         "confidence": "confirmed", "origin": "built-in regression scenario", "created": now(),
                         "status_history": [{"time": now(), "status": "open", "by": "built-in",
                                             "note": "Reproduced when the scenario was written."}],
                         "verifications": [], "signatures": [], "first_seen": "", "last_seen": ""}
                self.issues[block["id"]] = issue
            # Scenario text is authoritative for these fields; status and history belong to the registry.
            for key in ("title", "severity", "category", "expected", "actual", "classification"):
                if block.get(key):
                    issue[key] = block[key]
            issue["suspected"] = list(block.get("suspected") or [])
            if block.get("dt_test"):
                issue["dt_test"] = block["dt_test"]
            issue["scenario"] = reference
            issue["verify_kind"] = "expectations"
            names = set(issue.get("scenario_names") or [])
            names.add(scenario["name"])
            issue["scenario_names"] = sorted(names)
            # Harness detections of the same problem (from crawls, sweeps or testers) join this issue too.
            for signature in step_signatures.get(block["id"], []) + list(block.get("signatures") or []):
                if signature not in issue["signatures"]:
                    issue["signatures"].append(signature)

    # ----- matching findings ----------------------------------------------------------
    def match(self, finding, reference=None):
        """The issue a finding belongs to, or None when it describes something new."""
        if reference and self.assignments.get(reference) in self.issues:
            return self.follow(self.issues[self.assignments[reference]])
        wanted = finding.get("issue_id")
        if wanted and wanted in self.issues:
            return self.follow(self.issues[wanted])
        signature = finding.get("signature")
        source = str(finding.get("source") or "")
        if source.startswith("scenario:"):
            name = source.split(":", 1)[1]
            for issue in self.issues.values():
                if name in (issue.get("scenario_names") or []):
                    return self.follow(issue)
        if signature:
            for issue in self.issues.values():
                if signature in (issue.get("signatures") or []):
                    return self.follow(issue)
        if source == "harness" or source.startswith("scenario:"):
            return None  # these carry exact signatures; similar wording is not the same defect
        title = normalise_title(finding.get("title", ""))
        target = ((finding.get("evidence") or {}).get("target") or {}).get("key") if isinstance(
            finding.get("evidence"), dict) else None
        best, best_score = None, 0.0
        for issue in self.issues.values():
            if issue.get("origin") == "harness":
                continue
            score = difflib.SequenceMatcher(None, title, normalise_title(issue.get("title", ""))).ratio()
            for alias in issue.get("aliases", [])[:20]:
                score = max(score, difflib.SequenceMatcher(None, title, normalise_title(alias)).ratio())
            same_category = finding.get("category") == issue.get("category")
            same_target = target and target in (issue.get("targets") or [])
            if (score >= 0.72 and same_category) or (same_target and score >= 0.5):
                if score > best_score:
                    best, best_score = issue, score
        return self.follow(best) if best else None

    def follow(self, issue):
        seen = set()
        while issue and issue.get("status") == "duplicate" and issue.get("duplicate_of") in self.issues:
            if issue["id"] in seen:
                break
            seen.add(issue["id"])
            issue = self.issues[issue["duplicate_of"]]
        return issue

    def create(self, finding):
        source = str(finding.get("source") or "agent")
        harness = source == "harness"
        scripted = source.startswith("scenario:")
        if source == "dt-tests":
            return self.create_test_issue(finding)
        # A crash or exception is a bug by definition. A failed scripted step is either a DT bug
        # or a scenario that no longer matches DT, so it waits for triage like tester reports.
        confirmed = harness and finding.get("category") in ("exception", "crash", "freeze")
        issue = {"id": self.next_id(), "title": finding.get("title", "Untitled issue"),
                 "severity": finding.get("severity", "medium"), "category": finding.get("category", "other"),
                 "status": "open",
                 "classification": "confirmed bug" if confirmed else "unconfirmed",
                 "confidence": "confirmed" if confirmed else ("likely" if scripted else
                                                             finding.get("confidence", "likely")),
                 "origin": "harness" if harness else ("scenario" if scripted else "tester"),
                 "created": now(), "expected": finding.get("expected", ""), "actual": finding.get("actual", ""),
                 "signatures": [finding["signature"]] if finding.get("signature") else [],
                 # Harness and scenario findings carry exact signatures a replay can look for again.
                 "verify_kind": "signature" if (harness or scripted) else "manual",
                 "status_history": [{"time": now(), "status": "open", "by": "dataset build",
                                     "note": f"First reported by {finding.get('model') or source}."}],
                 "verifications": [], "suspected": [], "first_seen": "", "last_seen": ""}
        self.issues[issue["id"]] = issue
        return issue

    def create_test_issue(self, finding):
        issue = {"id": self.next_id(), "title": finding.get("title", "DT test fails"), "severity": "high",
                 "category": finding.get("category", "functional"), "status": "open", "classification": "confirmed bug",
                 "confidence": "confirmed", "origin": "dt-tests", "created": now(),
                 "expected": finding.get("expected", ""), "actual": finding.get("actual", ""),
                 "signatures": [finding["signature"]] if finding.get("signature") else [], "verify_kind": "manual",
                 "status_history": [{"time": now(), "status": "open", "by": "dt-tests",
                                     "note": "DT's own test suite failed during a Jev campaign."}],
                 "verifications": [], "suspected": [], "first_seen": "", "last_seen": ""}
        self.issues[issue["id"]] = issue
        return issue

    def absorb(self, issue, finding, run):
        """Record that a finding is another sighting of an issue."""
        signature = finding.get("signature")
        if signature and signature not in issue.setdefault("signatures", []):
            issue["signatures"].append(signature)
        title = finding.get("title", "")
        if title and title != issue.get("title") and title not in issue.setdefault("aliases", []):
            issue["aliases"] = (issue["aliases"] + [title])[-20:]
        target = ((finding.get("evidence") or {}).get("target") or {}).get("key") if isinstance(
            finding.get("evidence"), dict) else None
        if target and target not in issue.setdefault("targets", []):
            issue["targets"].append(target)
        if SEVERITY_RANK.get(finding.get("severity"), 9) < SEVERITY_RANK.get(issue.get("severity"), 9) and \
                issue.get("origin") != "built-in regression scenario":
            issue["severity"] = finding["severity"]
        seen = finding.get("time") or run.get("started_at") or ""
        if seen and (not issue.get("first_seen") or seen < issue["first_seen"]):
            issue["first_seen"] = seen
        if seen and seen > (issue.get("last_seen") or ""):
            issue["last_seen"] = seen
        commit = (run.get("dt_commit") or "")[:12]
        if commit and commit not in issue.setdefault("dt_commits", []):
            issue["dt_commits"].append(commit)
        if issue.get("status") == "fixed" and seen and seen > self.status_time(issue) and \
                commit and commit != (self.last_fix(issue) or {}).get("commit", "")[:12]:
            self.set_status(issue["id"], "regressed", by="dataset build",
                            note=f"Seen again in run {run.get('id')} on DT {commit}.", commit=commit)

    # ----- status -----------------------------------------------------------------------
    def set_status(self, issue_id, status, *, by="user", note="", commit="", **extra):
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}; use one of {', '.join(STATUSES)}")
        issue = self.issues[issue_id]
        issue["status"] = status
        entry = {"time": now(), "status": status, "by": by}
        if note:
            entry["note"] = note
        if commit:
            entry["commit"] = commit
        entry.update({key: value for key, value in extra.items() if value})
        issue.setdefault("status_history", []).append(entry)
        return issue

    @staticmethod
    def status_time(issue):
        history = issue.get("status_history") or []
        return history[-1]["time"] if history else ""

    @staticmethod
    def last_fix(issue):
        for entry in reversed(issue.get("status_history") or []):
            if entry.get("status") == "fixed":
                return entry
        return None

    def get(self, issue_id):
        key = issue_id.upper()
        if re.fullmatch(r"\d+", key):
            key = f"JEV-{int(key):04d}"
        return self.issues.get(key)


def issue_number(issue_id):
    match = re.search(r"(\d+)$", str(issue_id))
    return int(match.group(1)) if match else 0
