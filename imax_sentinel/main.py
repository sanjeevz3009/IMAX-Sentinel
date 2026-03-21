"""
main.py — IMAX Sentinel V1 orchestrator

Flow:
  1. Fetch both listing pages (new-releases + Nolan permalink)
  2. Parse each into FilmStubs
  3. Filter stubs against the watchlist
  4. Fetch each matched film's individual permalink page
  5. Parse showtimes + statuses
  6. Upsert into SQLite — detect new listings and status changes
  7. Fire Telegram alerts for anything interesting
"""

from __future__ import annotations

import logging

from imax_sentinel.config import load_config
from imax_sentinel.fetch import fetch_pages, save_html_snapshot
from imax_sentinel.logging_config import setup_logging
from imax_sentinel.notify import notify_new_listing, notify_status_change
from imax_sentinel.parse import parse_film_page, parse_listing_page
from imax_sentinel.store import init_db, upsert_performance

logger = logging.getLogger(__name__)


def _title_matches(title: str, watchlist: list[str]) -> bool:
    """Case-insensitive substring match — 'Interstellar' matches 'Interstellar (IMAX)'."""
    title_lower = title.lower()
    return any(w.lower() in title_lower for w in watchlist)


def main() -> None:
    config = load_config()
    app = config.get("app", {})

    log_level = app.get("log_level", "INFO")
    setup_logging(log_level)
    logger.info("IMAX Sentinel starting up")

    # ── Config ────────────────────────────────────────────────────────────────
    listing_urls: list[str] = config.get("bfi", {}).get("listing_urls", [])
    watchlist: list[str] = config.get("watch", {}).get("titles", [])
    watchlist_only: bool = config.get("watch", {}).get("watchlist_only", True)

    save_raw_html: bool = app.get("save_raw_html", False)
    raw_html_dir: str = app.get("raw_html_dir", "data/raw")
    save_challenge_html: bool = app.get("save_challenge_html", True)
    challenge_html_dir: str = app.get("challenge_html_dir", "data/challenges")
    db_path: str = app.get("db_path", "data/sentinel.db")

    browser_kwargs = dict(
        timeout_ms=app.get("browser_timeout_ms", 30_000),
        wait_after_load_ms=app.get("browser_wait_after_load_ms", 5_000),
        headless=app.get("browser_headless", True),
        user_data_dir=app.get("browser_profile_dir", ".camoufox-data"),
        warmup_url=app.get("browser_warmup_url"),
        delay_between_pages_seconds=app.get("browser_delay_between_pages_seconds", 2.5),
        enable_stealth=app.get("browser_enable_stealth", True),
        simulate_human_behaviour=app.get("browser_simulate_human_behaviour", True),
    )

    # ── Init DB ───────────────────────────────────────────────────────────────
    init_db(db_path)

    # ── Step 1: fetch listing pages ───────────────────────────────────────────
    logger.info("Fetching %s listing page(s)", len(listing_urls))
    listing_results = fetch_pages(urls=listing_urls, **browser_kwargs)

    successful_fetches = challenge_fetches = failed_fetches = 0

    # Collect all film stubs from all listing pages
    all_stubs = []
    for result in listing_results:
        url = result["url"]
        if not result["success"]:
            failed_fetches += 1
            logger.error("Failed fetching listing page %s: %s", url, result.get("error"))
            continue

        if result.get("challenge_page"):
            challenge_fetches += 1
            logger.warning("Challenge page on listing: %s", url)
            if save_challenge_html and result["html"]:
                save_html_snapshot(url, result["html"], challenge_html_dir)
            continue

        successful_fetches += 1
        if save_raw_html and result["html"]:
            save_html_snapshot(url, result["html"], raw_html_dir)

        stubs = parse_listing_page(result["html"], source_url=url)
        logger.info("Listing page %s → %s film stubs", url, len(stubs))
        all_stubs.extend(stubs)

    # ── Step 2: filter stubs against watchlist ────────────────────────────────
    if watchlist_only:
        matched_stubs = [s for s in all_stubs if _title_matches(s.title, watchlist)]
        logger.info("Watchlist filter: %s/%s stubs matched", len(matched_stubs), len(all_stubs))
    else:
        matched_stubs = all_stubs
        logger.info("Watchlist filter disabled — processing all %s stubs", len(all_stubs))

    if not matched_stubs:
        logger.info("No matched stubs — nothing to fetch. Exiting.")
        _print_summary(successful_fetches, challenge_fetches, failed_fetches)
        return

    # Deduplicate by permalink (same film may appear on both listing pages)
    seen_permalinks: set[str] = set()
    deduped_stubs = []
    for stub in matched_stubs:
        if stub.permalink not in seen_permalinks:
            seen_permalinks.add(stub.permalink)
            deduped_stubs.append(stub)
    logger.info("After dedup: %s unique film permalinks to fetch", len(deduped_stubs))

    # ── Step 3: fetch each film's individual page ─────────────────────────────
    film_urls = [stub.permalink for stub in deduped_stubs]
    stub_by_url = {stub.permalink: stub for stub in deduped_stubs}

    # Warm-up only happens on the first fetch_pages call — pass None here
    film_browser_kwargs = {**browser_kwargs, "warmup_url": None}
    film_results = fetch_pages(urls=film_urls, **film_browser_kwargs)

    # ── Step 4: parse + upsert + notify ──────────────────────────────────────
    for result in film_results:
        url = result["url"]
        stub = stub_by_url.get(url)

        if not result["success"]:
            failed_fetches += 1
            logger.error("Failed fetching film page %s: %s", url, result.get("error"))
            continue

        if result.get("challenge_page"):
            challenge_fetches += 1
            logger.warning("Challenge page on film page: %s", url)
            if save_challenge_html and result["html"]:
                save_html_snapshot(url, result["html"], challenge_html_dir)
            continue

        successful_fetches += 1
        if save_raw_html and result["html"]:
            save_html_snapshot(url, result["html"], raw_html_dir)

        performances = parse_film_page(result["html"], film_url=url)
        if not performances:
            logger.info("No performances found on %s", url)
            continue

        for perf in performances:
            if not perf.context_id:
                logger.debug("Skipping performance with no context_id: %s", perf.datetime_str)
                continue

            change = upsert_performance(
                context_id=perf.context_id,
                article_id=perf.article_id,
                title=perf.title,
                datetime_str=perf.datetime_str,
                venue=perf.venue,
                status=perf.status,
                booking_url=perf.booking_url,
                source_url=url,
                db_path=db_path,
            )

            # New listing alert
            if change["is_new"]:
                logger.info(
                    "NEW listing: %r  %s  status=%s",
                    perf.title,
                    perf.datetime_str,
                    perf.status,
                )
                notify_new_listing(
                    title=perf.title,
                    datetime_str=perf.datetime_str,
                    status=perf.status,
                    booking_url=perf.booking_url,
                    source_url=url,
                )

            # Status change alert
            elif change["status_changed"]:
                notify_status_change(
                    title=perf.title,
                    datetime_str=perf.datetime_str,
                    old_status=change["old_status"],
                    new_status=change["new_status"],
                    booking_url=perf.booking_url,
                )

    # ── Done ──────────────────────────────────────────────────────────────────
    logger.info(
        "Run complete | fetches=%s | challenges=%s | failed=%s",
        successful_fetches,
        challenge_fetches,
        failed_fetches,
    )
    _print_summary(successful_fetches, challenge_fetches, failed_fetches)


def _print_summary(successful: int, challenges: int, failed: int) -> None:
    if failed == 0 and successful > 0:
        print(f"Run complete: fetches={successful}, challenges={challenges}, failed={failed}")
    else:
        print(
            f"Run partially complete: fetches={successful}, challenges={challenges}, failed={failed}"  # noqa: E501
        )


if __name__ == "__main__":
    main()
