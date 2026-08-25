# ChatGPT Short-Term Stock Lab Data Bridge

This public repository is a data-engineering bridge for the Short-Term Stock Strategy Lab.

## Purpose

The Lab uses Alpaca SIP for 2016-present U.S. OHLCV/consolidated volume and SEC EDGAR for point-in-time shares, filings and fundamentals. This repository converts SEC bulk archives into compact plain CSV files that ChatGPT can read reliably.

## Outputs

- `data/sec_sp500_share_facts.csv`
- `data/sec_sp500_share_facts_recent.csv`
- `data/sp500_current_source.csv`
- `data/sp500_membership_history_source.csv`
- `data/build_metadata.json`

The bridge preserves both `dei:EntityCommonStockSharesOutstanding` and `us-gaap:CommonStockSharesOutstanding`, accession numbers, fact dates, filing dates, and SEC acceptance timestamps where available.

## Integrity rules

The bridge does **not** choose a favorable share fact, guess share classes, impute missing observations, or use current shares retrospectively. Conflicting raw facts are preserved for the Lab to quarantine. A filing accepted after the Lab's information cutoff must not be treated as known before that cutoff.

## SEC identification

The scheduled workflow expects a GitHub Actions repository secret named `SEC_USER_AGENT`. Its value should identify the automated research client and provide a contact address, as requested by SEC automated-access guidance. Do not commit credentials or private information to this public repository.

## Data boundaries

This repository contains only public-data infrastructure and public-derived datasets. It must not contain brokerage credentials, API keys, private Lab state, paper-trading ledgers, personal financial information, or unpublished trading-model specifications.
