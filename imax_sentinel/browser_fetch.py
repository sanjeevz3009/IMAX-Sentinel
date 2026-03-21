import logging
import time

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)


def fetch_pages_with_browser(
    urls,
    timeout_ms=30000,
    wait_after_load_ms=5000,
    headless=True,
):
    logger.info("Starting browser session for %s URLs", len(urls))

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            locale="en-GB",
            viewport={"width": 1440, "height": 900},
        )

        page = context.new_page()

        for index, url in enumerate(urls, start=1):
            logger.info("Browser fetching URL %s/%s: %s", index, len(urls), url)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(wait_after_load_ms)

                html = page.content()
                final_url = page.url
                title = page.title()

                logger.info(
                    "Browser fetch successful: %s | final_url=%s | title=%s | bytes=%s",
                    url,
                    final_url,
                    title,
                    len(html),
                )

                results.append(
                    {
                        "url": url,
                        "final_url": final_url,
                        "title": title,
                        "html": html,
                        "fetch_method": "playwright",
                        "success": True,
                    }
                )

                time.sleep(1.5)

            except Exception as exc:
                logger.exception("Browser fetch failed for %s: %s", url, exc)

                results.append(
                    {
                        "url": url,
                        "final_url": None,
                        "title": None,
                        "html": None,
                        "fetch_method": "playwright",
                        "success": False,
                        "error": str(exc),
                    }
                )

        context.close()
        browser.close()

    logger.info("Browser session complete")

    return results
