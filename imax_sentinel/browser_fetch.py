from __future__ import annotations

import logging
import random
import time

from camoufox.sync_api import Camoufox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Human-like interactions
# ---------------------------------------------------------------------------


def _human_mouse_move(page, target_x: int, target_y: int, steps: int = 20) -> None:
    """Move mouse to target along a slightly curved Bézier path with jitter."""
    vp = page.viewport_size or {"width": 1440, "height": 900}
    start_x = vp["width"] // 2
    start_y = vp["height"] // 2

    cp_x = random.randint(min(start_x, target_x), max(start_x, target_x))
    cp_y = random.randint(
        min(start_y, target_y) - 60,
        max(start_y, target_y) + 60,
    )

    for i in range(1, steps + 1):
        t = i / steps
        x = int((1 - t) ** 2 * start_x + 2 * (1 - t) * t * cp_x + t**2 * target_x)
        y = int((1 - t) ** 2 * start_y + 2 * (1 - t) * t * cp_y + t**2 * target_y)
        x += random.randint(-2, 2)
        y += random.randint(-2, 2)
        page.mouse.move(x, y)
        page.wait_for_timeout(random.randint(8, 25))


def _human_scroll(page) -> None:
    """Scroll in irregular chunks, occasionally drifting back up slightly."""
    total_scroll = random.randint(300, 800)
    num_steps = random.randint(3, 6)

    for _ in range(num_steps):
        chunk = random.randint(60, total_scroll // num_steps + 40)
        page.mouse.wheel(0, chunk)
        page.wait_for_timeout(random.randint(120, 400))

    if random.random() < 0.4:
        page.mouse.wheel(0, -random.randint(80, 200))
        page.wait_for_timeout(random.randint(200, 500))


def _random_idle_movement(page) -> None:
    """Move cursor to a few random positions, simulating absent-minded reading."""
    vp = page.viewport_size or {"width": 1440, "height": 900}
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, vp["width"] - 100)
        y = random.randint(100, vp["height"] - 100)
        _human_mouse_move(page, x, y)
        page.wait_for_timeout(random.randint(200, 700))


def _hover_random_link(page) -> None:
    """Hover over a random link near the top of the page without clicking."""
    try:
        links = page.query_selector_all("a")
        if not links:
            return
        link = random.choice(links[:10])
        box = link.bounding_box()
        if box:
            _human_mouse_move(
                page,
                int(box["x"] + box["width"] / 2),
                int(box["y"] + box["height"] / 2),
            )
    except Exception:
        pass  # stale element or off-screen — not critical


# ---------------------------------------------------------------------------
# Challenge detection
# ---------------------------------------------------------------------------


def is_challenge_page(html: str) -> bool:
    markers = [
        "performing security verification",
        "cf-turnstile-response",
        "challenge-platform",
        "cloudflare",
        "just a moment",
    ]
    lowered = html.lower()
    return any(marker in lowered for marker in markers)


# ---------------------------------------------------------------------------
# Core fetch function
# ---------------------------------------------------------------------------


def fetch_pages_with_browser(
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
        locale=("en-GB",),  # tuple — Camoufox accepts a sequence
        block_images=False,  # keep images enabled — blocking is a bot signal
    ) as browser:
        # viewport belongs on the context, not the browser launch options
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        # ── Warm-up ──────────────────────────────────────────────────────────
        if warmup_url:
            try:
                logger.info("Warming up browser session with %s", warmup_url)
                page.goto(warmup_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(wait_after_load_ms)
                if simulate_human_behaviour:
                    _random_idle_movement(page)
                    _human_scroll(page)
                logger.info("Warm-up complete | title=%s | url=%s", page.title(), page.url)
            except Exception as exc:
                logger.warning("Warm-up failed for %s: %s", warmup_url, exc)

        # ── Main fetch loop ───────────────────────────────────────────────────
        for index, url in enumerate(urls, start=1):
            logger.info("Browser fetching URL %s/%s: %s", index, len(urls), url)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                actual_wait = wait_after_load_ms
                if simulate_human_behaviour:
                    actual_wait = int(wait_after_load_ms * random.uniform(0.8, 1.2))

                page.wait_for_timeout(actual_wait)

                if simulate_human_behaviour:
                    _random_idle_movement(page)
                    _human_scroll(page)
                    _hover_random_link(page)

                html = page.content()
                final_url = page.url
                title = page.title()
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

    logger.info("Camoufox session complete — %s results", len(results))
    return results
