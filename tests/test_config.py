import pytest
from spot_product_collateral.config import Config

REQUIRED_VARS = [
    "BOTTLE_URL", "BOTTLE_USER", "BOTTLE_PASS",
    "POCKETBASE_URL", "PB_SUPERUSER_EMAIL", "PB_SUPERUSER_PASSWORD",
    "ANTHROPIC_API_KEY",
]


def _set_all(monkeypatch):
    values = {name: f"test-{name.lower()}" for name in REQUIRED_VARS}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_from_env_reads_all_vars(monkeypatch):
    values = _set_all(monkeypatch)
    config = Config.from_env()
    assert config.bottle_url == values["BOTTLE_URL"]
    assert config.bottle_user == values["BOTTLE_USER"]
    assert config.bottle_pass == values["BOTTLE_PASS"]
    assert config.pocketbase_url == values["POCKETBASE_URL"]
    assert config.pb_superuser_email == values["PB_SUPERUSER_EMAIL"]
    assert config.pb_superuser_password == values["PB_SUPERUSER_PASSWORD"]
    assert config.anthropic_api_key == values["ANTHROPIC_API_KEY"]


@pytest.mark.parametrize("missing", REQUIRED_VARS)
def test_from_env_raises_on_missing_var(monkeypatch, missing):
    _set_all(monkeypatch)
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match=missing):
        Config.from_env()
