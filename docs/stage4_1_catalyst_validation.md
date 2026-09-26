# STAGE 4.1 — CATALYST & SEC 8-K VALIDATION REPORT

## 1. Track A — Historical Earnings Announcements
- Announcement timestamps converted to `America/New_York`.
- Point-in-Time Cutoff: Must be publicly available strictly before 09:30:00 ET on session `t` (BMO on session `t` or AMC on session `t-1`).
- Announcements occurring at 09:31 ET or later are strictly excluded from session `t` candidate screening.

## 2. Track B — SEC EDGAR Form 8-K Filings
- Acceptance timestamp extracted from SEC EDGAR header (`acceptanceDateTime`).
- Converted from UTC ISO-8601 to `America/New_York`.
- Point-in-Time Cutoff: Must be accepted prior to 09:30:00 ET.
- Verified against Item 1.01, 1.02, 2.02, 7.01, and 8.01 material disclosures.

## 3. Scale Gap
- Local fixtures contain 30 earnings events and 5 Form 8-Ks.
- Institutional coverage requires tens of thousands of filings.
- Status: **BLOCKER**.
