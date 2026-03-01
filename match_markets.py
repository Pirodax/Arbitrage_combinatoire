"""
Match identical markets across Polymarket and Kalshi using
fuzzy text similarity + date proximity scoring.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from rapidfuzz import fuzz


# ── weights ──────────────────────────────────────────────────────────────────
W_TEXT = 0.90
W_DATE = 0.10
SCORE_THRESHOLD = 72.0   # minimum final score (0–100) to keep a match
DATE_DECAY_DAYS = 365    # days at which date score reaches ~0.05


# ── helpers ───────────────────────────────────────────────────────────────────
_STOP = {"will", "the", "a", "an", "in", "on", "at", "by", "to", "of",
         "be", "is", "any", "or", "and", "for", "before", "after",
         "this", "that", "with", "from"}

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t not in _STOP]
    return " ".join(tokens)


def text_score(a: str, b: str) -> float:
    """token_sort_ratio on normalised titles → [0, 100]"""
    return fuzz.token_sort_ratio(normalize(a), normalize(b))


def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s[:26], fmt[:len(s[:26])])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def date_score(d1: Optional[str], d2: Optional[str]) -> float:
    """Exponential decay based on |days difference| → [0, 100].
    Returns 50 when either date is missing (neutral)."""
    dt1, dt2 = parse_date(d1), parse_date(d2)
    if dt1 is None or dt2 is None:
        return 50.0
    delta = abs((dt1 - dt2).days)
    score = 100.0 * (0.05 ** (delta / DATE_DECAY_DAYS))
    return round(score, 2)


def final_score(ts: float, ds: float) -> float:
    return round(W_TEXT * ts + W_DATE * ds, 2)


# ── data loading ──────────────────────────────────────────────────────────────
def load_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── match result ──────────────────────────────────────────────────────────────
@dataclass
class Match:
    pm_title: str
    pm_end: Optional[str]
    pm_yes_price: Optional[float]
    ks_title: str
    ks_end: Optional[str]
    ks_yes_ask: Optional[float]
    text_score: float
    date_score: float
    score: float

    def price_gap(self) -> Optional[float]:
        if self.pm_yes_price is not None and self.ks_yes_ask is not None:
            return round(self.pm_yes_price - self.ks_yes_ask, 4)
        return None


# ── matching logic ────────────────────────────────────────────────────────────
def match(pm_events: list[dict], ks_events: list[dict]) -> list[Match]:
    results: list[Match] = []

    for pm in pm_events:
        pm_title = pm.get("title", "")
        pm_end = pm.get("end_date")
        pm_markets = pm.get("markets", [])
        prices = pm_markets[0].get("outcome_prices", []) if pm_markets else []
        pm_yes = prices[0] if prices else None

        best: Optional[Match] = None

        for ks in ks_events:
            ks_title = ks.get("title", "")
            ks_markets = ks.get("markets", [])
            ks_end = ks_markets[0].get("close_time") if ks_markets else None
            ks_yes_ask = ks_markets[0].get("yes_ask") if ks_markets else None

            ts = text_score(pm_title, ks_title)
            ds = date_score(pm_end, ks_end)
            fs = final_score(ts, ds)

            if fs < SCORE_THRESHOLD:
                continue

            candidate = Match(
                pm_title=pm_title,
                pm_end=pm_end,
                pm_yes_price=float(pm_yes) if pm_yes is not None else None,
                ks_title=ks_title,
                ks_end=ks_end,
                ks_yes_ask=ks_yes_ask,
                text_score=ts,
                date_score=ds,
                score=fs,
            )
            if best is None or fs > best.score:
                best = candidate

        if best:
            results.append(best)

    results.sort(key=lambda m: m.score, reverse=True)
    return results


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    pm_events = load_json("polymarket_events.json")
    ks_events = load_json("kalshi_events.json")

    print(f"Polymarket events : {len(pm_events)}")
    print(f"Kalshi events     : {len(ks_events)}")
    print(f"Threshold         : {SCORE_THRESHOLD}/100\n")

    matches = match(pm_events, ks_events)
    print(f"Matches found : {len(matches)}\n")

    output = []
    for m in matches:
        row = {
            "score": m.score,
            "text_score": m.text_score,
            "date_score": m.date_score,
            "price_gap": m.price_gap(),
            "polymarket": {"title": m.pm_title, "end": m.pm_end, "yes_price": m.pm_yes_price},
            "kalshi":     {"title": m.ks_title, "end": m.ks_end, "yes_ask": m.ks_yes_ask},
        }
        output.append(row)
        print(f"[{m.score:5.1f}] {m.pm_title[:55]}")
        print(f"       ↳ {m.ks_title[:55]}")
        print(f"       text={m.text_score:.1f}  date={m.date_score:.1f}  gap={m.price_gap()}\n")

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("→ saved to matches.json")


if __name__ == "__main__":
    main()
