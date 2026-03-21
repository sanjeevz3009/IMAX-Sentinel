import logging
from pathlib import Path

from imax_sentinel.browser_fetch import fetch_pages_with_browser

logger = logging.getLogger(__name__)


def fetch_pages(urls, timeout_ms=30000, wait_after_load_ms=5000, headless=True):
    return fetch_pages_with_browser(
        urls=urls,
        timeout_ms=timeout_ms,
        wait_after_load_ms=wait_after_load_ms,
        headless=headless,
    )


def save_html_snapshot(url, html, output_dir):
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

    logger.info("Saved raw HTML snapshot: %s", file_path)

    return str(file_path)
