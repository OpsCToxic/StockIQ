---
description: Scaffold and build a new data-source connector using the connector contract
argument-hint: "<source name, e.g. sec_form4 | finra_short_interest | reddit>"
---
Build a connector for: $ARGUMENTS

Use the connector-engineer subagent with the new-connector skill. First confirm the source's
current official API, auth, rate limits, and terms; if anything blocks it (paid only, approval
pending, scraping forbidden), stop and report before writing code. Finish with fixtures, parse and
idempotency tests, orchestration registration, `.env.example` updates, and `make lint test`.
