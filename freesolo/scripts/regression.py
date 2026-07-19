"""Runs a deployed adapter against every held-out example (examples/test.jsonl)
plus the fixed demo case, using response_format (structured/guided JSON output)
via the OpenAI-compatible serving endpoint -- NOT `flash chat`, which doesn't
expose response_format and is what caused the repetition-loop failures.

Every variable-length array field must be bounded (minItems/maxItems) in the
schema below, or the model loops indefinitely in whichever field is left
unconstrained -- this was the actual root cause, confirmed empirically.

Usage: python3 scripts/regression.py <run_id> [--full]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract_checks import check_structure
from response_schema import RESPONSE_SCHEMA

ENDPOINT = "https://clado-ai--freesolo-lora-serving.modal.run/v1/chat/completions"


def get_api_key():
    key = os.environ.get("FREESOLO_API_KEY") or os.environ.get("FSLO_KEY")
    if key:
        return key
    config_path = Path.home() / ".flash" / "config.json"
    return json.loads(config_path.read_text())["api_key"]


def load_system_prompt():
    path = Path("system_prompt.txt")
    if path.exists():
        return path.read_text().strip()
    import re
    src = Path("environment.py").read_text()
    match = re.search(r'SYSTEM_PROMPT = """(.*?)"""', src, re.S)
    if match:
        return match.group(1)
    raise FileNotFoundError("system_prompt.txt not found and environment.py has no inline SYSTEM_PROMPT")


def load_cases():
    cases = [("demo_case", json.load(open("examples/demo_case.json")))]
    with open("examples/test.jsonl") as f:
        for line in f:
            row = json.loads(line)
            cases.append((row["category"], row["input"]))
    return cases


def query(run_id, system_prompt, input_data, api_key):
    schema = json.loads(json.dumps(RESPONSE_SCHEMA))  # deep copy
    schema["properties"]["possible_next_step"]["enum"] = input_data["permitted_next_steps"]
    payload = {
        "model": run_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(input_data)},
        ],
        "max_tokens": 700,
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "rehabtrace_summary", "schema": schema, "strict": True},
        },
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:300]}"
    content = result["choices"][0]["message"]["content"]
    finish_reason = result["choices"][0]["finish_reason"]
    if finish_reason != "stop":
        return content, f"finish_reason={finish_reason} (did not terminate naturally)"
    return content, None


def main():
    run_id = sys.argv[1]
    show_full = "--full" in sys.argv
    system_prompt = load_system_prompt()
    api_key = get_api_key()
    cases = load_cases()

    Path("examples/regression_responses").mkdir(exist_ok=True)

    per_category = {}
    failures_shown = 0
    for i, (category, input_data) in enumerate(cases):
        content, query_error = query(run_id, system_prompt, input_data, api_key)
        per_category.setdefault(category, [0, 0])
        per_category[category][0] += 1

        if content is None:
            ok = False
            results = [("http_request", False, query_error)]
        else:
            try:
                output_data = json.loads(content)
                results = check_structure(input_data, output_data)
                if query_error:
                    results.append(("finished_naturally", False, query_error))
            except json.JSONDecodeError as e:
                results = [("valid_json", False, str(e))]
            ok = all(r[1] for r in results)

        if ok:
            per_category[category][1] += 1
        if content is not None:
            Path(f"examples/regression_responses/{category}_{i}.txt").write_text(content)
        if not ok and (show_full or failures_shown < 5):
            failures_shown += 1
            print(f"--- FAIL [{category} #{i}] ---")
            for name, r_ok, detail in results:
                if not r_ok:
                    print(f"  [FAIL] {name} -- {detail}")
            if content:
                print(f"  response: {content[:300]}")
            print()

    print("=" * 70)
    total, total_pass = 0, 0
    for category, (count, passed) in sorted(per_category.items()):
        total += count
        total_pass += passed
        print(f"  {category:55} {passed}/{count}")
    print("-" * 70)
    print(f"  {'TOTAL':55} {total_pass}/{total}  ({100*total_pass/total:.1f}%)")


if __name__ == "__main__":
    main()
