import importlib.metadata
import json

from tests import golden_cases as g


def main() -> None:
    cases = {k: g.compute_case(k) for k in g.all_case_keys() if k not in g.CT_KEYS}
    cases.update(g.compute_ct())
    env = {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "pillow")}
    text = json.dumps({"environment": env, "cases": cases}, indent=1, sort_keys=True) + "\n"
    g.EXPECTED_FILE.write_text(text, encoding="utf-8")
    print(len(cases), "cases written to", g.EXPECTED_FILE)


if __name__ == "__main__":
    main()
