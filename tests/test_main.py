import pytest
from unittest.mock import patch, MagicMock, mock_open
import sys
import importlib

from spot_product_collateral.state import State


@pytest.fixture
def mock_bottlepos():
    """Mock the bottlepos module to avoid import errors."""
    mock = MagicMock()
    sys.modules["bottlepos"] = mock
    yield mock
    sys.modules.pop("bottlepos", None)


def test_main_halts_when_consecutive_failures_exceeds_threshold(mock_bottlepos):
    """Test that main() exits immediately when consecutive_failures >= 10."""
    # Create a state with consecutive_failures = 10
    mock_state = State(consecutive_failures=10, last_run=None, last_run_id=None)

    # Mock State.load to return our mock state
    with patch("spot_product_collateral.state.State.load", return_value=mock_state):
        # Patch Config.from_env to verify it's never called
        with patch("spot_product_collateral.config.Config.from_env") as mock_config_from_env:
            # Import main (or reload it to get the mocked dependencies)
            import main

            # Call main() and expect SystemExit
            with pytest.raises(SystemExit) as exc_info:
                main.main()

            # Verify exit code is 1
            assert exc_info.value.code == 1

            # Verify Config.from_env() was never called (halt happened before it)
            mock_config_from_env.assert_not_called()


def test_main_halts_when_consecutive_failures_exceeds_threshold_writes_to_stderr(
    mock_bottlepos, capsys
):
    """Test that main() writes a clear message to stderr when halting."""
    # Create a state with consecutive_failures = 10
    mock_state = State(consecutive_failures=10, last_run=None, last_run_id=None)

    with patch("spot_product_collateral.state.State.load", return_value=mock_state):
        with patch("spot_product_collateral.config.Config.from_env") as mock_config_from_env:
            import main

            with pytest.raises(SystemExit):
                main.main()

            # Capture stderr
            captured = capsys.readouterr()
            assert "Halting: consecutive_failures=10 >= 10" in captured.err
            assert "HUMAN-GATES.md" in captured.err
            assert "a human must diagnose and reset STATE.json" in captured.err


def test_main_continues_when_consecutive_failures_below_threshold(mock_bottlepos):
    """Test that main() continues to Config.from_env() when consecutive_failures < 10."""
    # Create a state with consecutive_failures = 5 (below threshold)
    mock_state = State(consecutive_failures=5, last_run=None, last_run_id=None)

    with patch("spot_product_collateral.state.State.load", return_value=mock_state):
        # Mock all the downstream components
        with patch("spot_product_collateral.config.Config.from_env") as mock_config:
            with patch("bottlepos.BottlePOSClient") as mock_bottlepos_class:
                with patch("spot_product_collateral.run.run_once") as mock_run_once:
                    # Setup mock returns
                    mock_config.return_value = MagicMock()
                    mock_bottlepos_instance = MagicMock()
                    mock_bottlepos_class.return_value = mock_bottlepos_instance
                    mock_bottlepos_instance.list_items.return_value = []
                    mock_run_once.return_value = {
                        "run_id": "2026-08-29",
                        "items": [],
                        "errors": [],
                    }

                    import main

                    # Call main() - should NOT raise SystemExit
                    main.main()

                    # Verify Config.from_env() WAS called
                    mock_config.assert_called_once()


def test_main_loads_state_from_json_file_by_default(mock_bottlepos, tmp_path):
    """Test that main() loads STATE.json from the current directory."""
    # Create a real STATE.json file in a temp directory
    state_file = tmp_path / "STATE.json"
    state_file.write_text('{"consecutive_failures": 0, "last_run": null, "last_run_id": null}')

    # Change to temp directory
    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        # Mock the downstream components but NOT State.load (let it use the real file)
        with patch("spot_product_collateral.config.Config.from_env") as mock_config:
            with patch("bottlepos.BottlePOSClient") as mock_bottlepos_class:
                with patch("spot_product_collateral.run.run_once") as mock_run_once:
                    mock_config.return_value = MagicMock()
                    mock_bottlepos_instance = MagicMock()
                    mock_bottlepos_class.return_value = mock_bottlepos_instance
                    mock_bottlepos_instance.list_items.return_value = []
                    mock_run_once.return_value = {
                        "run_id": "2026-08-29",
                        "items": [],
                        "errors": [],
                    }

                    import main

                    # Call main() - should load the real STATE.json and continue
                    main.main()

                    # Verify Config.from_env() WAS called (gate passed)
                    mock_config.assert_called_once()
    finally:
        os.chdir(original_cwd)
