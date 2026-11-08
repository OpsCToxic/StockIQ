from stockiq.connectors.base import RateLimitedClient

COMPANY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FUND_URL = "https://www.sec.gov/files/company_tickers_mf.json"

# SEC fair access allows 10 req/s; this connector makes two requests a day.
SEC_RATE_PER_SECOND = 5.0


def sec_client(user_agent: str) -> RateLimitedClient:
    if not user_agent.strip() or "@" not in user_agent:
        raise ValueError(
            "Set SEC_USER_AGENT to a descriptive string with a contact email, "
            "e.g. 'StockIQ personal research you@example.com' (SEC fair access policy)"
        )
    return RateLimitedClient(SEC_RATE_PER_SECOND, headers={"User-Agent": user_agent})
