"""
Scrape 1-3 star Trustpilot reviews and extract pain point themes via Ollama.

Strategy: Trustpilot embeds review data in __NEXT_DATA__ JSON — no JS rendering needed.
Fetch each star-filtered page (?stars=1/2/3), parse reviews from __NEXT_DATA__, then
run Ollama (qwen3:8b) to cluster themes.
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import requests

from init_db import init_database

DEFAULT_DB_PATH = Path("competitor_data.db")
REQUEST_TIMEOUT_SECONDS = 30
TRUSTPILOT_BASE = "https://www.trustpilot.com/review/{domain}"
OLLAMA_ENDPOINT = "http://172.17.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen3:0.6b"
STAR_LEVELS = (1, 2, 3)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
]
_UA_CYCLE = itertools.cycle(_USER_AGENTS)


@dataclass(frozen=True)
class SentimentTheme:
    theme: str
    mention_count: int
    sample_quotes: list[str]


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _iter_competitors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT id, domain FROM competitors ORDER BY id").fetchall()


def _fetch(session: requests.Session, url: str) -> str | None:
    session.headers.update({"User-Agent": next(_UA_CYCLE), "Accept-Language": "en-US,en;q=0.9"})
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.text
    except requests.Timeout:
        logging.warning("Timeout fetching %s", url)
    except requests.RequestException as exc:
        logging.warning("HTTP error fetching %s: %s", url, exc)
    return None


def _extract_reviews_from_next_data(html: str) -> list[str]:
    """Parse review texts from Trustpilot's __NEXT_DATA__ JSON blob."""
    import re as _re
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    texts: list[str] = []

    def _search(obj: object, depth: int = 0) -> None:
        if depth > 15:
            return
        if isinstance(obj, dict):
            # reviews key contains a list of review dicts
            if "reviews" in obj and isinstance(obj["reviews"], list):
                for rev in obj["reviews"]:
                    if isinstance(rev, dict):
                        text = rev.get("text") or rev.get("content") or rev.get("body")
                        if text and isinstance(text, str) and len(text) > 10:
                            texts.append(text.strip())
            for v in obj.values():
                _search(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _search(item, depth + 1)

    _search(data)
    return texts


def _extract_themes_ollama(reviews: list[str], stars: int, domain: str) -> list[SentimentTheme]:
    """Send review texts to Ollama and extract complaint themes."""
    if not reviews:
        return []

    combined = "\n\n".join(f"[{i+1}] {t}" for i, t in enumerate(reviews))
    prompt = (
        f"Analyze these {stars}-star customer reviews for {domain} and identify the top recurring complaint themes.\n\n"
        "For each theme: short name (2-5 words), count of reviews mentioning it, and 1-2 direct short quotes.\n"
        "Return ONLY a JSON array, no other text:\n"
        '[{"theme": "Slow Delivery", "count": 4, "quotes": ["took 3 weeks", "never arrived"]}, ...]\n\n'
        f"Reviews:\n{combined[:6000]}\n\nJSON:"
    )

    try:
        resp = requests.post(
            OLLAMA_ENDPOINT,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            timeout=180,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()

        # Extract JSON array from response
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            logging.warning("No JSON array in Ollama response for %s stars=%d", domain, stars)
            return []

        items = json.loads(m.group(0))
        themes: list[SentimentTheme] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("theme", "")).strip()
            count = int(item.get("count", 1))
            quotes = [str(q)[:200] for q in item.get("quotes", []) if q][:3]
            if name:
                themes.append(SentimentTheme(
                    theme=name,
                    mention_count=min(count, len(reviews)),
                    sample_quotes=quotes,
                ))
        return themes

    except requests.RequestException as exc:
        logging.error("Ollama request failed: %s", exc)
    except (json.JSONDecodeError, ValueError) as exc:
        logging.error("Ollama response parse error: %s", exc)
    return []


def _fallback_themes(reviews: list[str], stars: int) -> list[SentimentTheme]:
    """Simple bigram frequency fallback when Ollama is unavailable."""
    from collections import Counter
    words = []
    for text in reviews:
        tokens = re.findall(r"\b[a-z]{4,}\b", text.lower())
        words.extend(zip(tokens, tokens[1:]))
    top = Counter(words).most_common(5)
    return [
        SentimentTheme(theme=" ".join(pair), mention_count=count, sample_quotes=[])
        for pair, count in top
    ]


def _store_themes(
    conn: sqlite3.Connection,
    competitor_id: int,
    scrape_date: str,
    scraped_at: str,
    stars: int,
    themes: list[SentimentTheme],
) -> None:
    for t in themes:
        conn.execute(
            """
            INSERT INTO reviews_sentiment
                (competitor_id, scrape_date, scraped_at, stars_filter, theme, mention_count, sample_quotes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(competitor_id, scrape_date, stars_filter, theme)
            DO UPDATE SET mention_count=excluded.mention_count,
                          sample_quotes=excluded.sample_quotes,
                          scraped_at=excluded.scraped_at
            """,
            (competitor_id, scrape_date, scraped_at, stars, t.theme, t.mention_count,
             json.dumps(t.sample_quotes)),
        )


def _ensure_sentiment_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competitor_id INTEGER NOT NULL,
            scrape_date TEXT NOT NULL,
            scraped_at TEXT NOT NULL,
            stars_filter INTEGER NOT NULL,
            theme TEXT NOT NULL,
            mention_count INTEGER NOT NULL DEFAULT 1,
            sample_quotes TEXT,
            UNIQUE(competitor_id, scrape_date, stars_filter, theme)
        )
    """)


def scrape_reviews_sentiment(db_path: Path = DEFAULT_DB_PATH) -> bool:
    init_database(db_path)
    scrape_date = datetime.now(UTC).date().isoformat()
    scraped_at = datetime.now(UTC).isoformat()
    any_success = False

    # Check Ollama availability
    ollama_ok = False
    try:
        r = requests.get("http://172.17.0.1:11434/api/tags", timeout=5)
        ollama_ok = r.status_code == 200
    except Exception:
        logging.warning("Ollama unavailable — will use bigram fallback")

    with sqlite3.connect(db_path) as conn:
        _ensure_sentiment_table(conn)
        competitors = _iter_competitors(conn)

        with requests.Session() as session:
            for competitor in competitors:
                competitor_id = int(competitor["id"])
                domain = str(competitor["domain"])
                logging.info("Sentiment scrape: %s", domain)

                for stars in STAR_LEVELS:
                    url = f"{TRUSTPILOT_BASE.format(domain=domain)}?stars={stars}"
                    html = _fetch(session, url)
                    if html is None:
                        logging.warning("Failed to fetch %s", url)
                        time.sleep(2)
                        continue

                    reviews = _extract_reviews_from_next_data(html)
                    logging.info("%s stars=%d: %d reviews found", domain, stars, len(reviews))

                    if not reviews:
                        time.sleep(2)
                        continue

                    if ollama_ok:
                        themes = _extract_themes_ollama(reviews, stars, domain)
                    else:
                        themes = _fallback_themes(reviews, stars)

                    if themes:
                        _store_themes(conn, competitor_id, scrape_date, scraped_at, stars, themes)
                        conn.commit()
                        any_success = True
                        logging.info("%s stars=%d: stored %d themes", domain, stars, len(themes))

                    time.sleep(3)

                time.sleep(2)

    return any_success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Trustpilot sentiment (1-3 stars)")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()
    try:
        success = scrape_reviews_sentiment(args.db_path)
        return 0 if success else 1
    except sqlite3.Error as exc:
        logging.exception("DB error: %s", exc)
        return 1
    except Exception as exc:
        logging.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
