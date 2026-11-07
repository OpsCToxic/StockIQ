# 0004 — Arctic Shift as the Reddit source

- **Status:** Accepted
- **Date:** 2026-11-02

## Context
Phase 7 (social sentiment) needs Reddit posts and comments for a few investing subreddits at
roughly 15-minute freshness. The planned source is the official Reddit Data API (free,
non-commercial tier, approval takes 2–4 weeks). See "Data sources and ingestion" in
docs/architecture.md and invariant 7 in AGENTS.md. Approval is not guaranteed. Cameron has decided
not to apply for it.

Arctic Shift is a community archive of Reddit with a free search API
(`https://arctic-shift.photon-reddit.com`, `/api/posts/search` and `/api/comments/search`). No key
or approval is needed. Tested 2026-11-02 against r/wallstreetbets:
- Newest post was about 2 minutes old; newest comment about 30 minutes old.
- `score` and `num_comments` on recent items are placeholders (1 and 0). The docs say data is
  complete after about 36 hours.
- Rate limits are dynamic, with `X-RateLimit-Reset` headers on responses. No uptime guarantee.
- No license or terms of use found on its README. It accepts removal requests.
- r/wallstreetbets produces roughly 200+ posts per day, so a poll must page until it reaches its
  last-seen timestamp.

Sample responses are saved in `tests/fixtures/arctic_shift/`.

## Options
| Option | Pros | Cons | Cost |
|---|---|---|---|
| Official Reddit Data API (PRAW) | Permitted by Reddit's terms; real-time; reliable | Approval wait of 2–4 weeks, outcome uncertain | Free (non-commercial) |
| Arctic Shift API | No approval; per-subreddit; minutes of lag | Terms unstated; no uptime guarantee; may disappear as Pushshift did; scores late | Free |
| Monthly dumps (Arctic Shift / Academic Torrents) | Bulk history; no API dependence | Large downloads; lag of weeks or months; not usable for live signals | Free (disk and bandwidth) |
| Unofficial scraping | Fast to start | Violates Reddit's terms; breaks and gets blocked; conflicts with invariant 7 | Free, high risk |

## Decision
Accepted by Cameron: use the Arctic Shift API as the Reddit source behind the standard connector
contract. Do not apply for the official Reddit Data API. Use dumps only for historical backfill if
needed. Do not scrape.

Because there is no official fallback, the exit plan matters more: keep every raw response (raw-first
already requires this), keep the connector isolated, and treat Reddit as optional. The sentiment
module must still work from StockTwits and Hacker News alone if Arctic Shift goes away.

## Consequences
- One connector (`connectors/arctic_shift/`), built when Phase 7 starts or earlier if Cameron moves
  it. Raw responses go to object storage first; upsert keyed on the Reddit post or comment ID.
  Polls use `sort=asc` with an advancing `after`, and dedupe on ID at the boundary.
- Point-in-time: every row stores `ingested_at`. Re-fetch each item about 36 hours after posting
  to capture final `score` and `num_comments`. Do not use scores from younger items in any signal.
- Respect HTTP 429 and the reset headers; send a descriptive User-Agent; use the shared token bucket.
- Always combine text search with `subreddit` and a time window. Do text matching in our own code.
- Honour deletions and removals: if an item disappears upstream, mark it removed and exclude it.
- Nothing downstream may depend on which source supplied a row, so another Reddit source can be
  swapped in by writing a new connector that emits the same normalized records.
- Terms risk: personal, non-commercial use only. Revisit before any sharing or multi-user use.
- Reddit-derived signals should be labelled with their source, so a gap in Reddit data is visible
  and not read as "no chatter".

**Revisit if:** the API goes down for more than a few days, adds restrictive terms, starts
returning materially stale data, or Cameron decides to apply for the official Reddit API after all.
