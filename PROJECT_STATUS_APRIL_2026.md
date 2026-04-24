# Bulkbeat TV - Project Status (April 2026)

## Overall Status

Production running and stable after queue, admin, and scheduling hardening.

## Confirmed Stable Areas

- 3-minute scheduler ingestion active
- atomic queue claim and in-flight recovery active
- Sarvam-only LLM path active
- market-time live routing and off-market queue routing active
- admin panel single-response behavior fixed

## Key Runtime Decisions

- Embedded admin bot is disabled by default.
- Standalone admin bot is recommended.
- Morning report is disabled by default.
- Morning queued dispatch remains enabled.
- Threshold defaults to strict mode (`8`), but admin can set `4/6/8`.

## Recent Fixes Included

1. Duplicate admin response prevention:
- embedded admin gating
- standalone admin PID lock

2. Queue integrity:
- `claim_pending_news` atomic claim
- `reset_inflight_news` on startup
- retry-safe status reset on processing failure

3. Low-RAM stability:
- DB-backed symbol cooldown state
- bounded queue processing loop

## Current Risk Notes

- Heavy duplicate-source churn causes high "Semantic block" log volume.
- Documentation and runbooks are now synced to actual runtime behavior.

## Recommended Ops Baseline

- Keep threshold at `8` for low-noise operation.
- Ensure only one admin bot process exists.
- Monitor queue snapshot periodically, especially `status=9`.
