"""
Match identical markets across Polymarket and Kalshi using
fuzzy text similarity + date proximity scoring.

Arbitrage logic:
  - Buy YES on PM + Buy NO on KS → profit = 1 - (pm_yes_ask + ks_no_ask)
  - Buy NO on PM  + Buy YES on KS → profit = 1 - (pm_no_ask  + ks_yes_ask)
  A positive profit means a risk-free gain (before fees/slippage).
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from rapidfuzz import fuzz


# ── weights & thresholds ──────────────────────────────────────────────────────
W_TEXT          = 0.90
W_DATE          = 0.10
SCORE_THRESHOLD = 72.0   # minimum match score to keep a pair
DATE_DECAY_DAYS = 365    # characteristic decay for date distance
WITHIN_DAYS     = 30     # only match events closing within N days


# ── text helpers ───────────────────────────────────────────────────────────────
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


# ── date helpers ──────────────────────────────────────────────────────────────
def parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def date_score(d1: Optional[str], d2: Optional[str]) -> float:
    """Exponential decay on |days difference| → [0, 100]. 50 if date missing."""
    dt1, dt2 = parse_date(d1), parse_date(d2)
    if dt1 is None or dt2 is None:
        return 50.0
    delta = abs((dt1 - dt2).days)
    return round(100.0 * (0.05 ** (delta / DATE_DECAY_DAYS)), 2)


def final_score(ts: float, ds: float) -> float:
    return round(W_TEXT * ts + W_DATE * ds, 2)


def within_cutoff(date_str: Optional[str], days: int) -> bool:
    """True if date_str is between now and now + days."""
    dt = parse_date(date_str)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    return now <= dt <= now + timedelta(days=days)


# ── data loading ──────────────────────────────────────────────────────────────
def load_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── match result ──────────────────────────────────────────────────────────────
@dataclass
class Match:
    pm_title:    str
    pm_end:      Optional[str]
    pm_yes_ask:  Optional[float]   # coût d'achat YES sur Polymarket
    pm_no_ask:   Optional[float]   # coût d'achat NO  sur Polymarket (≈ 1 - yes_bid)
    ks_title:    str
    ks_end:      Optional[str]
    ks_yes_ask:  Optional[float]   # coût d'achat YES sur Kalshi
    ks_no_ask:   Optional[float]   # coût d'achat NO  sur Kalshi
    text_score:  float
    date_score:  float
    score:       float

    def arb_yes_pm_no_ks(self) -> Optional[float]:
        """Acheter YES sur PM + NO sur KS. Profit = 1 - coût total."""
        if self.pm_yes_ask is not None and self.ks_no_ask is not None:
            cost = self.pm_yes_ask + self.ks_no_ask
            return round(1 - cost, 4)
        return None

    def arb_no_pm_yes_ks(self) -> Optional[float]:
        """Acheter NO sur PM + YES sur KS. Profit = 1 - coût total."""
        if self.pm_no_ask is not None and self.ks_yes_ask is not None:
            cost = self.pm_no_ask + self.ks_yes_ask
            return round(1 - cost, 4)
        return None

    def best_arb(self) -> Optional[float]:
        """Meilleure opportunité d'arbitrage (peut être négative = pas d'arb)."""
        candidates = [x for x in [self.arb_yes_pm_no_ks(), self.arb_no_pm_yes_ks()] if x is not None]
        return max(candidates) if candidates else None

    def best_arb_direction(self) -> Optional[str]:
        a = self.arb_yes_pm_no_ks()
        b = self.arb_no_pm_yes_ks()
        if a is None and b is None:
            return None
        if a is None:
            return "NO_PM + YES_KS"
        if b is None:
            return "YES_PM + NO_KS"
        return "YES_PM + NO_KS" if a >= b else "NO_PM + YES_KS"


# ── matching logic ────────────────────────────────────────────────────────────
def match(pm_events: list[dict], ks_events: list[dict]) -> list[Match]:
    results: list[Match] = []
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=WITHIN_DAYS)

    for pm in pm_events:
        pm_end = pm.get("end_date")

        # Filtre : event Polymarket doit se terminer dans les 30 jours
        pm_dt = parse_date(pm_end)
        if pm_dt is None or not (now <= pm_dt <= cutoff):
            continue

        pm_title = pm.get("title", "")
        pm_markets = pm.get("markets", [])
        pm_m = pm_markets[0] if pm_markets else {}
        pm_yes_ask = pm_m.get("best_ask")
        pm_yes_bid = pm_m.get("best_bid")
        pm_no_ask  = round(1 - pm_yes_bid, 4) if pm_yes_bid is not None else None

        best: Optional[Match] = None

        for ks in ks_events:
            ks_title   = ks.get("title", "")
            ks_markets = ks.get("markets", [])
            ks_m       = ks_markets[0] if ks_markets else {}
            ks_end     = ks_m.get("close_time")
            ks_yes_ask = ks_m.get("yes_ask")
            ks_no_ask  = ks_m.get("no_ask")

            ts = text_score(pm_title, ks_title)
            ds = date_score(pm_end, ks_end)
            fs = final_score(ts, ds)

            if fs < SCORE_THRESHOLD:
                continue

            candidate = Match(
                pm_title=pm_title,
                pm_end=pm_end,
                pm_yes_ask=pm_yes_ask,
                pm_no_ask=pm_no_ask,
                ks_title=ks_title,
                ks_end=ks_end,
                ks_yes_ask=ks_yes_ask,
                ks_no_ask=ks_no_ask,
                text_score=ts,
                date_score=ds,
                score=fs,
            )
            if best is None or fs > best.score:
                best = candidate

        if best:
            results.append(best)

    results.sort(key=lambda m: (m.best_arb() or -999), reverse=True)
    return results


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    pm_events = load_json("polymarket_events.json")
    ks_events = load_json("kalshi_events.json")

    print(f"Polymarket events : {len(pm_events)}")
    print(f"Kalshi events     : {len(ks_events)}")
    print(f"Filtre            : clôture dans {WITHIN_DAYS} jours")
    print(f"Threshold         : {SCORE_THRESHOLD}/100\n")

    matches = match(pm_events, ks_events)
    print(f"Matches trouvés   : {len(matches)}\n")

    output = []
    for m in matches:
        arb = m.best_arb()
        arb_flag = " ⚡ ARB" if arb is not None and arb > 0 else ""
        print(f"[{m.score:5.1f}]{arb_flag}")
        print(f"  PM : {m.pm_title[:60]}  (fin: {m.pm_end[:10] if m.pm_end else '?'})")
        print(f"  KS : {m.ks_title[:60]}")
        print(f"  Prix — PM yes_ask={m.pm_yes_ask}  no_ask={m.pm_no_ask}")
        print(f"         KS yes_ask={m.ks_yes_ask}  no_ask={m.ks_no_ask}")
        print(f"  Arb YES_PM+NO_KS = {m.arb_yes_pm_no_ks()}  |  NO_PM+YES_KS = {m.arb_no_pm_yes_ks()}")
        print(f"  → Meilleure direction : {m.best_arb_direction()}  profit={arb}\n")

        output.append({
            "match_score": m.score,
            "text_score":  m.text_score,
            "date_score":  m.date_score,
            "arbitrage": {
                "best_profit":    arb,
                "direction":      m.best_arb_direction(),
                "yes_pm_no_ks":   m.arb_yes_pm_no_ks(),
                "no_pm_yes_ks":   m.arb_no_pm_yes_ks(),
            },
            "polymarket": {
                "title":   m.pm_title,
                "end":     m.pm_end,
                "yes_ask": m.pm_yes_ask,
                "no_ask":  m.pm_no_ask,
            },
            "kalshi": {
                "title":   m.ks_title,
                "end":     m.ks_end,
                "yes_ask": m.ks_yes_ask,
                "no_ask":  m.ks_no_ask,
            },
        })

    with open("matches.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("→ saved to matches.json")


if __name__ == "__main__":
    main()
