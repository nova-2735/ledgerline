# Design decisions

Short records of the choices that shape Ledgerline: the context, what was decided, and what it
costs.

## 1. The model only transcribes

**Context.** Invoices vary wildly in layout, and some are scans. A language model reads them far
better than templates or regexes, but it can also make up a plausible number.
**Decision.** The model returns each field as the literal string printed on the page. Code parses
amounts, dates and IDs, and code makes every decision. The model may also suggest line mappings
for bundles and reword the explanation, both behind guards.
**Trade-off.** More code than "ask the model for a decision", and the model can't use judgment we
didn't write down. In return, every outcome is reproducible and every rule is testable.

## 2. Grounding plus validators give field confidence

**Context.** A transcribed value can still be wrong.
**Decision.** Each value is looked up on the page (text layer or OCR words). Confidence combines
"found on the page" with "a validator passed" (GSTIN checksum, line and tax arithmetic, amount in
words). Low confidence on a critical field holds the invoice for a check.
**Trade-off.** Plain text fields with no validator (names, PO reference) top out at medium
confidence, and scans without Tesseract can't be grounded as precisely.

## 3. A deterministic, versioned policy

**Context.** Approving money needs an audit trail and repeatable answers.
**Decision.** Tolerances, limits and switches live in one YAML policy. Each run stores the policy
version (`<version>+<hash>`). The same extraction, overrides, reference data and policy always
give the same decision. A "what if" preview shows which past runs would change under a new
setting.
**Trade-off.** Changing behaviour means editing policy, not prompting. That is the point, but it
is slower to tweak.

## 4. The pipeline continues after a failed check

**Context.** A reviewer who fixes one problem and then discovers a second wastes a round trip.
**Decision.** All 11 stages run even when a check fails, so the decision card lists everything
that is wrong and everything that passed. Only an unreadable file or a non-invoice stops early.
**Trade-off.** Later checks sometimes run on shaky inputs (for example, matching against an
inferred PO), so their messages must say what they assumed.

## 5. Conservative defaults: inferred POs and bank changes

**Context.** The two most expensive mistakes are paying against the wrong PO and paying a
fraudster's account.
**Decision.** A PO that isn't printed can be inferred by scoring candidates, but a person
confirms it with one click. A changed bank account is never auto-approved and is never answered
by email to the invoice's address; Approve stays disabled until a call-back to the number on
file is recorded.
**Trade-off.** Some clean invoices wait for a click. The PO switch is in the policy, so a buyer
can loosen it once the inference proves itself.

## 6. Four outcomes, including Return

**Context.** "Not approved" covers very different next steps.
**Decision.** Approve, Hold (an internal person acts), Return (the document is defective; the
vendor must re-issue) and Reject (must not be paid). Each comes with an owner and one specific
question.
**Trade-off.** Four outcomes need a strict precedence: Reject, then critical Hold, then Return,
then Hold, then Approve.

## 7. Server-sent events tailing the database

**Context.** The live run view must survive refreshes, late joiners and reconnects.
**Decision.** Every event is written to `run_events`; the SSE endpoint tails that table and
clients resume from their last sequence number. SSE rather than WebSockets because traffic is
one-way and SSE works through ordinary HTTP proxies.
**Trade-off.** A 250 ms polling delay and some database reads, which are negligible at this scale.

## 8. SQLite, seeded

**Context.** The demo needs a realistic history (earlier invoices, partial billing) from the
first click, and zero operations.
**Decision.** SQLite in WAL mode via SQLAlchemy. The demo world is generated and seeded at image
build time and copied in on first start. `DATABASE_URL` can point at Postgres.
**Trade-off.** The billing lock is in-process, so the API runs as one process; several processes
would need a database lock.

## 9. A single container

**Context.** Reviewers need one link that works.
**Decision.** One image serves the API and the built web app. The same image runs locally with
`docker compose up`.
**Trade-off.** No independent scaling of web and API, which isn't needed here. The free host
sleeps when idle, so the first load is slow.

## 10. A synthetic world with ground truth and an evaluation

**Context.** Real invoices can't be shared, and "it looks right" isn't a measurement.
**Decision.** A seeded generator (RNG 42) builds one company, its vendors, POs, goods receipts,
24 historical invoices and 15 inbox scenarios across four visual templates, including simulated
scans, each with a known correct answer. `make eval` and `make eval-live` score decisions and
field reads against that truth.
**Trade-off.** Synthetic invoices are cleaner and more uniform than real ones; the results show
the process works as designed, not a production accuracy rate.

## 11. Indian GST specifics

**Context.** The buyer is an Indian company, and GST errors are a common reason to send an
invoice back.
**Decision.** GSTIN checksums, buyer GSTIN check, CGST+SGST for intra-state and IGST for
inter-state supply, current slabs, tax-inclusive pricing, lakh-style amounts ("1,16,348/-"),
day-first dates and INR formatting throughout.
**Trade-off.** Other tax regimes and currencies would need their own rules.

## 12. Cache model readings, and say so

**Context.** Free-tier quotas are tight and a demo can't stall on a rate limit.
**Decision.** Readings are cached by file hash, provider, model and prompt version. A run that
used a cached reading is labelled "cached" in the UI and in its events, and "Process with fresh
read" bypasses the cache. An hourly budget caps live calls.
**Trade-off.** A cached run doesn't show live model latency, so the label must be visible to be
honest.

## 13. Reset restores a seeded snapshot

**Context.** A demo reset re-ran the whole seed through the pipeline: about 5 s on a laptop but
about 87 s on the free Render instance, long enough to break the flow of a live demo.
**Decision.** The freshly seeded database is kept as a snapshot (the image's `/app/seed-data`,
or `DATA_DIR/seed-snapshot/` locally) and a reset copies it into the live database with SQLite's
online backup API, under the same reset lock as before. Saved model readings are carried over. A
local snapshot records a fingerprint of the code, prompts, policy, specs and world and is ignored
once any of them changes; with no current snapshot, or if the restore fails, the reset reseeds.
**Trade-off.** One extra copy of a few-MB database on disk, and the fingerprint is coarse: any
code edit means the next local reset is a slow reseed.

## 14. Keep setup and CPU work off the run path

**Context.** On the free 0.1 vCPU instance a run took several times longer than its model calls.
The first live run in a process paid for importing the model SDK and building a client (about
8 s), every run opened a new connection, and OCR rasterised scans at 300 dpi in colour.
**Decision.** One live model client per process, built in a background thread at startup and
shared by all runs; OCR at the scan's own resolution (150 to 300 dpi) in greyscale; the PDF opened
once per read; SQLite `synchronous=NORMAL` in WAL mode. Measurements are in `docs/PERFORMANCE.md`.
**Trade-off.** The warm-up spends CPU right after boot, competing with the first requests on a
tiny instance. With `synchronous=NORMAL` an OS crash or power cut can lose the last few commits
(never corrupt the database); an app crash loses nothing.
