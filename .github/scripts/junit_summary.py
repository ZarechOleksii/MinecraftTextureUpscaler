import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SLOWEST = 5


def main(argv: list[str]) -> int:
    root = ET.parse(Path(argv[1])).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    seconds = sum(float(s.get("time", 0)) for s in suites)
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    verdict = "passed" if not (totals["failures"] or totals["errors"]) else "FAILED"
    print(f"## Test results: {verdict}\n")
    print("| passed | failed | errors | skipped | total | time |")
    print("|---:|---:|---:|---:|---:|---:|")
    print(
        f"| {passed} | {totals['failures']} | {totals['errors']} | {totals['skipped']} | {totals['tests']} "
        f"| {seconds:.0f}s |\n"
    )
    cases = list(root.iter("testcase"))
    broken = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    if broken:
        print("### Failed tests\n")
        for case in broken:
            problem = case.find("failure") if case.find("failure") is not None else case.find("error")
            message = (problem.get("message") or "").splitlines()[0] if problem is not None else ""
            print(f"- `{case.get('classname')}::{case.get('name')}` {message}")
        print()
    slow = sorted(cases, key=lambda c: float(c.get("time", 0)), reverse=True)[:SLOWEST]
    print(f"<details><summary>{SLOWEST} slowest tests</summary>\n")
    for case in slow:
        print(f"- {float(case.get('time', 0)):.1f}s `{case.get('classname')}::{case.get('name')}`")
    print("\n</details>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
