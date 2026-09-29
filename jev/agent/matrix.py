"""Run several testers (models x missions x personas) in parallel and merge their findings."""

import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from ..config import resolve_display, runs_dir
from ..findings import cluster, load_run_findings, render_markdown
from .openrouter import OpenRouter
from .runner import QARun, RunConfig, slug


def run_matrix(base, models, missions, personas, parallel=2, out_dir=None):
    if parallel > 1 and resolve_display((base.app or {}).get("display")) == "window":
        # Each app takes the focus before every action; several on one screen would disturb each other.
        print("Window mode: running the testers one at a time so their windows do not take focus from each "
              "other (use --headless to run them in parallel).", flush=True)
        parallel = 1
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = Path(out_dir) if out_dir else runs_dir() / f"matrix-{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    combos = [(model, mission, persona) for mission in missions for persona in personas for model in models]
    (root / "plan.json").write_text(json.dumps({"models": models, "missions": missions, "personas": personas,
                                                "parallel": parallel, "base": base.__dict__}, indent=2, default=str),
                                    encoding="utf-8")
    client = OpenRouter()
    results = []

    def one(model, mission, persona):
        label = f"{slug(model)}__{slug(mission)}__{slug(persona)}"
        config = replace(base, model=model, mission=mission, persona=persona, out_dir=str(root), label=label)
        try:
            return QARun(config, client=client).execute()
        except Exception as error:  # noqa: BLE001 - one failed run must not stop the others
            return {"model": model, "mission": mission, "persona": persona, "error": repr(error),
                    "traceback": traceback.format_exc(), "run_dir": str(root / label)}

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = [pool.submit(one, *combo) for combo in combos]
        for future in as_completed(futures):
            results.append(future.result())
    write_summary(root, results)
    return root, results


def write_summary(root, results):
    root = Path(root)
    findings = []
    for run in sorted(root.iterdir()):
        if run.is_dir() and (run / "findings.jsonl").exists():
            findings.extend(load_run_findings(run / "findings.jsonl"))
    rows = ["| Run | Model | Mission | Persona | Stop reason | Calls | Findings | Cost |", "|---|---|---|---|---|---|---|---|"]
    for result in sorted(results, key=lambda item: (item.get("mission", ""), item.get("model", ""))):
        usage = result.get("usage") or {}
        run_name = Path(result.get("run_dir", "")).name
        rows.append(f"| [{run_name}]({run_name}/report.md) | `{result.get('model')}` | {result.get('mission')} | "
                    f"{result.get('persona')} | {result.get('stop_reason') or result.get('error', '')[:80]} | "
                    f"{result.get('tool_calls', '-')} | {result.get('findings', '-')} | ${float(usage.get('cost') or 0):.4f} |")
    by_model = {}
    for group in cluster(findings):
        for model in {item.get("model") for item in group if item.get("source") != "harness"}:
            by_model[model] = by_model.get(model, 0) + 1
    model_lines = [f"- `{model}`: {count} distinct issue(s) reported" for model, count in sorted(by_model.items(), key=lambda kv: -kv[1])]
    intro = "\n".join(["## Runs", "", *rows, "", "## Distinct issues found per model", "",
                       *(model_lines or ["- none"]), "", "## All findings (merged across runs)"])
    report = render_markdown(findings, title="Jev QA matrix summary", intro=intro, base_dir=root)
    (root / "summary.md").write_text(report, encoding="utf-8")
    (root / "summary.json").write_text(json.dumps({"runs": results, "distinct_issues": len(cluster(findings)),
                                                   "findings": findings}, indent=2, default=str), encoding="utf-8")
    return root / "summary.md"
