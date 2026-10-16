# AI Visibility Scan

Which brands do LLMs actually recommend? This pipeline asks consumer questions
in Bahasa Indonesia across multiple models (via any OpenAI-compatible gateway)
and measures which Indonesian brands get mentioned — and which are invisible.

**Findings from the first full run** (DeepSeek V4 Flash, 4 July 2026, 90 calls; each category
has 6 answers to its open questions, so every rate below is a count out of 6):

- **Tokopedia and Shopee were named in all 6 e-commerce answers, and Bukalapak in none. That zero
  is the right answer, not a visibility gap.** Bukalapak stopped selling physical goods on its
  marketplace in early 2025: final orders were due by 9 February 2025, and it now sells phone credit,
  data packages and bill payments
  ([Marketech APAC, 10 January 2025](https://marketech-apac.com/indonesias-bukalapak-to-phase-out-physical-goods-shift-focus-to-virtual-products-digital-services/);
  [IDN Financials](https://www.idnfinancials.com/news/51957/closing-down-marketplace-bukalapak-to-shift-to-digital-services)).
  The questions ask where to shop online and where to buy electronics. An earlier version of this
  README called Bukalapak's zero a gap; it was not.
- SeaBank was named in 6 of 6 digital-banking answers; Jenius, the category's pioneer, in 2 of 6.
- 12 of the 50 tracked brands were never named. Bukalapak is one, for the reason above; I have not
  checked the other 11 against company news, so a zero here is a question, not a finding.

Full per-category results in [`summary.csv`](summary.csv); raw per-call data in
[`results.jsonl`](results.jsonl) (93 calls, appended as JSONL so runs are
resumable and auditable).

## How it works

30 consumer questions (10 categories × 3 phrasings, `config.json`) × N runs per
model. Answers are scanned for brand mentions; only *open* questions count
toward visibility (seeded head-to-head questions name brands in the prompt, so
they measure preference, not visibility).

One script, any gateway — OpenRouter, OpenAI, Groq, or a local Ollama:

```bash
pip install -r requirements.txt
python3 scan.py --selftest            # detection logic check, no network

export OPENROUTER_API_KEY=sk-or-...   # or SCAN_API_KEY + SCAN_BASE_URL
SCAN_MODELS="openai/gpt-4o-mini,deepseek/deepseek-chat" python3 scan.py
```

Environment knobs: `SCAN_BASE_URL`, `SCAN_MODELS` (comma-separated), `RUNS`
(default 3 — LLM answers are non-deterministic, so rates beat single samples),
`DELAY_S` (pacing for strict gateways).

## Engineering notes

- **Built for hostile gateways.** 429s are retried honoring the server's
  `retry_after`; SDK fast-retries are disabled so backoff is actually respected.
- **Idempotent, resumable runs.** Every call is appended to `results.jsonl`
  as it completes; re-running skips whatever already succeeded, so a killed
  scan loses nothing.
- **Detection is locale-aware.** Word-boundary matching plus case-sensitive
  handling for brands that are also common Indonesian words (DANA, Jago,
  Accurate — "siapkan dana" must not count as a DANA mention). `--selftest`
  pins this behavior with assertions.

## Methodology caveats (honest ones)

1. Plain API calls ≈ a model's built-in knowledge — consumer apps add web
   grounding, so this is a proxy, not a replica.
2. Mention rates shift across runs and model versions; report rates and dates,
   not absolutes.
3. String detection misses aliases the config doesn't know ("Jaksel" vs
   "Jakarta Selatan" taught us this) — extend `aliases` per brand as needed.
4. A zero can be the right answer. Before calling a brand invisible, check that it still sells what
   the question asks about: Bukalapak's zero above came from the company leaving the category.
