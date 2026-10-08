"""Google Play and App Store reviews to one CSV, via the hiver/app-reviews-scraper Actor on Apify.

    pip install -r requirements.txt
    export APIFY_TOKEN=...   # Apify Console > Settings > API & Integrations
    python reviews_to_csv.py com.spotify.music 324684580 --ratings 1 2 --since 2026-10-01

Apps can be Google Play package names or URLs and App Store IDs or URLs, mixed in one list.
"""
import argparse
import csv
import os
import sys
from decimal import Decimal

from apify_client import ApifyClient

ACTOR = "hiver/app-reviews-scraper"
COLUMNS = [
    "store", "appId", "appName", "country", "rating", "title", "text", "date", "appVersion",
    "thumbsUp", "isEdited", "developerReply", "developerReplyDate", "reviewUrl", "reviewId", "error",
]


def main() -> None:
    p = argparse.ArgumentParser(description="App reviews from Google Play and the App Store to CSV.")
    p.add_argument("apps", nargs="+", help="com.spotify.music, 324684580, or store URLs")
    p.add_argument("--countries", nargs="+", default=["us"], help="store countries, e.g. us gb de")
    p.add_argument("--ratings", nargs="+", help="only these star ratings, e.g. 1 2")
    p.add_argument("--since", help="skip reviews older than this date (YYYY-MM-DD)")
    p.add_argument("--max", type=int, default=100, help="reviews per app and country, 1-5000 (default 100)")
    p.add_argument("--max-charge", type=Decimal, default=Decimal("1.00"),
                   help="stop the run once it has cost this many USD (default 1.00)")
    p.add_argument("--out", default="reviews.csv")
    args = p.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN (Apify Console > Settings > API & Integrations).")

    run_input = {"apps": args.apps, "countries": args.countries, "maxReviewsPerApp": args.max, "sort": "newest"}
    if args.ratings:
        run_input["ratings"] = args.ratings
    if args.since:
        run_input["sinceDate"] = args.since

    # APIFY_API_BASE_URL is only for testing against a mock server; leave it unset.
    client = ApifyClient(token, api_url=os.environ.get("APIFY_API_BASE_URL", "https://api.apify.com"))
    run = client.actor(ACTOR).call(run_input=run_input, max_total_charge_usd=args.max_charge)
    if run is None or run.status != "SUCCEEDED":
        sys.exit(f"Run did not succeed: {run.status if run else 'not started'} {run.status_message if run else ''}")

    rows = errors = 0
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for review in client.dataset(run.default_dataset_id).iterate_items():
            writer.writerow({k: str(v).lower() if isinstance(v, bool) else v for k, v in review.items()})
            rows += 1
            errors += bool(review.get("error"))
    print(f"{rows} rows ({errors} error rows) -> {args.out}")
    print(f"Run {run.id}: {run.status_message}")


if __name__ == "__main__":
    main()
