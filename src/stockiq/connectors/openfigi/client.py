from stockiq.connectors.base import RateLimitedClient

MAPPING_URL = "https://api.openfigi.com/v3/mapping"

# Per the OpenFIGI docs: 25 requests/min and 10 jobs/request without a key,
# 250 requests/min and 100 jobs/request with one.
NO_KEY = (25 / 60, 10)
WITH_KEY = (250 / 60, 100)


def figi_client(api_key: str) -> tuple[RateLimitedClient, int]:
    """Return the client and the maximum number of jobs per request."""
    rate, max_jobs = WITH_KEY if api_key else NO_KEY
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    return RateLimitedClient(rate, headers=headers), max_jobs
