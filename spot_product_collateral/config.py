import os
from dataclasses import dataclass

_REQUIRED = [
    "BOTTLE_URL", "BOTTLE_USER", "BOTTLE_PASS",
    "POCKETBASE_URL", "PB_SUPERUSER_EMAIL", "PB_SUPERUSER_PASSWORD",
    "ANTHROPIC_API_KEY",
]


@dataclass
class Config:
    bottle_url: str
    bottle_user: str
    bottle_pass: str
    pocketbase_url: str
    pb_superuser_email: str
    pb_superuser_password: str
    anthropic_api_key: str

    @classmethod
    def from_env(cls) -> "Config":
        values = {}
        for name in _REQUIRED:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            values[name] = value
        return cls(
            bottle_url=values["BOTTLE_URL"],
            bottle_user=values["BOTTLE_USER"],
            bottle_pass=values["BOTTLE_PASS"],
            pocketbase_url=values["POCKETBASE_URL"],
            pb_superuser_email=values["PB_SUPERUSER_EMAIL"],
            pb_superuser_password=values["PB_SUPERUSER_PASSWORD"],
            anthropic_api_key=values["ANTHROPIC_API_KEY"],
        )
