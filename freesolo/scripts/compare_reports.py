"""Compare base, SFT, and GRPO regression reports without hiding regressions."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python3 scripts/compare_reports.py <report.json> <report.json> [...]"
        )
    reports = [load(path) for path in sys.argv[1:]]
    names = [report["model"] for report in reports]
    print("metric\t" + "\t".join(names))
    print(
        "full_contract_pass_rate\t"
        + "\t".join(f"{report['pass_rate']:.1%}" for report in reports)
    )
    important = (
        "overall_pattern_correct",
        "observation_directions_correct",
        "numbers_grounded",
        "safe_non_diagnostic_language",
        "next_step_correct",
    )
    for metric in important:
        values = []
        for report in reports:
            result = report["checks"].get(metric, {"passed": 0, "total": 0})
            rate = result["passed"] / result["total"] if result["total"] else 0
            values.append(f"{rate:.1%}")
        print(metric + "\t" + "\t".join(values))


if __name__ == "__main__":
    main()
