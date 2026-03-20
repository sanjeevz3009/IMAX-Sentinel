from __future__ import annotations

import tomllib
from pathlib import Path


def load_config(path: str = "config.toml") -> dict:
    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Create it from config.example.toml."
        )

    with config_path.open("rb") as f:
        return tomllib.load(f)
