# IMAX Sentinel

A personal IMAX ticket watcher for Christopher Nolan and other selected films.

## Stack

- Python 3.14
- uv
- requests
- BeautifulSoup
- SQLite
- Telegram

## Local setup

```bash
uv venv --python 3.14.2
source .venv/bin/activate
uv sync
cp config.example.toml config.toml
uv run python -m imax_sentinel.main
```
