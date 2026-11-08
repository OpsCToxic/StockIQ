from stockiq.connectors.base import RateLimitedClient

BASE_URL = "https://api.massive.com"

# ADR 0005: the free plan is 5 calls per minute.
FREE_RATE_PER_SECOND = 5 / 60


def massive_client(api_key: str) -> RateLimitedClient:
    if not api_key.strip():
        raise ValueError("Set MASSIVE_API_KEY in .env")
    # Header auth keeps the key out of URLs (and so out of logs and next_url values).
    return RateLimitedClient(
        FREE_RATE_PER_SECOND, headers={"Authorization": f"Bearer {api_key}"}, timeout=60.0
    )
