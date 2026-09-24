# SCrobo$ real-market gateway

PROFIT IS THE GOAL. EVIDENCE IS THE BOSS.

The first adapter is Twelve Data, using one explicit authenticated HTTPS request per cache miss. The GitHub secret is **twelvedata_api**, exposed only as the process environment variable `TWELVE_DATA_API_KEY`. The manual `Twelve Data Auth Check` workflow succeeded on 23 September 2026. Authentication alone is not proof of a verified dataset or completed research smoke test.

## Scope and acceptance

The initial gateway supports USD Common Stock/ETF instruments on NASDAQ, NYSE and NYSE ARCA, 1/5/15/30-minute unadjusted candles, and a contiguous range within one regular US session. Provide the exact provider symbol, exchange, MIC, currency and instrument type. Returned metadata must match. UTC is explicitly requested; provider candle-open labels become timezone-aware UTC. Finite positive OHLC geometry, ordering, duplicates, exact coverage, interval spacing, candle completion and an explicit freshness policy are checked. There is no interpolation, missing-bar repair, synthetic fallback or guessed holiday calendar. A holiday or early-close range that lacks requested bars is rejected. Full cross-session calendars and corporate-action research are future work.

`market-fetch REQUEST.json --cache data/cache` writes only accepted `candles.csv` and `manifest.json` under a deterministic request hash. The manifest includes REAL classification, VERIFIED quality, source and identity, normalization, freshness/coverage, SHA-256, acquisition time and evidence eligibility. Failed acquisition/quality checks create a separate sanitized REJECTED record; rejected data never becomes an accepted cache. An incomplete or corrupted cache fails closed and needs explicit investigation rather than silently redownloading. Cache files and private research reports stay ignored by Git. Cache reuse rechecks bytes, metadata, quality and freshness.

`market-lab CACHE_DIR CONFIG.json --output reports` verifies the cache and passes normalized candles to the existing Strategy Lab with final holdout withheld. No holdout-reveal option is exposed. It carries the manifest and fingerprint into the output and checks the engine consumed those exact bytes. REAL/VERIFIED describes the dataset checks, not a validated trading edge: resulting research is PROVISIONAL. Existing low-level batch/lab/portfolio commands are software-test mode; their outputs are SYNTHETIC/TEST_ONLY and ineligible as evidence. Do not use those direct commands to claim real-market evidence.

The cache is a local integrity mechanism, not a signed vendor attestation. A user controlling both files and source can forge records; byte hashes do not prove vendor honesty, licensing, survivorship-bias absence or statistical significance. Mocked test payloads exercise the acceptance branch only and never constitute fetched market observations.

## Broker identity boundary

Trading 212 is not the candle source. T212 fields are null and the gateway explicitly records `PROVIDER_IDENTITY_VERIFIED_BROKER_UNLINKED` until an independent mapping is available. The optional mapping function requires exact ISIN, currency, instrument type and independently resolved exchange with exactly one candidate. It rejects missing or ambiguous identities and never guesses a broker ticker from a provider symbol. T212's documented instrument response does not itself supply an exchange field; a verified exchange association must be added before this mapping can pass. No T212 provider/client, order methods, account-data downloads or configurable live host exists in the gateway.

## Operating locally

Install the project dependencies, including Windows timezone data. Use an already configured `TWELVE_DATA_API_KEY` environment variable; never put the value in a command argument, file, report or source. GitHub workflows map the existing `twelvedata_api` secret to that variable. The current example request format is:

```json
{
  "provider_symbol": "AAPL", "exchange": "NASDAQ", "mic_code": "XNGS",
  "currency": "USD", "instrument_type": "Common Stock", "timeframe": "15min",
  "start": "2026-09-23T13:30:00+00:00", "end": "2026-09-23T19:45:00+00:00",
  "adjustment_policy": "none", "max_age_seconds": 86400
}
```

Those dates are an illustrative bounded request, not a claim that this dataset was downloaded. Freeze dates and freshness limits for the intended historical experiment. `market-portfolio CACHE_DIR CONFIG.json` adapts a single verified provider symbol to the existing shared-cash replay, always development-only. All allocations must reference that symbol; multi-dataset real portfolio acquisition remains future work.

## Licensing and public repository

Twelve Data individual plans permit personal/internal use and prohibit redistribution. No downloaded candles, price-bearing research reports or cache artifacts should be published in this public repository or its public Actions artifacts without appropriate rights. The diagnostic emits only a sanitized auth status. Provider entitlement and metadata visibility are separate; a visible instrument need not be included in the subscription.

Sources checked 23 September 2026: [official API documentation](https://twelvedata.com/docs), [official Python parameter reference](https://github.com/twelvedata/twelvedata-python), [usage terms guidance](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage), [T212 instrument metadata](https://docs.trading212.com/api/instruments/instruments).
