# Performance

Where a run's time goes, what was changed to cut it, and the measurements before and after.

## Method

- **Local**: one API process (`WORKERS=1`, as on Render), fresh model readings
  (`force_fresh`), `gemini-3.5-flash-lite`, Tesseract on. Stage durations come from
  `GET /api/runs/{id}`, model-call latency from the run's `llm_call` events.
- **Render-like**: the same API process with a hard CPU cap of 0.1 vCPU (a Windows job object),
  to match the free Render instance. It reproduces the reported Render symptoms closely: the old
  reseeding reset took 79 s here and 87 s on Render, and the first live S06 took 14 s here and
  about 19 s on Render.
- "First run" means the first live model call after the process started.

## Where the time went

| Cost | Why | Share on a 0.1 vCPU instance |
|---|---|---|
| Model client cold start | Every run built a new Gemini client; the first call in a process also imported the SDK and opened a fresh TLS connection | 7.7 s of the first run's 11.3 s reading step |
| OCR on scans | Each scan was rasterised at 300 dpi in colour, although the generated scans are 150 to 170 dpi | 47 s of S04's 52 s |
| Reset | Re-ran all 24 history documents through the pipeline | 79 s |
| Commits | About 45 commits per run, each with an fsync (`synchronous=FULL`) | small locally; depends on the disk |
| Model calls | One reading (about 2.5 s) and one explanation rewording (about 0.8 s) | unchanged |

Not hotspots, measured: the rules read the reference tables 2 or 3 times per run (once per
vendor/PO lookup, not once per check); digital pages are never OCR'd; page images are rendered
only when the viewer asks for them, not inside the pipeline; polling `GET /runs/{id}` costs
15 to 90 ms even at 0.1 vCPU.

## Changes

1. One shared live model client per process, built in a background thread at startup (SDK
   import, connection client), so the first run doesn't wait for it and later runs reuse the
   connection.
2. OCR rasterises a scan at its own resolution (kept between 150 and 300 dpi) and in greyscale.
   The same or more words are found (S04: 146 at 150 dpi against 132 at 300 dpi).
3. The reader opens the PDF once for the checks, text, words and OCR (it opened it twice).
4. SQLite runs with `synchronous=NORMAL` in WAL mode: still safe against corruption and app
   crashes, without an fsync on every commit.
5. Reset restores the seeded snapshot instead of reseeding (see DECISIONS §13).

## Results

Stage durations in ms (wall time in seconds where noted). S06 is a digital invoice, S04 and S05
are scans.

### Local

| Measurement | Before | After |
|---|---|---|
| Reset | 9.7 s (reseed) | 0.15 s (snapshot) |
| S06 first run, wall | 11.5 s | 4.2 s |
| S06 first run, `extract_fields` (model call inside) | 8,927 (2,641) | 2,675 (2,587) |
| S04 `read_document` | 2,981 | 883 |
| S05 `read_document` | 3,503 | 1,177 |
| S01, wall (steady state) | 4.1 s | 4.1 s |

### Render-like (0.1 vCPU)

| Measurement | Before | After |
|---|---|---|
| Reset | 79.4 s (reseed) | 0.4 to 0.7 s (snapshot) |
| S06 first run, wall | 14.1 s | 4.1 s |
| S06 first run, `extract_fields` (model call inside) | 11,254 (3,514) | 2,653 (2,575) |
| S04 `read_document` | 46,902 | 13,693 |
| S04, wall | 52.1 s | 18.6 s |
| S01, wall | 5.3 s | 4.8 s |
| Model client warm-up (background, at startup) | — | 22 to 25 s |

What remains on a 0.1 vCPU instance is the model calls (about 3.3 s per run) and OCR on scans
(about 14 s for S04). A run that hits a provider retry takes 1 to 2 s longer; the reported
`latency_ms` covers the final attempt, and `attempts` shows the retries.

### Live (Render)

The deployed service runs the code from `main`, so the "after" column needs this branch deployed.
