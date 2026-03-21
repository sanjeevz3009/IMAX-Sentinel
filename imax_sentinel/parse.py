"""
parse.py — BFI IMAX HTML parser

Two-stage parsing mirrors the site structure:

  Stage 1 — Listing page  (new-releases or nolan permalink)
            parse_listing_page()  →  list[FilmStub]
            Extracts the highlight cards: title + film permalink URL.

  Stage 2 — Film page     (individual film permalink)
            parse_film_page()    →  list[Performance]
            Extracts showtimes + booking status for one film.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://whatson.bfi.org.uk/imax/Online/"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FilmStub:
    """A film card scraped from a listing/highlights page."""

    title: str
    permalink: str  # full absolute URL to the film's own page
    date_hint: str = ""  # e.g. "From 20 March" — present on new-releases, absent on Nolan page


@dataclass
class Performance:
    """A single showtime scraped from a film's booking page."""

    title: str
    article_id: str  # AudienceView UUID — stable identifier for the film
    context_id: str  # AudienceView UUID — stable identifier for *this* performance
    datetime_str: str  # raw string, e.g. "Saturday 21 March 2026 21:00"
    datetime_parsed: datetime | None
    venue: str
    status: str  # "available" | "soldout" | "unavailable"
    booking_url: str  # deep link — either seatSelect.asp POST target or article page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_FMT = "%A %d %B %Y %H:%M"


def _parse_datetime(raw: str) -> datetime | None:
    raw = raw.strip()
    try:
        return datetime.strptime(raw, _DATE_FMT)
    except ValueError:
        logger.debug("Could not parse datetime: %r", raw)
        return None


def _resolve_url(href: str) -> str:
    """Turn a relative BFI href into an absolute URL."""
    if href.startswith("http"):
        return href
    return urljoin(BASE_URL, href)


def _extract_uuid(href: str, param: str) -> str:
    """Pull a UUID query-param value out of an AudienceView href."""
    try:
        qs = parse_qs(urlparse(href).query)
        # AudienceView uses :: as a separator in param names
        for key, values in qs.items():
            if key.endswith(param):
                return values[0]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Stage 1 — listing page
# ---------------------------------------------------------------------------


def parse_listing_page(html: str, source_url: str = "") -> list[FilmStub]:
    """
    Parse a highlights/listing page (new-releases or Nolan permalink).

    Returns one FilmStub per Highlight card found.
    """
    soup = BeautifulSoup(html, "html.parser")
    stubs: list[FilmStub] = []

    highlights = soup.select("div.Highlight")
    if not highlights:
        logger.warning("parse_listing_page: no .Highlight cards found (source=%s)", source_url)
        return stubs

    for card in highlights:
        title_tag = card.select_one("h3.Highlight__heading")
        link_tag = card.select_one("a.Highlight__link")

        if not title_tag or not link_tag:
            logger.debug("Skipping incomplete Highlight card")
            continue

        title = title_tag.get_text(strip=True)
        href = link_tag.get("href", "")
        if not href:
            logger.debug("Skipping Highlight card with no href: %s", title)
            continue

        permalink = _resolve_url(href)

        date_hint = ""
        subject_tag = card.select_one("div.Highlight__subject")
        if subject_tag:
            date_hint = subject_tag.get_text(strip=True)

        stubs.append(FilmStub(title=title, permalink=permalink, date_hint=date_hint))
        logger.debug("Found film stub: %r  date_hint=%r  url=%s", title, date_hint, permalink)

    logger.info("parse_listing_page: found %s film stubs (source=%s)", len(stubs), source_url)
    return stubs


# ---------------------------------------------------------------------------
# Stage 2 — film page
# ---------------------------------------------------------------------------


def parse_film_page(html: str, film_url: str = "") -> list[Performance]:
    """
    Parse a film's individual booking page.

    Returns one Performance per showtime row found.
    Status values:
      "available"   — Buy button present
      "soldout"     — "Sold out!" message present
      "unavailable" — row present but no actionable element (coming soon / unknown)
    """
    soup = BeautifulSoup(html, "html.parser")
    performances: list[Performance] = []

    rows = soup.select("div.result-box-item")
    if not rows:
        logger.info("parse_film_page: no showtimes found (url=%s)", film_url)
        return performances

    for row in rows:
        # Title
        name_tag = row.select_one("div.item-name a")
        title = name_tag.get_text(strip=True) if name_tag else "Unknown"
        name_href = name_tag.get("href", "") if name_tag else ""

        article_id = _extract_uuid(name_href, "article_id")
        context_id = _extract_uuid(name_href, "context_id")
        booking_url = _resolve_url(name_href) if name_href else film_url

        # Datetime
        date_tag = row.select_one("span.start-date")
        datetime_str = date_tag.get_text(strip=True) if date_tag else ""
        datetime_parsed = _parse_datetime(datetime_str) if datetime_str else None

        # Venue
        venue_tag = row.select_one("div.item-venue")
        venue = venue_tag.get_text(strip=True) if venue_tag else "BFI IMAX"

        # Status — determined by CSS class on the item-link container
        item_link_div = row.select_one("div.item-link")
        status = "unavailable"
        if item_link_div:
            classes = item_link_div.get("class", [])
            if "soldout" in classes:
                status = "soldout"
            elif item_link_div.select_one("a.btn-primary"):
                status = "available"

        performances.append(
            Performance(
                title=title,
                article_id=article_id,
                context_id=context_id,
                datetime_str=datetime_str,
                datetime_parsed=datetime_parsed,
                venue=venue,
                status=status,
                booking_url=booking_url,
            )
        )
        logger.debug(
            "Performance: %r  %s  status=%s  context_id=%s",
            title,
            datetime_str,
            status,
            context_id,
        )

    logger.info("parse_film_page: found %s performances (url=%s)", len(performances), film_url)
    return performances
