#!/usr/bin/env python3
"""Scan visibilitas brand Indonesia di jawaban AI — via endpoint OpenAI-compatible.

Satu endpoint, banyak model. Cocok untuk OpenRouter (ratusan model lintas
vendor dengan satu API key), OpenAI langsung, Groq/Together, atau gateway
lokal seperti Ollama (http://localhost:11434/v1).

Pakai:
    export OPENROUTER_API_KEY=sk-or-...
    python3 scan.py                     # scan dengan model default (lihat bawah)
    SCAN_MODELS="openai/gpt-4o-mini,google/gemini-2.5-flash" python3 scan.py
    python3 scan.py --selftest          # cek fungsi deteksi brand, tanpa network

Env:
    SCAN_API_KEY | OPENROUTER_API_KEY | OPENAI_API_KEY   (urutan prioritas)
    SCAN_BASE_URL   default: OpenRouter jika pakai OPENROUTER_API_KEY,
                    selain itu default SDK (api.openai.com)
    SCAN_MODELS     daftar model dipisah koma (slug persis milik gateway-mu)
    RUNS            pengulangan per query, default 3 (jawaban AI non-deterministik)
    DELAY_S         jeda antar panggilan dalam detik, default 2.0 (naikkan kalau
                    gateway-mu ketat rate limit-nya, mis. DELAY_S=4)

Output:
    results.jsonl  — satu baris per panggilan API (mentah; scan bisa di-resume)
    summary.csv    — mention rate per model x kategori x brand (query open saja)
"""
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS = ROOT / "results.jsonl"
SUMMARY = ROOT / "summary.csv"
RUNS = int(os.environ.get("RUNS", "3"))
MAX_TOKENS = 700
DELAY_S = float(os.environ.get("DELAY_S", "2.0"))  # jeda antar panggilan, detik

OPENROUTER_URL = "https://openrouter.ai/api/v1"
# ponytail: cek slug terbaru di openrouter.ai/models sebelum scan serius
DEFAULT_OPENROUTER_MODELS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-2.5-flash",
]


def detect(text: str, brands: list[dict]) -> list[str]:
    """Daftar nama brand yang disebut, terurut posisi kemunculan pertama.

    Word-boundary supaya "DANAmu" tidak match "DANA"; brand ber-flag "cs"
    dicocokkan case-sensitive (DANA/Jago/Accurate = kata umum bhs Indonesia).
    """
    found = []
    for b in brands:
        flags = 0 if b.get("cs") else re.IGNORECASE
        positions = []
        for alias in [b["name"], *b.get("aliases", [])]:
            m = re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, flags)
            if m:
                positions.append(m.start())
        if positions:
            found.append((min(positions), b["name"]))
    return [name for _, name in sorted(found)]


def build_client_and_models():
    key = (
        os.environ.get("SCAN_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not key:
        sys.exit(
            "Tidak ada API key.\n"
            "Set salah satu: SCAN_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY"
        )

    base_url = os.environ.get("SCAN_BASE_URL")
    using_openrouter = bool(
        base_url == OPENROUTER_URL
        or (not base_url and os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("SCAN_API_KEY"))
    )
    if using_openrouter and not base_url:
        base_url = OPENROUTER_URL

    raw = os.environ.get("SCAN_MODELS", "")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        models = DEFAULT_OPENROUTER_MODELS if using_openrouter else ["gpt-4o-mini"]

    from openai import OpenAI

    # max_retries=0: retry 429 kita tangani sendiri supaya bisa menghormati
    # retry_after dari gateway, bukan retry cepat bawaan SDK
    client = OpenAI(api_key=key, base_url=base_url, max_retries=0)
    return client, models


def ask(client, model: str, q: str) -> str:
    # tanpa system prompt & tanpa temperature — kita mau jawaban se-default
    # mungkin, mendekati apa yang dilihat konsumen
    r = client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


def ask_with_retry(client, model: str, q: str, attempts: int = 6) -> str:
    """Retry saat kena rate limit (429), menghormati retry_after dari gateway."""
    for i in range(attempts):
        try:
            return ask(client, model, q)
        except Exception as e:
            msg = str(e)
            if "429" not in msg and "rate limit" not in msg.lower():
                raise
            m = re.search(r"(?:retry_after\D*|Retry in )(\d+)", msg, re.IGNORECASE)
            wait = (int(m.group(1)) + 1) if m else 5 * (i + 1)
            print(
                f"    rate limit — tunggu {wait}s (percobaan {i + 1}/{attempts})",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise RuntimeError(f"masih rate limit setelah {attempts} percobaan")


def load_done() -> set:
    """Kunci (model, query, run) yang sudah ada di results.jsonl — untuk resume."""
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["model"], r["query"], r["run"]))
    return done


def scan(config: dict) -> None:
    client, models = build_client_and_models()
    done = load_done()
    total = sum(len(c["queries"]) for c in config["categories"]) * RUNS * len(models)
    print(f"Model: {', '.join(models)} | total panggilan: {total}\n")

    n = 0
    with RESULTS.open("a") as out:
        for model in models:
            for cat in config["categories"]:
                for q in cat["queries"]:
                    for run in range(1, RUNS + 1):
                        n += 1
                        if (model, q["text"], run) in done:
                            continue
                        try:
                            text = ask_with_retry(client, model, q["text"])
                        except Exception as e:
                            print(f"[{n}/{total}] {model} GAGAL: {e}", file=sys.stderr)
                            time.sleep(DELAY_S)
                            continue
                        rec = {
                            "model": model,
                            "provider": model.split("/")[0] if "/" in model else "openai",
                            "category": cat["name"],
                            "query": q["text"],
                            "query_type": q["type"],
                            "run": run,
                            "mentions": detect(text, cat["brands"]),
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        out.flush()
                        print(
                            f"[{n}/{total}] {model} {cat['name']} run{run}: "
                            f"{', '.join(rec['mentions']) or '(tidak ada brand disebut)'}"
                        )
                        time.sleep(DELAY_S)

    summarize(config)


def summarize(config: dict) -> None:
    """Mention rate per model x kategori x brand — query open saja."""
    runs = defaultdict(int)      # (model, category) -> jumlah run open
    mentions = defaultdict(int)  # (model, category, brand) -> jumlah disebut
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["query_type"] != "open":
            continue
        runs[(r["model"], r["category"])] += 1
        for b in r["mentions"]:
            mentions[(r["model"], r["category"], b)] += 1

    rows = []
    for cat in config["categories"]:
        for (model, c), total in sorted(runs.items()):
            if c != cat["name"]:
                continue
            for b in cat["brands"]:
                hit = mentions.get((model, c, b["name"]), 0)
                rows.append(
                    {
                        "model": model,
                        "category": c,
                        "brand": b["name"],
                        "open_mentions": hit,
                        "open_runs": total,
                        "open_rate": round(hit / total, 2) if total else 0,
                    }
                )
    if not rows:
        print("Belum ada hasil query open di results.jsonl.")
        return

    with SUMMARY.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n=== RINGKASAN (query open, tersimpan di {SUMMARY.name}) ===")
    current = None
    for row in rows:
        key = (row["model"], row["category"])
        if key != current:
            current = key
            print(f"\n{row['model']} / {row['category']}")
        bar = "#" * int(row["open_rate"] * 20)
        print(f"  {row['brand']:<16} {row['open_rate']:>5.0%}  {bar}")


def selftest() -> None:
    brands = [
        {"name": "GoPay"},
        {"name": "DANA", "cs": True},
        {"name": "Bank Jago", "aliases": ["Jago"], "cs": True},
        {"name": "J&T Express", "aliases": ["J&T"]},
    ]
    # urutan mengikuti posisi kemunculan pertama
    assert detect("Saya sarankan DANA lalu GoPay.", brands) == ["DANA", "GoPay"]
    # word boundary: "DANAmu" bukan DANA; "dana" (kata umum) bukan DANA (cs)
    assert detect("siapkan dana untuk DANAmu", brands) == []
    # alias + case-sensitive: "jago masak" bukan Bank Jago, "Jago" iya
    assert detect("Dia jago masak, tapi nabungnya di Jago.", brands) == ["Bank Jago"]
    # karakter spesial di nama brand aman di-regex
    assert detect("Kirim pakai J&T saja.", brands) == ["J&T Express"]
    # tidak ada mention
    assert detect("Tidak ada rekomendasi.", brands) == []
    print("selftest OK — 5 assertion lolos")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        scan(json.loads((ROOT / "config.json").read_text()))
