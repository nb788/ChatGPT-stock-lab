# ChatGPT Short-Term Stock Lab Data Bridge

> **Project research gate: `BLOCKED_PREWORK`.** This public bridge may continue
> source acquisition, parsing, and QA, but its outputs may not be used for new
> stock backtests, indicator searches, challenger tuning, holdout access, or
> promotion until the authoritative runtime gate reports `OPEN`. See
> `PROJECT_RESEARCH_RESUME_GATE.md` and `data/research_resume_gate_status.json`.

This public repository is a data-engineering bridge for the Short-Term Stock Strategy Lab. It is infrastructure only; the frozen trading model and private Lab state do not live here.

## Primary roles

- **Alpaca SIP**: 2016-present consolidated U.S. OHLCV/volume and corporate-action/reference validation.
- **SEC EDGAR/data.sec.gov**: authoritative filings, acceptance timestamps and XBRL share facts.
- **Nasdaq Trader symbol directories**: current listed-security/security-class naming support.
- **GitHub Actions**: deterministic transport, parsing, QA and compact public-data output. GitHub is not the source authority.

## Raw SEC outputs

- `data/sec_sp500_share_facts.csv`
- `data/sec_sp500_share_facts_recent.csv`
- `data/sp500_current_source.csv`
- `data/sp500_membership_history_source.csv`
- `data/build_metadata.json`

The raw bridge preserves `dei:EntityCommonStockSharesOutstanding` and `us-gaap:CommonStockSharesOutstanding`, accession numbers, fact dates, filing dates and SEC acceptance timestamps where available. GAAP shares are diagnostic/context evidence, not an automatic replacement for or rejection of a class-specific DEI fact.

## Filing-level QA outputs

The workflow independently parses filing-level inline-XBRL DEI facts because flattened CompanyFacts can lose share-class dimensions. QA outputs include current-universe resolution, quarantined timing exceptions, listing-security identity and rolling accepted-share events.

A valid production denominator must represent the **same economically traded share class** as the SIP volume/price. Deterministic hierarchy:

1. explicit filing-level DEI class/context matched to official listed-security identity;
2. exact `CommonStockMember` where a single listed common security maps uniquely;
3. one-current-ticker/one-latest-DEI-value only when no competing current class/context exists and identity is consistent;
4. flattened CompanyFacts DEI only when recent, point-in-time and independently class-consistent.

`NonvotingCommonStockMember`, `ConvertibleCommonStockMember` and other distinct members are never treated as the listed common class merely because their names contain "common". Ambiguity is preserved and the affected security is ineligible rather than guessed.

## Point-in-time timing rule

`acceptanceDateTime` determines when a filing can become known. A filing accepted after an information cutoff cannot be used at that cutoff. Facts dated after the audit as-of or after their filing acceptance day are quarantined. Missing acceptance timestamps are quarantined unless recovered from an official SEC source.

The production turnover denominator is **not** one latest shares snapshot backfilled across the 21-day window. `sec_current_share_events.csv` is an event stream. For each trading day, the Lab must as-of join the latest valid same-class share event known by that day and then apply only intervening known split factors.

## Corporate actions and security lineage

Ticker equality does not prove security continuity. The Lab separately reconciles dated symbol, CUSIP, CIK/registrant, exchange/share class and corporate actions. Splits are propagated mechanically; ambiguous mergers, spinoffs and reorganizations are quarantined across affected lookback windows. Execution prices remain raw while analytical R21 uses split-only continuity; cash dividends are excluded from production R21.

## Workflow integrity

The SEC workflow is serialized with GitHub Actions concurrency so a stale long-running build cannot publish over newer methodology. Consumers must use only the newest successful, fresh, non-superseded run on current code.

Nightly SEC bulk archives are a bootstrap/reconciliation source, not sufficient by themselves for a 16:30 ET production signal. The Lab requires a same-day live SEC delta/freshness check before production close screening.

## Historical limitations

The current public S&P membership-history reconstruction is a useful candidate source but is not authoritative by itself and requires reconciliation against official S&P DJI change announcements/effective dates. Alpaca solves much of 2016-present market history, including some inactive/acquired names; pre-2016 market-data completeness remains a separate validation roadblock. No current CIK, share count or membership is projected backward without dated validation.

## Integrity boundaries

This bridge does **not** choose favorable facts, impute missing observations, guess share classes, backfill later filings, silently resolve source conflicts, or redefine the Lab objective. Conflicts and failures are retained as QA outputs.

The repository must never contain brokerage credentials, API keys, private Lab state, personal financial information, paper-trading ledgers, or unpublished model specifications. The `SEC_USER_AGENT` is supplied through a GitHub Actions repository secret and is not committed.
