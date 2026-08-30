import json
import os
from dataclasses import dataclass, asdict


@dataclass
class State:
    consecutive_failures: int = 0
    last_run: str | None = None
    last_run_id: str | None = None

    @classmethod
    def load(cls, path: str) -> "State":
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls(
            consecutive_failures=data.get("consecutive_failures", 0),
            last_run=data.get("last_run"),
            last_run_id=data.get("last_run_id"),
        )

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
