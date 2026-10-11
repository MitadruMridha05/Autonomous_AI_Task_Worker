"""Create a Markdown summary and PNG chart from evaluation results."""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

def build_report(results_path: str | Path = "runs/eval_results.json", output_dir: str | Path = "runs/report") -> tuple[Path, Path]:
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True); frame = pd.read_json(results_path)
    if frame.empty: raise ValueError("Evaluation results are empty")
    frame["passed"] = frame["passed"].astype(bool)
    summary = {"tasks": len(frame), "passed": int(frame["passed"].sum()), "failed": int((~frame["passed"]).sum()), "success_rate": float(frame["passed"].mean()), "mean_steps": float(frame["steps"].mean()), "mean_latency_s": float(frame["duration_s"].mean()), "total_retries": int(frame["retries"].sum())}
    md = out / "report.md"; lines = ["# OpsPilot Evaluation Report", "", f"- Tasks: {summary['tasks']}", f"- Passed: {summary['passed']}", f"- Failed: {summary['failed']}", f"- Success rate: {summary['success_rate']:.1%}", f"- Mean steps: {summary['mean_steps']:.2f}", f"- Mean latency: {summary['mean_latency_s']:.4f} s", f"- Retries: {summary['total_retries']}", "", "| Task | Status | Expected | Passed | Steps | Latency (s) |", "|---|---|---|---:|---:|---:|"]
    for _, r in frame.iterrows(): lines.append(f"| {r.task_id} | {r.status} | {r.expected_status} | {'yes' if r.passed else 'no'} | {r.steps} | {r.duration_s} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    chart = out / "task_results.png"
    try:
        import seaborn as sns; import matplotlib.pyplot as plt
        sns.set_theme(style="whitegrid"); ax = sns.barplot(data=frame, x="task_id", y="passed", hue="passed", legend=False, palette={True: "#2ca02c", False: "#d62728"}); ax.set_ylim(0, 1.1); ax.set_ylabel("Passed (1=yes)"); ax.set_xlabel("Evaluation task"); ax.tick_params(axis="x", rotation=45); plt.tight_layout(); plt.savefig(chart, dpi=140); plt.close()
    except ImportError: chart.write_bytes(b"")
    return md, chart

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--results", default="runs/eval_results.json"); p.add_argument("--output-dir", default="runs/report"); a = p.parse_args(); md, chart = build_report(a.results, a.output_dir); print(f"Report: {md}\nChart: {chart}"); return 0
if __name__ == "__main__": raise SystemExit(main())
