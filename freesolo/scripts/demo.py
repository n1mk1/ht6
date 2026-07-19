#!/usr/bin/env python3
"""Local RehabTrace demo: build the FreeSolo prompt and validate the gold response.

This exercises the same prompt-building + deterministic validation path used after
deployment, without calling a paid model.

Usage:
  python3 scripts/demo.py
  python3 scripts/demo.py --response examples/demo_case_gold_response.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contract_checks import check_response_text, print_results  # noqa: E402


def build_prompt_messages(input_data: dict) -> list[dict]:
    """Mirror environment.RehabTraceEnv.build_prompt_messages without freesolo import."""
    system_prompt = (ROOT / "system_prompt.txt").read_text().strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(input_data)},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="RehabTrace local demo")
    parser.add_argument(
        "--input",
        default=str(ROOT / "examples" / "demo_case.json"),
        help="Path to demo input JSON",
    )
    parser.add_argument(
        "--response",
        default=str(ROOT / "examples" / "demo_case_gold_response.txt"),
        help="Path to response text to validate",
    )
    args = parser.parse_args()

    input_data = json.loads(Path(args.input).read_text())
    response_path = Path(args.response)
    if not response_path.exists():
        # Fall back to regenerating gold from generate_dataset constants.
        sys.path.insert(0, str(ROOT / "scripts"))
        from generate_dataset import DEMO_OUTPUT  # noqa: WPS433

        response_path.write_text(json.dumps(DEMO_OUTPUT, indent=2) + "\n")
        print(f"wrote gold response -> {response_path}")

    response_text = response_path.read_text()
    messages = build_prompt_messages(input_data)

    print("=== prompt messages ===")
    print(f"system chars: {len(messages[0]['content'])}")
    print(f"user preview: {messages[1]['content'][:180]}...")
    print()

    results = check_response_text(input_data, response_text)
    ok = print_results(str(response_path), results)
    print("\nOVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
