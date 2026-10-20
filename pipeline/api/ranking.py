"""
ranking.py

Score de compatibilité, filtres et tri des offres (calcul 100 % local, aucun coût).

Pourquoi un nouveau score : l'ancien score (part des compétences de l'offre couvertes
par le CV) donnait 100 % à toute offre dont les quelques compétences détectées étaient
dans le CV — y compris une offre où UNE seule compétence a été détectée. Avec des
centaines d'offres à égalité, les premières affichées étaient toutes à 100 %.

Nouveau score (0-100) :
  couverture pondérée = somme des poids des compétences couvertes / somme des poids
                        des compétences de l'offre, poids = rareté (IDF) de la compétence
                        dans l'ensemble des offres : maîtriser une compétence rare compte
                        plus qu'une compétence présente partout (SQL, Python…) ;
  fiabilité           = 0,5 + 0,5 × m / (m + 3 × p), m = somme des poids (rareté) de TOUTES les
                        compétences détectées dans l'offre, p = poids moyen d'une compétence.
                        Une offre où 1 compétence courante est détectée vaut ≈ 0,63 ; avec 3
                        compétences ≈ 0,75 ; avec 8 ≈ 0,86 ; plus les compétences demandées sont
                        nombreuses et rares, plus on se rapproche de 1.
  score = 100 × couverture pondérée × fiabilité.
Un 100 % exact est donc impossible : le plafond d'une offre dépend de la richesse de
ce qu'elle demande réellement. Une offre sans compétence détectée vaut 0.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

RELIABILITY_K = 3


def norm(s: Any) -> str:
    """Minuscules sans accents, pour les recherches insensibles à la casse/accents."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


# ----------------------------------------------------------------- dates
_REL = re.compile(r"il y a\s+(\d+)\s*(minute|heure|jour|semaine|mois)", re.I)
_UNITS = {"minute": timedelta(minutes=1), "heure": timedelta(hours=1), "jour": timedelta(days=1),
          "semaine": timedelta(weeks=1), "mois": timedelta(days=30)}


def parse_published(raw: Any, ref: datetime | None) -> datetime | None:
    """published_at est stocké en texte (formats variables selon la source)."""
    if not raw:
        return None
    s = str(raw).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1]), tzinfo=timezone.utc)
        except ValueError:
            return None
    m = _REL.search(s)
    if m and ref is not None:
        return ref - int(m[1]) * _UNITS[m[2].lower()]
    if norm(s) in ("aujourd'hui", "aujourdhui") and ref is not None:
        return ref
    if norm(s) == "hier" and ref is not None:
        return ref - timedelta(days=1)
    return None


# ----------------------------------------------------------------- libellés normalisés
# Les sources écrivent la même information de façons différentes (« partial », « hybrid »,
# « Télétravail partiel »… ; « MIS », « Intérim » ; « LIB », « Indépendant »…). On les ramène
# à quelques libellés propres pour que les filtres n'affichent aucun doublon.
def remote_label(raw: Any) -> str:
    t = norm(raw)
    if not t or t in ("unknown", "inconnu", "n/a", "na", "null", "none specified", "non precise"):
        return ""
    if re.search(r"full|total|complet|100|integral|entier", t):
        return "Télétravail total"
    if re.search(r"punctual|ponctuel|occasion", t):
        return "Télétravail occasionnel"
    if re.search(r"partial|partiel|hybrid|mixte", t):
        return "Hybride"
    if re.fullmatch(r"(no|non|none|aucun|onsite|on-site|on site|sur site|presentiel|pas de teletravail)", t):
        return "Sur site"
    return str(raw).strip().capitalize()


def contract_label(raw: Any) -> str:
    t = norm(raw)
    if not t:
        return ""
    words = set(re.findall(r"[a-z]+", t))
    if "cdi" in words:
        return "CDI"
    if words & {"alternance", "apprentissage", "professionnalisation", "apprenticeship", "alternant"}:
        return "Alternance"
    if words & {"stage", "stagiaire", "internship", "intern"}:
        return "Stage"
    if words & {"interim", "mis", "mission", "missions"}:
        return "Intérim"
    if words & {"cdd", "temporaire", "temporary", "saisonnier", "sai", "dis"}:
        return "CDD"
    if words & {"freelance", "independant", "lib", "liberal", "independent", "contractor", "franchise", "fra"}:
        return "Freelance / Indépendant"
    if words & {"fonctionnaire", "public", "titulaire", "fonction"}:
        return "Fonction publique"
    return "Autre"


# ----------------------------------------------------------------- villes
def city_of(location: Any) -> str:
    """Ville lisible à partir de formats variés : '75 - PARIS 09', 'Paris (75)', 'Lyon, Rhône'."""
    s = str(location or "").strip()
    if not s:
        return ""
    s = re.sub(r"^\d{2,3}\s*[-–]\s*", "", s)            # '75 - PARIS 09'
    s = re.split(r"[,(/]", s)[0].strip()                # 'Paris, Île-de-France' / 'Paris (75)'
    s = re.sub(r"\s*[-–]\s*\d{2,3}$", "", s)            # 'Rennes - 35'
    s = re.sub(r"\s+\d{1,2}(e|er|eme|ème)?$", "", s, flags=re.I)  # 'Paris 09'
    return s.title() if s.isupper() or s.islower() else s


# ----------------------------------------------------------------- index
class Index:
    """Données d'offres prêtes à scorer et filtrer (construit avec le catalogue)."""

    def __init__(self, entries: list[tuple[dict, Any]]):
        now = datetime.now(timezone.utc)
        self.rows: list[dict] = []
        df: Counter = Counter()
        for offer, skills in entries:
            sk = list(dict.fromkeys(skills or []))
            df.update(sk)
            seen = offer.get("inserted_at") or offer.get("collected_at")
            if isinstance(seen, datetime) and seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            ref = offer.get("collected_at") if isinstance(offer.get("collected_at"), datetime) else now
            pub = parse_published(offer.get("published_at"), ref)
            if pub and pub > now + timedelta(days=1):    # date aberrante dans le futur
                pub = None
            smin, smax = offer.get("salary_min"), offer.get("salary_max")
            self.rows.append({
                "offer": offer, "skills": sk, "skillset": set(sk),
                "pub": pub, "seen": seen, "when": pub or seen,
                "city": city_of(offer.get("location")),
                "contract": contract_label(offer.get("contract_type")),
                "remote": remote_label(offer.get("remote")),
                "smin": smin, "smax": smax, "sal": smax or smin,
                "hay": norm(" ".join([str(offer.get("title") or ""), str(offer.get("company") or ""), " ".join(sk)])),
                "loc": norm(offer.get("location")),
            })
        spell: dict[str, Counter] = {}
        for r in self.rows:
            if r["city"]:
                spell.setdefault(norm(r["city"]), Counter())[r["city"]] += 1
        best = {k: c.most_common(1)[0][0] for k, c in spell.items()}
        for r in self.rows:
            if r["city"]:
                r["city"] = best[norm(r["city"])]
        n = max(1, len(entries))
        self.idf = {s: math.log((n + 1) / (c + 1)) + 1.0 for s, c in df.items()}
        occurrences = sum(df.values()) or 1
        mean_w = sum(self.idf[s] * c for s, c in df.items()) / occurrences     # poids moyen d'une compétence
        self.k_mass = RELIABILITY_K * mean_w
        for r in self.rows:
            r["mass"] = sum(self.idf.get(s, 1.0) for s in r["skills"])
        self.facets = self._facets()

    def _facets(self) -> dict:
        def top(key, limit):
            c = Counter(r[key] for r in self.rows if r[key])
            return [{"value": v, "count": n} for v, n in c.most_common(limit)]
        srcs = Counter(r["offer"].get("source") for r in self.rows if r["offer"].get("source"))
        return {
            "contracts": top("contract", 12), "remotes": top("remote", 8), "cities": top("city", 60),
            "sources": [{"value": v, "count": n} for v, n in srcs.most_common()],
            "with_salary": sum(1 for r in self.rows if r["sal"]),
            "with_date": sum(1 for r in self.rows if r["pub"]),
        }

    # ------------------------------------------------------------- score
    def score(self, row: dict, cv: set[str]) -> tuple[float, list[str], list[str]]:
        sk = row["skills"]
        n = len(sk)
        if not n:
            return 0.0, [], []
        matched = [s for s in sk if s in cv]
        missing = [s for s in sk if s not in cv]
        if not matched:
            return 0.0, matched, missing
        idf = self.idf
        cover = sum(idf.get(s, 1.0) for s in matched) / sum(idf.get(s, 1.0) for s in sk)
        reliability = 0.5 + 0.5 * row["mass"] / (row["mass"] + self.k_mass)
        # compétences manquantes les plus rares en premier : ce sont les plus utiles à apprendre
        missing.sort(key=lambda s: -idf.get(s, 1.0))
        return round(100 * cover * reliability, 1), matched, missing


# ----------------------------------------------------------------- recherche
def search(index: Index, cv_skills: list[str], f: dict) -> tuple[int, list[dict], dict]:
    """Applique filtres + tri. Retourne (total correspondant, page de résultats, distribution)."""
    cv = set(cv_skills)
    now = datetime.now(timezone.utc)
    max_days = f.get("max_age_days")
    cutoff = now - timedelta(days=max_days) if max_days else None
    kw = [w for w in norm(f.get("keyword")).split() if w]
    city = norm(f.get("city"))
    contract, remote, source = f.get("contract"), f.get("remote"), f.get("source")
    sal_only, sal_min = bool(f.get("salary_only")), f.get("salary_min")
    min_score = float(f.get("min_score") or 0)

    hits = []
    for row in index.rows:
        if cutoff and (row["when"] is None or row["when"] < cutoff):
            continue
        if contract and row["contract"] != contract:
            continue
        if remote and row["remote"] != remote:
            continue
        if source and row["offer"].get("source") != source:
            continue
        if sal_only and not row["sal"]:
            continue
        if sal_min and (not row["sal"] or row["sal"] < sal_min):
            continue
        if city and city not in row["loc"]:
            continue
        if kw and not all(w in row["hay"] for w in kw):
            continue
        sc, matched, missing = index.score(row, cv)
        if sc < min_score:
            continue
        hits.append((sc, row, matched, missing))

    sort = f.get("sort") or "relevance"
    ts = lambda r: r["when"].timestamp() if r["when"] else 0.0  # noqa: E731
    if sort == "recent":
        hits.sort(key=lambda h: (ts(h[1]), h[0]), reverse=True)
    elif sort == "salary":
        hits.sort(key=lambda h: (h[1]["sal"] or 0, h[0]), reverse=True)
    else:
        hits.sort(key=lambda h: (h[0], len(h[2]), ts(h[1])), reverse=True)

    dist = {"90+": 0, "70-89": 0, "50-69": 0, "<50": 0, "0": 0}
    for sc, *_ in hits:
        dist["90+" if sc >= 90 else "70-89" if sc >= 70 else "50-69" if sc >= 50 else "<50" if sc > 0 else "0"] += 1
    return len(hits), hits, dist


def to_hit(sc: float, row: dict, matched: list[str], missing: list[str], now: datetime) -> dict:
    o = row["offer"]
    return {
        "dedup_key": o["dedup_key"], "source": o.get("source") or "", "title": o.get("title") or "",
        "company": o.get("company"), "location": o.get("location"), "url": o.get("url"),
        "score": sc, "matched_skills": matched, "missing_skills": missing,
        "contract_type": row["contract"] or None, "remote": row["remote"] or None,
        "salary_min": row["smin"], "salary_max": row["smax"],
        "date": row["when"].isoformat() if row["when"] else None, "date_known": row["pub"] is not None,
    }