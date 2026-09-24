# Real-market paper research handoff

The scheduled workflow runs at minute 23 each hour, with a manual Run workflow button. GitHub schedules are best effort. Your PC can be off. It uses the latest completed US weekday session after a 16:15 New York cutoff, with DST-aware timestamps. Holidays, early closes, missing bars and stale data fail closed; no synthetic substitution.

## Operating model

Vic, Alpha, Beta, Ben and Jah are all independent paper-trading bots on the ChatGPT side. The repo executes their frozen experimental configurations inside the SC-R-D internal paper broker. Vic is the sole main department reporter/logger. Software ledger logging and Jah's machine-readable audit records are infrastructure, not additional department reporters.

The initial queue in examples/real_queue.json contains one versioned technical experiment per bot. Each gets a separate simulated USD account, bounded risk, costs, causal next-open fills and a protected four-bar final holdout. Alpha and Beta have higher paper risk budgets. Ben's initial experiment is explicitly a technical control: no catalyst/fundamental feed exists yet. Jah also trades a technical control and receives reconciliation evidence. These are historical experiments, not persistent forward paper accounts and not autonomous AI agents.

## Evidence and memory

The workflow produces report.md (Vic's summary), results.json, handoffs/{victor,alpha,beta,ben,jah}.json and cumulative state.json. Queued, executed, rejected and reused are explicit execution states. Executed real-market findings remain PROVISIONAL; validated findings stay empty pending a separate frozen validation protocol and review. Losses, failed hypotheses and rejected attempts are retained. No automatic strategy promotion or retuning occurs.

Each handoff carries hypothesis/version, setup parameters, provenance, dataset/engine fingerprints, USD P/L, R metrics, fill timestamps and outcomes, rejects, ledger integrity hashes and review lessons. Price-level fills, raw candles and full SQLite ledgers are generated on the runner but are not published from this public repository. Published records contain only price-free derived evidence. GBP P/L is null with UNAVAILABLE_NO_VERIFIED_FX, never a fabricated pound conversion. Verified historical FX conversion remains to build.

The next run restores the previous real-research-state artifact and validates its hash chain. An identical dataset/request/config/engine evidence ID is reused, not counted again. A changed hypothesis with the same version is rejected. New versions preserve earlier outcomes. This supports human/ChatGPT learning; it does not update ChatGPT memories automatically. History hashes detect accidental changes, not malicious rewrites by a trusted repository owner.

Both artifacts retain 90 days. Each new run carries the cumulative state forward, including rejected runs. If earlier runs exist but history is missing or corrupt, the workflow stops instead of starting over. Download/archive state.json periodically; a gap beyond retention requires restoring history. This is not permanent archival storage. GitHub concurrency prevents overlapping history writers; queued schedules may be delayed or replaced by GitHub.

## ChatGPT-side next step

On their next scheduled run, agents must access the latest successful evidence artifact (or have it uploaded), read their handoff plus prior history, and send review conclusions to Vic. Vic alone produces the main department report. Hypothesis revisions must be explicitly reviewed and committed as a new queue version. The repo does not yet automatically deliver artifacts into ChatGPT or accept agent submissions. No new model/API budget is introduced.

## Verified starting point

The AAPL smoke check on 24 September 2026 passed with 26 genuine 15-minute candles from 23 September. Dataset SHA-256: b1389a5901a6e5adcced961fee05d09d83fea3836d774616d1a053af10a27e4c. Both Strategy Lab and internal paper portfolio consumed the verified data; ledger reconciled and holdout stayed withheld. This is PROVISIONAL real-market evidence, not proof of profitable edge.

Twelve Data identifies AAPL/NASDAQ with MIC XNGS. The earlier XNAS request was rejected; the request was corrected against official provider documentation, without relaxing identity checks: https://twelvedata.com/docs

Trading 212 remains read-only demo authentication only. No T212 order code, order permission or live endpoint is added. Provider identity is verified; T212 listing mapping remains unlinked. Synthetic fixtures remain TEST_ONLY, never learning evidence.
