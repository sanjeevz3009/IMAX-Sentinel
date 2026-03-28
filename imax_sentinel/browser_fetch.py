from __future__ import annotations

import logging
import random
import time

from camoufox.sync_api import Camoufox

from imax_sentinel.challenge_detection import is_challenge_page
from imax_sentinel.human_behaviour_simulation import (
    hover_random_link,
    human_scroll,
    random_idle_movement,
)

logger = logging.getLogger(__name__)


# Core fetch function
def fetch_pages_with_browser(
    *,
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
    """
    Fetch a list of URLs using Camoufox (a hardened Firefox fork) which spoofs
    TLS fingerprints, WebGL, fonts, and other low-level signals that Playwright
    Chromium cannot patch at the JS layer.
    """
    logger.info("Starting Camoufox browser session for %s URLs", len(urls))
    results = []

    with Camoufox(
        headless=headless,
        geoip=True,  # derives locale/timezone from IP for consistency
        locale=("en-GB",),  # tuple, Camoufox accepts a sequence
        block_images=False,  # keep images enabled, blocking is a bot signal
    ) as browser:
        # viewport belongs on the context, not the browser launch options
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        # Warm-up
        if warmup_url:
            try:
                logger.info("Warming up browser session with %s", warmup_url)

                page.goto(warmup_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(wait_after_load_ms)

                if simulate_human_behaviour:
                    random_idle_movement(page=page)
                    human_scroll(page=page)

                logger.info("Warm-up complete | title=%s | url=%s", page.title(), page.url)
            except Exception as exc:
                logger.warning("Warm-up failed for %s: %s", warmup_url, exc)

        # Main fetch loop
        for index, url in enumerate(urls, start=1):
            logger.info("Browser fetching URL %s/%s: %s", index, len(urls), url)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                actual_wait = wait_after_load_ms

                if simulate_human_behaviour:
                    actual_wait = int(wait_after_load_ms * random.uniform(0.8, 1.2))

                page.wait_for_timeout(actual_wait)

                if simulate_human_behaviour:
                    random_idle_movement(page)
                    human_scroll(page)
                    hover_random_link(page)

                html = page.content()
                title = page.title()

                final_url = page.url

                challenge_page = is_challenge_page(html)

                if challenge_page:
                    logger.warning(
                        "Challenge page detected for %s | final_url=%s | title=%s",
                        url,
                        final_url,
                        title,
                    )
                else:
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
                        "fetch_method": "camoufox",
                        "success": True,
                        "challenge_page": challenge_page,
                    }
                )

            except Exception as exc:
                logger.exception("Browser fetch failed for %s: %s", url, exc)

                results.append(
                    {
                        "url": url,
                        "final_url": None,
                        "title": None,
                        "html": None,
                        "fetch_method": "camoufox",
                        "success": False,
                        "challenge_page": False,
                        "error": str(exc),
                    }
                )

            sleep_s = delay_between_pages_seconds

            if simulate_human_behaviour:
                sleep_s *= random.uniform(0.7, 1.5)

            time.sleep(sleep_s)

        context.close()

    logger.info("Camoufox session complete - %s results", len(results))

    return results
