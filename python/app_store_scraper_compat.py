"""Small app-store-scraper 0.3.5 migration shim backed by hiver's Apify Actor.

Set APIFY_TOKEN and replace `from app_store_scraper import AppStore` with
`from app_store_scraper_compat import AppStore`. Requires an explicit app_id.
No network request occurs until review(); each call starts one paid Actor run.
"""
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal

ACTOR = "hiver/app-reviews-scraper"


def _utc(value):
    """Interpret the original library's naive datetimes as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _date(value):
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _field(run, name, camel):
    return run.get(camel) if isinstance(run, dict) else getattr(run, name, None)


class AppStore:
    def __init__(self, country, app_name, app_id=None,
                 log_format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                 log_level="INFO", log_interval=5, *, token=None, client=None,
                 max_total_charge_usd=1.00):
        # Logging arguments remain accepted; the Apify client handles run logging.
        if app_id is None or not re.fullmatch(r"[0-9]+", str(app_id)):
            raise ValueError("Supply an explicit numeric App Store app_id; name lookup is not supported.")
        if not re.fullmatch(r"[A-Za-z]{2}", str(country)):
            raise ValueError("country must be a two-letter store country code")
        charge = Decimal(str(max_total_charge_usd))
        if not charge.is_finite() or charge <= 0:
            raise ValueError("max_total_charge_usd must be finite and positive")
        self.country = str(country).lower()
        self.app_name = re.sub(r"[\W_]+", "-", str(app_name).lower())
        self.app_id = int(app_id)
        self.url = f"https://apps.apple.com/{self.country}/app/{self.app_name}/id{self.app_id}"
        self.reviews = []
        self.reviews_count = 0
        self.max_total_charge_usd = charge
        self._client = client
        self._token = token

    def review(self, how_many=sys.maxsize, after=None, sleep=None):
        """Append at most how_many reviews; return None like the original library.

        after is inclusive; naive datetimes mean UTC. sleep is accepted, ignored.
        One run can retrieve at most 5,000 reviews; source availability and the
        charge cap can reduce this further. Repeated calls may append duplicates.
        Failures raise rather than silently appearing as an empty review list.
        """
        if isinstance(how_many, bool) or not isinstance(how_many, int) or how_many <= 0:
            raise ValueError("how_many must be a positive integer")
        if after is not None and not isinstance(after, datetime):
            raise TypeError("after must be a datetime object")
        cutoff = _utc(after) if after is not None else None
        run_input = {"apps": [str(self.app_id)], "countries": [self.country],
                     "maxReviewsPerApp": min(how_many, 5000), "sort": "newest", "onlyNew": False}
        if cutoff is not None:
            run_input["sinceDate"] = cutoff.date().isoformat()
        if self._client is None:
            token = self._token or os.environ.get("APIFY_TOKEN")
            if not token:
                raise RuntimeError("Set APIFY_TOKEN to your Apify API token before calling review().")
            from apify_client import ApifyClient
            self._client = ApifyClient(token)
        run = self._client.actor(ACTOR).call(
            run_input=run_input, max_total_charge_usd=self.max_total_charge_usd)
        if run is None or _field(run, "status", "status") != "SUCCEEDED":
            status = _field(run, "status", "status") if run is not None else "not started"
            raise RuntimeError(f"Apify review run did not succeed: {status}")
        dataset_id = _field(run, "default_dataset_id", "defaultDatasetId")
        if not dataset_id:
            raise RuntimeError("Apify review run returned no dataset ID")
        mapped = []
        for row in self._client.dataset(dataset_id).iterate_items():
            if row.get("error"):
                raise RuntimeError(f"Actor review error: {row['error']}")
            if (row.get("store") != "apple" or str(row.get("appId")) != str(self.app_id)
                    or row.get("country") != self.country):
                continue
            date = _date(row["date"])
            if cutoff is not None and date < cutoff:
                continue
            review = {"date": date.replace(tzinfo=None), "review": row.get("text"),
                      "rating": row.get("rating"), "isEdited": row.get("isEdited"),
                      "title": row.get("title"), "userName": None}
            if row.get("developerReply") is not None:
                review["developerResponse"] = {
                    "id": None, "body": row["developerReply"],
                    "modified": row.get("developerReplyDate")}
            mapped.append(review)
            if len(mapped) >= min(how_many, 5000):
                break
        self.reviews.extend(mapped)
        self.reviews_count = len(self.reviews)
