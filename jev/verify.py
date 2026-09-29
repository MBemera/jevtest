"""Replay the scenario behind each known issue against the DT checkout under test.

A passing replay means the problem no longer happens: the issue is marked fixed, tied to the
DT commit. A replay that shows the problem again marks a fixed issue regressed. A replay that
cannot get through its steps (DT changed its screens) is inconclusive and changes nothing.
Point JEV_DT_PATH at a DT branch to check a fix before it is merged.
"""

import json
import time
from pathlib import Path

from .config import dt_version, runs_dir
from .registry import Registry
from .scenarios import load_scenario, read_findings, run_scenario

VERIFIABLE = ("expectations", "signature")


def select(registry, issue_ids=None, statuses=("open", "regressed", "fixed"), include_manual=False):
    if issue_ids:
        chosen = []
        for issue_id in issue_ids:
            issue = registry.get(issue_id)
            if issue is None:
                raise KeyError(f"No issue {issue_id} in {registry.path}")
            chosen.append(issue)
        return chosen
    return [issue for issue in registry.issues.values()
            if issue.get("scenario") and issue.get("status") in statuses
            and (include_manual or issue.get("verify_kind") in VERIFIABLE)]


def judge(issue, result, run_dir):
    """reproduced, passed or inconclusive, with a one-line reason."""
    steps = result.steps
    blocked = [step for step in steps if not step["optional"] and (
        not step["tool_ok"] or any(str(problem).startswith("not run") for problem in step["problems"]))]
    if issue.get("verify_kind") == "signature":
        wanted = set(issue.get("signatures") or [])
        seen = [finding for finding in read_findings(run_dir) if finding.get("signature") in wanted]
        if seen:
            return "reproduced", f"{seen[0].get('title')} ({seen[0].get('signature')})"
        if blocked:
            return "inconclusive", f"step {blocked[0]['index']} could not run: {blocked[0]['problems'][:1]}"
        return "passed", "the replay no longer triggers the recorded problem"
    if result.passed:
        return "passed", "every expectation held"
    failures = result.failures()
    if blocked and blocked[0]["index"] <= failures[0]["index"]:
        return "inconclusive", (f"step {blocked[0]['index']} ({blocked[0]['do']}) could not run, so the scenario may "
                                f"need updating: {'; '.join(blocked[0]['problems'][:1])}")
    first = failures[0]
    return "reproduced", f"step {first['index']} ({first['do']}): {'; '.join(first['problems'][:2])}"


def apply(registry, issue, outcome, reason, dt, run_dir):
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": outcome, "reason": reason[:400],
             "commit": dt.get("commit", ""), "branch": dt.get("branch", ""), "dirty": dt.get("dirty"),
             "run": str(run_dir)}
    issue.setdefault("verifications", []).append(entry)
    issue["verifications"] = issue["verifications"][-30:]
    short = (dt.get("commit") or "")[:12] + (" (uncommitted changes)" if dt.get("dirty") else "")
    status = issue.get("status")
    if outcome == "passed" and status in ("open", "regressed"):
        registry.set_status(issue["id"], "fixed", by="jev verify", commit=dt.get("commit", ""),
                            note=f"Replay passed on DT {short}.")
        return "fixed"
    if outcome == "reproduced" and status == "fixed":
        registry.set_status(issue["id"], "regressed", by="jev verify", commit=dt.get("commit", ""),
                            note=f"Replay reproduced the problem on DT {short}: {reason[:200]}")
        return "regressed"
    return status


def verify(issue_ids=None, *, out_dir=None, registry_path=None, app_overrides=None, include_manual=False,
           statuses=("open", "regressed", "fixed"), quiet=False):
    registry = Registry(registry_path) if registry_path else Registry()
    chosen = select(registry, issue_ids, statuses, include_manual)
    out = Path(out_dir) if out_dir else runs_dir() / f"verify-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    dt = dict(dt_version())
    rows = []
    for issue in chosen:
        if not issue.get("scenario"):
            rows.append({"id": issue["id"], "title": issue.get("title"), "result": "skipped",
                         "reason": "no replay scenario yet", "status": issue.get("status")})
            continue
        try:
            scenario = load_scenario(issue["scenario"])
        except (OSError, ValueError) as error:
            rows.append({"id": issue["id"], "title": issue.get("title"), "result": "skipped",
                         "reason": f"scenario not loadable: {error}", "status": issue.get("status")})
            continue
        run_dir = out / f"{issue['id']}-{scenario['name']}"[:120]
        if not quiet:
            print(f"== {issue['id']} {issue.get('title', '')[:90]}", flush=True)
        result = run_scenario(scenario, run_dir, app_overrides=app_overrides, quiet=quiet)
        if issue.get("verify_kind") not in VERIFIABLE:
            outcome, reason = "replayed", "replayed to the reported point; judge the result by eye (manual issue)"
            status = issue.get("status")
        else:
            outcome, reason = judge(issue, result, run_dir)
            status = apply(registry, issue, outcome, reason, dt, run_dir)
        rows.append({"id": issue["id"], "title": issue.get("title"), "result": outcome, "reason": reason,
                     "status": status, "run": str(run_dir), "seconds": result.duration})
        if not quiet:
            print(f"   -> {outcome}: {reason[:160]} (status: {status})", flush=True)
    registry.save()
    write_summary(out, rows, dt)
    return out, rows


def write_summary(out, rows, dt):
    lines = ["# Jev verification", "",
             f"DT `{(dt.get('commit') or 'unknown')[:12]}` on branch `{dt.get('branch') or '?'}`"
             + (" with uncommitted changes" if dt.get("dirty") else "") + f" at {dt.get('path')}", "",
             "| Issue | Result | Status now | Why | Title |", "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | {row['result']} | {row.get('status')} | "
                     f"{str(row.get('reason', '')).replace('|', '/')[:160]} | {str(row.get('title', '')).replace('|', '/')} |")
    counts = {}
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    lines += ["", "**" + ", ".join(f"{count} {result}" for result, count in sorted(counts.items())) + "**"
              if counts else "Nothing to verify."]
    (out / "verify-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "verify-summary.json").write_text(json.dumps({"dt": dt, "results": rows}, indent=2, default=str),
                                             encoding="utf-8")
