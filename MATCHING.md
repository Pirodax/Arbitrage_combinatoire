# Matching de marchés cross-plateforme

## Objectif

Identifier automatiquement les marchés **identiques ou équivalents** entre Polymarket et Kalshi afin de détecter des opportunités d'arbitrage (différence de prix sur le même événement).

---

## Pipeline

```
polymarket_events.json          kalshi_events.json
        │                               │
        └──────────────┬────────────────┘
                       ▼
              Normalisation des titres
                       │
                       ▼
              Score textuel (rapidfuzz)
                       │
              Score de date (decay)
                       │
                       ▼
              Score final = 70% texte + 30% date
                       │
              Seuil : 72 / 100
                       │
                       ▼
                 matches.json
```

---

## 1. Normalisation du titre

Avant tout calcul, chaque titre est normalisé :

```python
text = text.lower()
text = re.sub(r"[^\w\s]", " ", text)   # supprime ponctuation
tokens = [t for t in text.split() if t not in STOP_WORDS]
```

**Stop words supprimés** : `will, the, a, an, in, on, at, by, to, of, be, is, any, or, and, for, before, after, this, that, with, from`

**Exemples :**

| Titre brut | Après normalisation |
|---|---|
| `"Will Trump win the election?"` | `trump win election` |
| `"Trump wins the 2024 election"` | `trump wins 2024 election` |

---

## 2. Score textuel — `token_sort_ratio`

Fonction : `rapidfuzz.fuzz.token_sort_ratio(a, b)` → `[0, 100]`

### Comment ça marche

1. **Tokenisation** : découpe en mots
2. **Tri alphabétique** des tokens (neutralise l'ordre des mots)
3. **Ratio de Levenshtein** entre les deux chaînes triées

### Formule interne

```
edit_distance = nombre minimum d'insertions/suppressions/substitutions
                pour transformer A en B

ratio = (1 - edit_distance / max(len(A), len(B))) × 100
```

**Exemple concret :**

```
A = "trump win election"      → trié : "election trump win"
B = "trump wins 2024 election" → trié : "2024 election trump wins"

edit_distance ≈ 10
max_len       = 24
ratio = (1 - 10/24) × 100 ≈ 58.3
```

### Pourquoi `token_sort` et pas `ratio` simple ?

`ratio` simple est sensible à l'ordre des mots :
- `"Bitcoin price 2025"` vs `"2025 Bitcoin price"` → ratio ≈ 53
- Avec `token_sort_ratio` → 100 (identiques une fois triés)

---

## 3. Score de date — décroissance exponentielle

Formule :

```
score_date = 100 × 0.05^(|Δjours| / DATE_DECAY_DAYS)
```

Avec `DATE_DECAY_DAYS = 30`.

| Écart entre les dates | Score date |
|---|---|
| 0 jours (même date) | **100.0** |
| 10 jours | 49.4 |
| 30 jours | 5.0 |
| 60 jours | 0.25 |
| Date manquante | **50.0** (neutre) |

La base `0.05` garantit qu'à exactement `DATE_DECAY_DAYS` jours d'écart, le score tombe à 5/100 — considéré comme négligeable.

---

## 4. Score final

```
score_final = 0.70 × score_texte + 0.30 × score_date
```

Les poids reflètent que **le titre est le signal principal** et la date sert de tiebreaker / validateur.

| Composante | Poids | Justification |
|---|---|---|
| Texte | 70 % | Contenu sémantique principal |
| Date | 30 % | Discrimine les séries répétitives (ex: élections mensuelles) |

### Seuil : 72 / 100

En dessous de 72, la paire est rejetée. Ce seuil a été choisi pour :
- Accepter des formulations légèrement différentes (ex: "wins" vs "win")
- Rejeter les faux positifs sur des thèmes génériques ("Will X happen?")

---

## 5. Détection d'arbitrage

Une fois un match confirmé, le `price_gap` est calculé :

```
price_gap = pm_yes_price - ks_yes_ask
```

- `price_gap > 0` → Polymarket cote le YES plus haut que Kalshi : **acheter sur Kalshi, vendre sur Polymarket**
- `price_gap < 0` → inverse

### Exemple de sortie (`matches.json`)

```json
{
  "score": 84.3,
  "text_score": 91.0,
  "date_score": 64.2,
  "price_gap": 0.05,
  "polymarket": {
    "title": "Will Trump impose tariffs on Canada?",
    "end": "2025-04-01T00:00:00Z",
    "yes_price": 0.72
  },
  "kalshi": {
    "title": "Trump tariffs on Canada before April?",
    "end": "2025-04-01T04:59:00Z",
    "yes_ask": 0.67
  }
}
```

---

## Paramètres configurables

| Constante | Valeur | Rôle |
|---|---|---|
| `W_TEXT` | 0.90 | Poids du score textuel |
| `W_DATE` | 0.10 | Poids du score de date |
| `SCORE_THRESHOLD` | 72.0 | Seuil minimum pour garder un match |
| `DATE_DECAY_DAYS` | 365 | Jours pour atteindre score_date ≈ 5 |

> **Pourquoi date à 10 % ?**
> Kalshi utilise des dates de clôture arbitraires (parfois 2029 pour un marché 2026).
> Le texte reste le signal principal ; la date ne sert que de léger tiebreaker.

---

## Résultat sur 100 PM × 200 KS events

```
[90.0] Who will Trump nominate as Fed Chair?  ← gap = +0.93 ⚡
[85.3] Presidential Election Winner 2028
[80.8] US recognize Somaliland by...?
[76.7] Which party wins 2028 US Presidential Election?
```
