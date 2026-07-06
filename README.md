# AI Visibility Scan

Which brands do LLMs actually recommend? This pipeline asks consumer questions
in Bahasa Indonesia across multiple models (via any OpenAI-compatible gateway)
and measures which Indonesian brands get mentioned — and which are invisible.

**Headline findings from the first full run (deepseek-v4-flash, 90 calls):**

- **Bukalapak — a former unicorn — was mentioned in 0% of e-commerce answers.**
  Tokopedia and Shopee: 100%.
- SeaBank (100%) crushed Jenius (33%) in digital banking — the category pioneer
  is losing the AI-recommendation battle.
- 12 of 50 tracked brands (24%) were never mentioned at all.

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
