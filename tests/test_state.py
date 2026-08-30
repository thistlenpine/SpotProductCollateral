import json
import os
from spot_product_collateral.state import State


def test_load_missing_file_returns_defaults(tmp_path):
    path = str(tmp_path / "STATE.json")
    state = State.load(path)
    assert state.consecutive_failures == 0
    assert state.last_run is None
    assert state.last_run_id is None


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "STATE.json")
    state = State(consecutive_failures=2, last_run="2026-08-29T00:00:00Z", last_run_id="2026-08-29")
    state.save(path)
    loaded = State.load(path)
    assert loaded.consecutive_failures == 2
    assert loaded.last_run == "2026-08-29T00:00:00Z"
    assert loaded.last_run_id == "2026-08-29"
    with open(path) as f:
        assert json.load(f)["consecutive_failures"] == 2
