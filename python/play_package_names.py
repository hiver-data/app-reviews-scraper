"""Google Play package names (appId) by app name, to CSV, via the hiver/app-store-google-play-scraper Actor on Apify.

    pip install -r requirements.txt
    export APIFY_TOKEN=...   # Apify Console > Settings > API & Integrations
    python play_package_names.py Spotify WhatsApp Duolingo --top 3

For google-play-scraper (PyPI 1.2.7) users whose search() returns appId None for the top result.
Every row is a full app record: package name, title, developer, rating, installs, version, URL.
"""
import argparse
import csv
import os
import sys
from decimal import Decimal

from apify_client import ApifyClient

ACTOR = "hiver/app-store-google-play-scraper"
COLUMNS = ["searchTerm", "rank", "appId", "appName", "developer", "rating", "ratingsCount", "installs",
           "version", "updatedAt", "genre", "url", "error"]


def search_play(client, names, top=1, country="us", language="en", max_charge=Decimal("0.10")):
    """Top `top` Google Play results for each app name, as dicts with COLUMNS keys."""
    run_input = {"stores": ["google_play"], "searchTerms": list(names), "maxResultsPerTerm": top,
                 "country": country, "language": language}
    run = client.actor(ACTOR).call(run_input=run_input, max_total_charge_usd=max_charge)
    if run is None or run.status != "SUCCEEDED":
        raise RuntimeError(f"Run did not succeed: {run.status if run else 'not started'}")
    return [{k: row.get(k) for k in COLUMNS} for row in client.dataset(run.default_dataset_id).iterate_items()]


def main() -> None:
    p = argparse.ArgumentParser(description="Google Play package names by app name, to CSV.")
    p.add_argument("names", nargs="+", help="app names, e.g. Spotify WhatsApp (at most 50)")
    p.add_argument("--top", type=int, default=1, help="results per name, 1-200 (default 1)")
    p.add_argument("--country", default="us")
    p.add_argument("--language", default="en")
    p.add_argument("--max-charge", type=Decimal, default=Decimal("0.10"),
                   help="stop the run once it has cost this many USD (default 0.10)")
    p.add_argument("--out", default="play_package_names.csv")
    args = p.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN (Apify Console > Settings > API & Integrations).")
    # APIFY_API_BASE_URL is only for testing against a mock server; leave it unset.
    client = ApifyClient(token, api_url=os.environ.get("APIFY_API_BASE_URL", "https://api.apify.com"))
    rows = search_play(client, args.names, args.top, args.country, args.language, args.max_charge)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    for r in rows:
        if r["rank"] == 1:
            print(f"{r['searchTerm']}: {r['appId']}  ({r['appName']}, {r['developer']})")
    print(f"{len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
