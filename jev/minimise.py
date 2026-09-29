"""Shrink a replay to the few steps that still trigger a problem (delta debugging).

Crawler and tester findings come with a replay of everything that happened before them, often
dozens of steps. For a problem the harness recognises by signature (an exception, a crash, a
freeze, leaked error text), this replays shorter and shorter versions and keeps any version
that still produces the same signature. The result is a short repro for DT's developers and a
fast regression check for ``jev verify``.
"""

import json
import math
import time
from pathlib import Path

from .scenarios import describe_step, read_findings, run_scenario

MINIMISABLE = ("exception@", "crash@", "hang@", "stall@", "text@", "qt@")


def minimisable(issue):
    return any(str(signature).startswith(MINIMISABLE) for signature in issue.get("signatures") or [])


class Minimiser:
    def __init__(self, scenario, signatures, out_dir, *, max_minutes=4.0, app_overrides=None, log=None):
        self.scenario = dict(scenario)
        self.signatures = {str(item) for item in signatures if str(item).startswith(MINIMISABLE)}
        self.out_dir = Path(out_dir)
        self.deadline = time.time() + max_minutes * 60
        self.app_overrides = app_overrides
        self.log = log or (lambda message: None)
        self.replays = 0
        self.cache = {}

    def reproduces(self, steps):
        key = json.dumps(steps, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        self.replays += 1
        trial = dict(self.scenario, steps=steps, continue_on_error=True)
        trial.pop("issue", None)  # trial runs must not be filed against the issue
        run_dir = self.out_dir / f"try-{self.replays:03d}"
        run_scenario(trial, run_dir, app_overrides=self.app_overrides, quiet=True)
        found = any(finding.get("signature") in self.signatures for finding in read_findings(run_dir))
        self.log(f"  replay {self.replays}: {len(steps)} steps -> {'reproduced' if found else 'not reproduced'}")
        self.cache[key] = found
        return found

    def run(self):
        steps = [step for step in self.scenario.get("steps", []) if step.get("do")]
        original = len(steps)
        if not self.signatures:
            return {"reproduced": False, "reason": "no signature to look for", "original": original, "steps": steps}
        if not self.reproduces(steps):
            return {"reproduced": False, "reason": "the full replay did not reproduce it (timing or state dependent)",
                    "original": original, "steps": steps, "replays": self.replays}
        chunks = 2
        while len(steps) >= 2 and time.time() < self.deadline:
            size = math.ceil(len(steps) / chunks)
            reduced = False
            for start in range(0, len(steps), size):
                if time.time() >= self.deadline:
                    break
                candidate = steps[:start] + steps[start + size:]
                if candidate and self.reproduces(candidate):
                    steps, chunks, reduced = candidate, max(chunks - 1, 2), True
                    break
            if not reduced:
                if chunks >= len(steps):
                    break
                chunks = min(len(steps), chunks * 2)
        return {"reproduced": True, "original": original, "steps": steps, "replays": self.replays,
                "complete": time.time() < self.deadline}


def minimise_issue(registry, issue_id, out_dir, *, scenarios_dir, max_minutes=4.0, app_overrides=None, log=print):
    """Minimise one issue's replay and store the short version as its scenario."""
    from .config import dt_version
    from .scenarios import load_scenario

    issue = registry.get(issue_id)
    if issue is None:
        raise KeyError(f"No issue {issue_id}")
    if not issue.get("scenario"):
        raise ValueError(f"{issue['id']} has no replay yet; run `jev dataset build` first")
    if not minimisable(issue):
        raise ValueError(f"{issue['id']} is not recognised by a harness signature, so it cannot be minimised "
                         "automatically")
    scenario = load_scenario(issue["scenario"])
    log(f"Minimising {issue['id']} ({len(scenario.get('steps', []))} steps): {issue.get('title')}")
    result = Minimiser(scenario, issue.get("signatures") or [], Path(out_dir) / issue["id"], max_minutes=max_minutes,
                       app_overrides=app_overrides, log=log).run()
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": result["original"], "to": len(result["steps"]),
             "replays": result.get("replays", 0), "reproduced": result["reproduced"],
             "commit": dt_version().get("commit", "")}
    issue["minimised"] = entry
    if result["reproduced"]:
        minimal = {key: value for key, value in scenario.items() if key not in ("_path", "steps")}
        minimal.update(name=f"replay-{issue['id'].lower()}", steps=result["steps"],
                       minimised_from=result["original"])
        minimal["title"] = f"Minimal replay of {issue['id']}: {issue.get('title', '')}"[:200]
        scenarios_dir = Path(scenarios_dir)
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        path = scenarios_dir / f"{issue['id']}.json"
        path.write_text(json.dumps(minimal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        issue["scenario"] = str(path)
        app = minimal.get("app") or {}
        setup = f"Start DT with {', '.join(f'{key}={value}' for key, value in app.items()) or 'defaults'}"
        issue["minimal_steps"] = [setup] + [describe_step(step) for step in result["steps"]]
        log(f"  {issue['id']}: {result['original']} -> {len(result['steps'])} steps in {result.get('replays')} replays")
    else:
        log(f"  {issue['id']}: {result.get('reason')}")
    return result
