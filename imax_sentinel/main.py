from __future__ import annotations

import logging

from imax_sentinel.config import load_config
from imax_sentinel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    log_level = config.get("app", {}).get("log_level", "INFO")

    setup_logging(log_level)

    logger.info("Cinema Sentinel starting up")
    logger.info("Loaded config successfully")

    urls = config.get("bfi", {}).get("urls", [])
    titles = config.get("watch", {}).get("titles", [])

    logger.info("Configured BFI URLs: %s", len(urls))
    logger.info("Configured watchlist titles: %s", len(titles))

    print("Cinema Sentinel config + logging scaffold is ready.")


if __name__ == "__main__":
    main()
