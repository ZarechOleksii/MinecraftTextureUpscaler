import importlib.metadata

import pytest

from tests import golden_cases as g

EXPECTED = g.load_expected()


def _recorded_environment() -> str:
    import json

    env = json.loads(g.EXPECTED_FILE.read_text(encoding="utf-8"))["environment"]
    now = {name: importlib.metadata.version(name) for name in env}
    return f"recorded with {env}, running with {now}"


def _case(key: str) -> object:
    return pytest.param(key, id=key, marks=() if g.is_fast(key) else pytest.mark.slow)


def test_case_list_matches_the_recorded_cases() -> None:
    assert set(g.all_case_keys()) == set(EXPECTED)


@pytest.mark.parametrize("key", [_case(k) for k in g.all_case_keys() if k not in g.CT_KEYS])
def test_upscale_matches_recorded_output(key: str) -> None:
    assert g.compute_case(key) == EXPECTED[key], _recorded_environment()


def test_connected_texture_sheet_matches_recorded_output() -> None:
    assert g.compute_ct() == {k: EXPECTED[k] for k in g.CT_KEYS}, _recorded_environment()
