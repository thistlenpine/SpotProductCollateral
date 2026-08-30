import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from spot_product_collateral.config import Config
from spot_product_collateral.crawler import TastingProfileResult
from spot_product_collateral.state import State
from spot_product_collateral.upc_lookup import UpcLookupResult


@pytest.fixture
def mock_bottlepos():
    """Mock the bottlepos module to avoid import errors."""
    mock = MagicMock()
    sys.modules["bottlepos"] = mock
    yield mock
    sys.modules.pop("bottlepos", None)


def _paths(tmp_path):
    """Return (state_path, runs_dir) inside tmp_path so no test touches the real repo root."""
    return str(tmp_path / "STATE.json"), str(tmp_path / "runs")


def test_main_halts_when_consecutive_failures_exceeds_threshold(mock_bottlepos, tmp_path):
    """Test that main() exits immediately when consecutive_failures >= 10."""
    state_path, runs_dir = _paths(tmp_path)
    mock_state = State(consecutive_failures=10, last_run=None, last_run_id=None)

    with patch("spot_product_collateral.state.State.load", return_value=mock_state):
        # Patch Config.from_env to verify it's never called
        with patch("spot_product_collateral.config.Config.from_env") as mock_config_from_env:
            import main

            with pytest.raises(SystemExit) as exc_info:
                main.main(state_path=state_path, runs_dir=runs_dir)

            assert exc_info.value.code == 1
            mock_config_from_env.assert_not_called()

    assert not os.path.exists(runs_dir)


def test_main_halts_when_consecutive_failures_exceeds_threshold_writes_to_stderr(
    mock_bottlepos, tmp_path, capsys
):
    """Test that main() writes a clear message to stderr when halting."""
    state_path, runs_dir = _paths(tmp_path)
    mock_state = State(consecutive_failures=10, last_run=None, last_run_id=None)

    with patch("spot_product_collateral.state.State.load", return_value=mock_state):
        with patch("spot_product_collateral.config.Config.from_env"):
            import main

            with pytest.raises(SystemExit):
                main.main(state_path=state_path, runs_dir=runs_dir)

            captured = capsys.readouterr()
            assert "Halting: consecutive_failures=10 >= 10" in captured.err
            assert "HUMAN-GATES.md" in captured.err
            assert "a human must diagnose and reset STATE.json" in captured.err


def test_main_continues_when_consecutive_failures_below_threshold(mock_bottlepos, tmp_path):
    """Test that main() continues to Config.from_env() when consecutive_failures < 10."""
    state_path, runs_dir = _paths(tmp_path)
    mock_state = State(consecutive_failures=5, last_run=None, last_run_id=None)

    with patch("spot_product_collateral.state.State.load", return_value=mock_state):
        with patch("spot_product_collateral.config.Config.from_env") as mock_config:
            # NOTE: main.py does `from bottlepos import BottlePOSClient` and
            # `from spot_product_collateral.run import run_once`, so the patch
            # target must be main's own namespace, not the source module.
            with patch("main.BottlePOSClient") as mock_bottlepos_class:
                with patch("main.run_once") as mock_run_once:
                    mock_config.return_value = MagicMock()
                    mock_bottlepos_instance = MagicMock()
                    mock_bottlepos_class.return_value = mock_bottlepos_instance
                    mock_bottlepos_instance.list_items.return_value = []
                    mock_run_once.return_value = {
                        "run_id": "2026-08-29",
                        "items": [],
                        "errors": [],
                        "verified": True,
                    }

                    import main

                    main.main(state_path=state_path, runs_dir=runs_dir)

                    mock_config.assert_called_once()
                    mock_run_once.assert_called_once()
                    # run_once was handed the tmp-path state file, not the repo root's
                    assert mock_run_once.call_args[0][2] == state_path


def test_main_uses_default_paths_relative_to_cwd(mock_bottlepos, tmp_path):
    """main() defaults to STATE.json / runs relative to the CWD when no args are given."""
    state_file = tmp_path / "STATE.json"
    state_file.write_text('{"consecutive_failures": 0, "last_run": null, "last_run_id": null}')

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        with patch("spot_product_collateral.config.Config.from_env") as mock_config:
            with patch("main.BottlePOSClient") as mock_bottlepos_class:
                with patch("main.run_once") as mock_run_once:
                    mock_config.return_value = MagicMock()
                    mock_bottlepos_instance = MagicMock()
                    mock_bottlepos_class.return_value = mock_bottlepos_instance
                    mock_bottlepos_instance.list_items.return_value = []
                    mock_run_once.return_value = {
                        "run_id": "2026-08-29",
                        "items": [],
                        "errors": [],
                        "verified": True,
                    }

                    import main

                    main.main()

                    mock_config.assert_called_once()
                    assert mock_run_once.call_args[0][2] == "STATE.json"
    finally:
        os.chdir(original_cwd)

    # The defaults resolved inside tmp_path, never the repo root.
    assert (tmp_path / "runs").is_dir()


def test_main_exits_nonzero_when_manifest_not_verified(mock_bottlepos, tmp_path, capsys):
    """A run whose manifest fails verification must surface a non-zero exit status."""
    state_path, runs_dir = _paths(tmp_path)
    State(consecutive_failures=3, last_run=None, last_run_id=None).save(state_path)

    with patch("spot_product_collateral.config.Config.from_env") as mock_config:
        with patch("main.BottlePOSClient") as mock_bottlepos_class:
            with patch("main.run_once") as mock_run_once:
                mock_config.return_value = MagicMock()
                mock_bottlepos_class.return_value = MagicMock(list_items=lambda: [])
                mock_run_once.return_value = {
                    "run_id": "2026-08-29",
                    "items": [],
                    "errors": [{"upc": None, "error": "scan failed: boom"}],
                    "verified": False,
                }

                import main

                with pytest.raises(SystemExit) as exc_info:
                    main.main(state_path=state_path, runs_dir=runs_dir)

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "2026-08-29" in captured.err
    assert "verification FAILED" in captured.err


def test_main_end_to_end_writes_real_record_to_pocketbase(mock_bottlepos, pb_server, tmp_path):
    """End-to-end: main() -> real run_once -> real scan/enrichment/pocketbase against the mock server.

    Only the three genuinely-external services are faked (BottlePOS, the UPC
    lookup HTTP call, and the Anthropic-backed crawler).
    """
    state_path, runs_dir = _paths(tmp_path)

    config = Config(
        bottle_url="http://bottlepos.example",
        bottle_user="user",
        bottle_pass="pass",
        pocketbase_url=pb_server.base_url,
        pb_superuser_email="admin@example.com",
        pb_superuser_password="hunter2",
        anthropic_api_key="fake-key",
    )

    fake_items = [
        SimpleNamespace(
            code="012345678905",
            name="Example Wine",
            description="A red wine",
            category_name="RED WINE",
            id=1,
        ),
    ]

    with patch("spot_product_collateral.config.Config.from_env", return_value=config), \
         patch("main.BottlePOSClient") as mock_bottlepos_class, \
         patch("spot_product_collateral.run.lookup_upc") as mock_lookup, \
         patch("spot_product_collateral.run.crawl_tasting_profile") as mock_crawl, \
         patch("spot_product_collateral.run.anthropic.Anthropic") as mock_anthropic:
        mock_bottlepos_class.return_value = SimpleNamespace(list_items=lambda: fake_items)
        mock_lookup.return_value = UpcLookupResult(
            found=True,
            name="Example Wine 750ML",
            description="A smooth red.",
            image_url=None,
        )
        mock_crawl.return_value = TastingProfileResult(
            found=True,
            tasting_profile="Dark cherry and oak. 13.5% ABV",
            sources=["https://example.com/a", "https://example.com/b"],
        )
        mock_anthropic.return_value = SimpleNamespace(messages=None)

        import main

        main.main(state_path=state_path, runs_dir=runs_dir)

    # Assert on the ACTUAL stored record, not just the manifest.
    products = pb_server.records["products"]
    assert len(products) == 1
    record = next(iter(products.values()))
    assert record["upc"] == "012345678905"
    assert record["name"] == "Example Wine 750ML"
    assert record["description"] == "A smooth red."
    assert record["tasting_profile"] == "Dark cherry and oak. 13.5% ABV"
    assert record["abv"] == 13.5
    assert record["confidence"] == "high"
    assert record["status"] == "published"
    assert record["sources"] == ["https://example.com/a", "https://example.com/b"]
    assert record["bottlepos_item_id"] == "1"
    assert record["bottlepos_snapshot_hash"]

    # The run also wrote a manifest and a clean state.
    manifest_files = os.listdir(runs_dir)
    assert len(manifest_files) == 1
    with open(os.path.join(runs_dir, manifest_files[0])) as f:
        manifest = json.load(f)
    assert manifest["verified"] is True
    assert manifest["items"] == [{"upc": "012345678905", "status": "published"}]
    assert manifest["errors"] == []

    saved_state = State.load(state_path)
    assert saved_state.consecutive_failures == 0
    assert saved_state.last_run_id == manifest["run_id"]
