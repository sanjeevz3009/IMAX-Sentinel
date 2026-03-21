from __future__ import annotations

import logging
from pathlib import Path

from imax_sentinel.browser_fetch import fetch_pages_with_browser

logger = logging.getLogger(__name__)


def fetch_pages(
    urls: list[str],
    timeout_ms: int = 30_000,
    wait_after_load_ms: int = 5_000,
    headless: bool = True,
    user_data_dir: str = ".camoufox-data",
    warmup_url: str | None = None,
    delay_between_pages_seconds: float = 2.5,
    enable_stealth: bool = True,
    simulate_human_behaviour: bool = True,
) -> list[dict]:
    return fetch_pages_with_browser(
        urls=urls,
        timeout_ms=timeout_ms,
        wait_after_load_ms=wait_after_load_ms,
        headless=headless,
        user_data_dir=user_data_dir,
        warmup_url=warmup_url,
        delay_between_pages_seconds=delay_between_pages_seconds,
        enable_stealth=enable_stealth,
        simulate_human_behaviour=simulate_human_behaviour,
    )


def save_html_snapshot(url: str, html: str, output_dir: str) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    safe_name = (
        url.replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .replace("?", "_")
        .replace("&", "_")
        .replace(":", "_")
        .replace("=", "_")
    )

    file_path = output_path / f"{safe_name}.html"
    file_path.write_text(html, encoding="utf-8")
    logger.info("Saved HTML snapshot: %s", file_path)
    return str(file_path)
