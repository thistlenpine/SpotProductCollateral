# main.py
import os
import sys
from datetime import datetime, timezone

from bottlepos import BottlePOSClient

from spot_product_collateral.config import Config
from spot_product_collateral.run import run_once
from spot_product_collateral.state import State


def main():
    state = State.load("STATE.json")
    if state.consecutive_failures >= 10:
        print(
            f"Halting: consecutive_failures={state.consecutive_failures} >= 10. "
            "See HUMAN-GATES.md — a human must diagnose and reset STATE.json before the next run.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = Config.from_env()
    bottlepos_client = BottlePOSClient(config.bottle_url, config.bottle_user, config.bottle_pass)
    items = bottlepos_client.list_items()

    os.makedirs("runs", exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    manifest_path = os.path.join("runs", f"{run_id}.json")

    manifest = run_once(config, items, "STATE.json", manifest_path)
    print(f"Run {manifest['run_id']}: {len(manifest['items'])} enriched, {len(manifest['errors'])} errors")


if __name__ == "__main__":
    main()
