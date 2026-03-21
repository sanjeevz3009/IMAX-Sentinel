import logging

from imax_sentinel.config import load_config
from imax_sentinel.fetch import fetch_pages, save_html_snapshot
from imax_sentinel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main():
    config = load_config()

    log_level = config.get("app", {}).get("log_level", "INFO")
    setup_logging(log_level)

    logger.info("IMAX Sentinel starting up")

    urls = config.get("bfi", {}).get("urls", [])
    save_raw_html = config.get("app", {}).get("save_raw_html", False)
    raw_html_dir = config.get("app", {}).get("raw_html_dir", "data/raw")
    browser_timeout_ms = config.get("app", {}).get("browser_timeout_ms", 30000)
    browser_wait_after_load_ms = config.get("app", {}).get("browser_wait_after_load_ms", 5000)
    browser_headless = config.get("app", {}).get("browser_headless", True)

    logger.info("Configured BFI URLs: %s", len(urls))

    results = fetch_pages(
        urls=urls,
        timeout_ms=browser_timeout_ms,
        wait_after_load_ms=browser_wait_after_load_ms,
        headless=browser_headless,
    )

    successful_fetches = 0
    failed_fetches = 0

    for result in results:
        url = result["url"]

        if result["success"]:
            successful_fetches += 1
            html = result["html"]
            fetch_method = result.get("fetch_method", "unknown")

            logger.info("Fetched %s using method=%s", url, fetch_method)

            if save_raw_html and html:
                save_html_snapshot(url, html, raw_html_dir)
        else:
            failed_fetches += 1
            logger.error("Failed processing URL %s: %s", url, result.get("error"))

    logger.info(
        "Fetch run complete | successful=%s | failed=%s",
        successful_fetches,
        failed_fetches,
    )

    if failed_fetches == 0 and successful_fetches > 0:
        print("Chunk 3 complete: fetcher is working.")
    else:
        print(
            f"Chunk 3 incomplete: successful={successful_fetches}, failed={failed_fetches}. "
            "Fetcher needs adjustment."
        )


if __name__ == "__main__":
    main()
