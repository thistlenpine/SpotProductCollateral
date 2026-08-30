# main.py
import os
import sys
from datetime import datetime, timezone

from bottlepos import BottlePOSClient

from spot_product_collateral.config import Config
from spot_product_collateral.run import run_once
from spot_product_collateral.state import State


def main(state_path="STATE.json", runs_dir="runs"):
    state = State.load(state_path)
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

    os.makedirs(runs_dir, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    manifest_path = os.path.join(runs_dir, f"{run_id}.json")

    manifest = run_once(config, items, state_path, manifest_path)
    print(f"Run {manifest['run_id']}: {len(manifest['items'])} enriched, {len(manifest['errors'])} errors")

    if manifest.get("verified") is False:
        print(
            f"Run {manifest['run_id']}: verification FAILED — manifest did not pass verify_manifest. "
            f"consecutive_failures has been incremented in {state_path}. "
            "See HUMAN-GATES.md (gate G2) — a human must diagnose this run.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
