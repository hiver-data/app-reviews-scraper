"""search/app import-swap adapter for google-play-scraper 1.2.7.

One paid hiver/app-store-google-play-scraper run per positive search()/app().
Only keys, signatures and available values are preserved, NOT field completeness.
No dependency on google_play_scraper. See README for absent fields and limits.
"""
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

ACTOR = "hiver/app-store-google-play-scraper"
SEARCH_KEYS = tuple("appId icon screenshots title score genre price free currency video videoImage description descriptionHTML developer installs".split())
APP_KEYS = tuple("title description descriptionHTML summary installs minInstalls realInstalls score ratings reviews histogram price free currency sale saleTime originalPrice saleText offersIAP inAppProductPrice developer developerId developerEmail developerWebsite developerAddress privacyPolicy genre genreId categories icon headerImage screenshots video videoImage contentRating contentRatingDescription adSupported containsAds released lastUpdatedOn updated version comments appId url".split())


def _field(run, snake, camel):
    return run.get(camel) if isinstance(run, dict) else getattr(run, snake, None)


def _locale(lang, country):
    if not isinstance(lang, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*", lang):
        raise ValueError("lang must be a language code, e.g. en or pt-BR")
    if not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2}", country):
        raise ValueError("country must be a two-letter code")
    return lang, country.lower()


def _run(inp, client, token, max_total_charge_usd):
    cap = Decimal(str(max_total_charge_usd))
    if not cap.is_finite() or cap <= 0:
        raise ValueError("max_total_charge_usd must be finite and positive")
    if client is None:
        token = token or os.environ.get("APIFY_TOKEN")
        if not token:
            raise RuntimeError("Set APIFY_TOKEN before calling search() or app().")
        from apify_client import ApifyClient
        client = ApifyClient(token)
    run = client.actor(ACTOR).call(run_input=inp, max_total_charge_usd=cap, logger=None)
    if run is None or _field(run, "status", "status") != "SUCCEEDED":
        raise RuntimeError("Apify app-details run did not succeed: " + str(_field(run, "status", "status") if run else "not started"))
    dataset = _field(run, "default_dataset_id", "defaultDatasetId")
    if not dataset:
        raise RuntimeError("Apify app-details run returned no dataset ID")
    rows = list(client.dataset(dataset).iterate_items())
    for row in rows:
        if row.get("error") or row.get("success") is False:
            raise RuntimeError("Actor app-details error: " + str(row.get("error") or "unsuccessful row"))
    return rows


def _map(row, detail=False):
    result = dict.fromkeys(APP_KEYS if detail else SEARCH_KEYS)
    result["screenshots"] = []
    result.update(appId=row["appId"], title=row.get("appName"), score=row.get("rating"),
                  genre=row.get("genre"), price=row.get("price"), currency=row.get("currency"),
                  developer=row.get("developer"), installs=row.get("installs"))
    result["free"] = row["price"] == 0 if row.get("price") is not None else None
    if detail:
        result.update(ratings=row.get("ratingsCount"), version=row.get("version"),
                      released=row.get("releasedAt"), url=row.get("url"), categories=[], comments=[])
        installs = row.get("installs")
        result["minInstalls"] = int(installs.replace(",", "").removesuffix("+")) if isinstance(installs, str) and re.fullmatch(r"[0-9,]+\+?", installs) else None
        histogram = row.get("histogram")
        result["histogram"] = [histogram.get(str(n)) for n in range(1, 6)] if isinstance(histogram, dict) else None
        updated = row.get("updatedAt")
        if updated:
            date = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            date = date.astimezone(timezone.utc)
            result["updated"] = int(date.timestamp())
            result["lastUpdatedOn"] = date.strftime("%b %d, %Y").replace(" 0", " ")
    return result


def _matches(row, lang, country):
    return (row.get("store") == "google_play" and row.get("country") == country
            and row.get("language") == lang)


def search(query, n_hits=30, lang="en", country="us", *, token=None, client=None,
           max_total_charge_usd=0.10):
    """Return up to min(n_hits, 200) first-page hits in source rank order.

    n_hits<=0 returns [] without a run. Missing/unavailable metadata stays None.
    Failures raise RuntimeError rather than silently returning partial results.
    """
    if isinstance(n_hits, bool) or not isinstance(n_hits, int):
        raise TypeError("n_hits must be an integer")
    if n_hits <= 0:
        return []
    if not isinstance(query, str) or not 0 < len(query.strip()) <= 200:
        raise ValueError("query must be a nonempty string of at most 200 characters")
    query = query.strip()
    lang, country = _locale(lang, country)
    limit = min(n_hits, 200)
    rows = _run({"stores": ["google_play"], "apps": [], "searchTerms": [query],
                 "maxResultsPerTerm": limit, "country": country, "language": lang},
                client, token, max_total_charge_usd)
    matched = [r for r in rows if _matches(r, lang, country) and isinstance(r.get("searchTerm"), str)
               and r["searchTerm"].casefold() == query.casefold()]
    if rows and not matched:
        raise RuntimeError("Actor returned rows for a different store, locale or query")
    if any(not r.get("appId") or isinstance(r.get("rank"), bool) or not isinstance(r.get("rank"), int) or r["rank"] < 1 for r in matched):
        raise RuntimeError("Actor search row is missing appId or source rank")
    seen, result = set(), []
    for row in sorted(matched, key=lambda r: r["rank"]):
        if row["appId"] not in seen:
            seen.add(row["appId"])
            result.append(_map(row))
    return result[:limit]


def app(app_id, lang="en", country="us", *, token=None, client=None,
        max_total_charge_usd=0.10):
    """Return one sparse details dict with the 1.2.7 keys, or raise RuntimeError."""
    if not isinstance(app_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", app_id):
        raise ValueError("app_id must be an explicit Google Play package ID")
    lang, country = _locale(lang, country)
    rows = _run({"stores": ["google_play"], "apps": ["play:" + app_id], "searchTerms": [],
                 "country": country, "language": lang}, client, token, max_total_charge_usd)
    for row in rows:
        if _matches(row, lang, country) and row.get("appId") == app_id:
            return _map(row, detail=True)
    raise RuntimeError("Actor returned no details for the requested app and locale")
