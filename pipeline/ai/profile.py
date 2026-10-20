"""
profile.py — faits fiables sur le candidat, calculés LOCALEMENT à partir du CV (sans IA) :
nom, durée d'expérience, niveau (junior / confirmé / senior), en-tête du document.
Ces faits sont ensuite imposés à l'IA : elle ne décide plus elle-même du niveau.
"""
from __future__ import annotations

import re
from datetime import date

MONTHS = {
    "janv": 1, "janvier": 1, "jan": 1, "fevr": 2, "fev": 2, "fevrier": 2, "feb": 2, "mars": 3, "mar": 3,
    "avr": 4, "avril": 4, "apr": 4, "mai": 5, "may": 5, "juin": 6, "jun": 6, "juil": 7, "juillet": 7, "jul": 7,
    "aout": 8, "aug": 8, "sept": 9, "sep": 9, "septembre": 9, "oct": 10, "octobre": 10, "nov": 11,
    "novembre": 11, "dec": 12, "decembre": 12,
}
_M = r"(?:(\d{1,2})[/.]|([A-Za-zéûôè]{3,10})\.?\s+)?(20\d{2}|19\d{2})"
PRESENT = r"(?:pr[ée]sent|aujourd.hui|actuel|en cours|maintenant|ce jour|now|current)"
RANGE = re.compile(rf"{_M}\s*(?:-|–|—|à|au|to)\s*(?:{_M}|({PRESENT}))", re.I)
EDU_WORDS = re.compile(r"dipl[oô]me|master|mast[eè]re|licence|bachelor|bts|dut|bac\b|[ée]cole|universit|formation|"
                       r"cursus|scolarit|certification|\bmba\b|ing[ée]nieur\b.*[ée]cole", re.I)
RELEVANT = re.compile(r"\bdata\b|donn[ée]es|\bbi\b|power ?bi|sql|etl|python|pipeline|airflow|spark|databricks|big data|"
                      r"analyste|d[ée]veloppeu|ing[ée]nieur|steward|dashboard|reporting|cloud|devops|power ?apps", re.I)
EXP_SECTION = re.compile(r"exp[ée]rience|parcours professionnel|emploi|missions?", re.I)
EDU_SECTION = re.compile(r"formation|dipl[oô]me|[ée]tudes|scolarit|cursus", re.I)


def _norm(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _month(num, name) -> int:
    if num:
        n = int(num)
        return n if 1 <= n <= 12 else 1
    if name:
        return MONTHS.get(_norm(name).rstrip("."), MONTHS.get(_norm(name)[:4], 1))
    return 1


def experience_months(cv_text: str, today: date | None = None, relevant_only: bool = False) -> int:
    """Mois d'expérience professionnelle (alternance incluse), en fusionnant les périodes
    qui se chevauchent. Les périodes situées dans une section/ligne « formation » sont ignorées."""
    today = today or date.today()
    spans: list[tuple[int, int, bool]] = []
    lines_all = cv_text.replace("\r", "").split("\n")
    section = "exp"
    for idx, line in enumerate(lines_all):
        s = line.strip()
        if len(s) < 40 and not RANGE.search(s):
            if EDU_SECTION.search(s) and not EXP_SECTION.search(s):
                section = "edu"
            elif EXP_SECTION.search(s):
                section = "exp"
        for m in RANGE.finditer(line):
            g = m.groups()
            m1, n1, y1 = g[0], g[1], int(g[2])
            if g[6]:
                y2, mo2 = today.year, today.month
            else:
                y2, mo2 = int(g[5]), _month(g[3], g[4])
            mo1 = _month(m1, n1)
            if y1 < 1990 or y2 > today.year + 1 or y2 < y1:
                continue
            if section == "edu" or (EDU_WORDS.search(line) and not re.search(r"alternan|apprenti|stage|stagiaire", line, re.I)):
                continue
            a, b = y1 * 12 + mo1, y2 * 12 + mo2
            if b >= a:
                ctx = " ".join(lines_all[idx:idx + 4])
                spans.append((a, b, bool(RELEVANT.search(ctx))))
    spans = [(a, b) for a, b, r in spans if r or not relevant_only]
    spans.sort()
    total, cur = 0, None
    for a, b in spans:
        if cur is None:
            cur = [a, b]
        elif a <= cur[1]:
            cur[1] = max(cur[1], b)
        else:
            total += cur[1] - cur[0]; cur = [a, b]
    if cur:
        total += cur[1] - cur[0]
    return total


def seniority(months: int) -> tuple[str, str]:
    """(niveau, consigne de formulation) — seuils prudents."""
    years = months / 12
    if years < 3:
        return "junior", "profil junior / en début de carrière (alternance et stages inclus)"
    if years < 6:
        return "confirmé", "profil confirmé de 3 à 6 ans d'expérience (jamais « senior »)"
    return "senior", "profil expérimenté de plus de 6 ans"


def candidate_name(cv_text: str) -> str:
    """Nom du candidat = première ligne qui ressemble à un nom (2–4 mots, lettres uniquement)."""
    for line in cv_text.replace("\r", "").split("\n")[:12]:
        s = re.sub(r"[#*_|•·]", " ", line).strip(" -–—:\t")
        s = re.sub(r"\s+", " ", s)
        if not s or re.search(r"[@\d/]|http|www", s):
            continue
        words = s.split(" ")
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’\-]+", w) for w in words):
            if re.search(r"curriculum|\bcv\b|profil|exp[ée]rience|comp[ée]tences|formation|ing[ée]nieur|d[ée]veloppeur|"
                         r"data|engineer|analyst|consultant|manager|steward|alternan", s, re.I):
                continue
            return " ".join(w if w.isupper() and len(w) > 1 else w[:1].upper() + w[1:] for w in words)
    return ""


def clean_title(title: str, strip_level: bool = False) -> str:
    """Intitulé de l'offre sans « (H/F) », « F/H », ni mention de niveau absurde pour le candidat."""
    t = re.sub(r"\(?\s*\b[HF]\s*/\s*[HF]\b\s*\)?|\(?\s*\bH\s*/\s*F\b\s*\)?|\(?\s*\bF\s*/\s*H\b\s*\)?", "", title or "", flags=re.I)
    if strip_level:
        t = re.sub(r"\b(senior|s[ée]nior|confirm[ée]e?|exp[ée]riment[ée]e?|lead)\b", "", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip(" -–—|,")


def _get(offer, *keys) -> str:
    for k in keys:
        v = offer.get(k) if isinstance(offer, dict) else getattr(offer, k, None)
        if v:
            return str(v).strip()
    return ""


def facts(cv_text: str, offer) -> dict:
    total = experience_months(cv_text)
    months = experience_months(cv_text, relevant_only=True)
    if months == 0:   # pertinence non détectée : on retient la durée totale plutôt que de sous-estimer
        months = total
    level, wording = seniority(months)
    if total == 0:   # aucune période datée lisible : on ne devine pas le niveau
        level, wording = "indéterminé", "durée d'expérience non déterminée : n'indique AUCUN niveau (junior, senior…) ni nombre d'années ; reste factuel"
    if total - months >= 12:
        wording += f" ; environ {round((total - months) / 12, 1)} an(s) d'expérience professionnelle dans d'autres domaines (à présenter comme compétences transversales, pas comme expérience data)"
    return {
        "name": candidate_name(cv_text),
        "months": months,
        "years": round(months / 12, 1),
        "level": level,
        "wording": wording,
        "target": clean_title(_get(offer, "title", "titre", "intitule", "job_title"), strip_level=True),
        "company": _get(offer, "company", "company_name", "entreprise", "employer"),
    }


def header_markdown(f: dict, include_company: bool = True) -> str:
    """En-tête imposé : NOM puis poste visé (et entreprise). Ajouté par le code, jamais par l'IA."""
    name = f["name"] or "Prénom NOM"
    line = f["target"]
    if include_company and f["company"]:
        line = f"{line} — {f['company']}" if line else f["company"]
    return f"# {name}\n\n**{line}**\n" if line else f"# {name}\n"


# ------------------------------------------------------------------ contacts & en-têtes
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def contacts(cv_text: str) -> dict:
    """E-mail, téléphone, adresse/ville, LinkedIn lus dans le CV (jamais inventés : vides si absents)."""
    t = cv_text.replace("\r", "")
    email = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", t)
    phone = re.search(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.\-]?\d{2}){4}(?!\d)", t)
    linkedin = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%]+/?", t, re.I)
    address = city = ""
    m = re.search(r"^[ \t]*((?:\d{1,3}[ ,]*(?:bis|ter)?[ ,]*)?[^\n\d@|]{0,40}?)?[ ,]*(\d{5})[ ,]+([A-Za-zÀ-ÿ' \-]{2,30})", t, re.M)
    if m:
        city = m.group(3).strip(" ,-")
        street = (m.group(1) or "").strip(" ,-")
        address = f"{street}, {m.group(2)} {city}".strip(" ,") if street else f"{m.group(2)} {city}"
    else:   # « Paris · email » ou « Île-de-France » dans les 8 premières lignes
        for line in t.split("\n")[:8]:
            mm = re.search(r"(?:·|\||•|-)\s*(Paris|Lyon|Marseille|Toulouse|Nantes|Bordeaux|Lille|Rennes|Strasbourg|Montpellier|Nice)\b", line)
            if mm:
                city = mm.group(1); break
    return {"email": email.group(0) if email else "", "phone": re.sub(r"\s+", " ", phone.group(0)).strip() if phone else "",
            "linkedin": linkedin.group(0) if linkedin else "", "address": address, "city": city}


def french_date(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.day}{'er' if d.day == 1 else ''} {MOIS[d.month - 1]} {d.year}"


def _offer_city(offer) -> str:
    loc = _get(offer, "city", "ville", "location", "lieu", "location_name")
    loc = re.sub(r"^\s*\d{2,5}\s*[-–,]?\s*", "", loc).split(",")[0].split(" - ")[0].strip()
    return loc if len(loc) <= 40 else ""


def cv_header(f: dict, c: dict) -> str:
    """En-tête du CV : NOM / poste visé — entreprise / contacts. Ajouté par le code."""
    parts = [f["name"] or "Prénom NOM"]
    out = f"# {parts[0]}\n"
    if f["target"]:
        out += f"\n**{f['target']}" + (f" — {f['company']}" if f["company"] else "") + "**\n"
    line = " · ".join(x for x in (c["city"] or c["address"], c["phone"], c["email"], c["linkedin"]) if x)
    if line:
        out += f"\n{line}\n"
    return out


def letter_header(f: dict, c: dict, offer) -> str:
    """Bloc normalisé d'une lettre française : expéditeur, destinataire, lieu/date, objet, séparateur."""
    sender = [f"**{f['name'] or 'Prénom NOM'}**"]
    if c["address"]:
        sender.append(c["address"])
    if c["phone"]:
        sender.append(c["phone"])
    if c["email"]:
        sender.append(c["email"])
    recipient = [f"**{f['company']}**" if f["company"] else "**À l'attention du Service Recrutement**"]
    if f["company"]:
        recipient.append("Service Recrutement")
    city = _offer_city(offer)
    if city:
        recipient.append(city)
    place = c["city"] or ""
    date_line = f"Fait à {place}, le {french_date()}" if place else f"Le {french_date()}"
    objet = f"**Objet : Candidature au poste de {f['target']}**" if f["target"] else "**Objet : Candidature**"
    return "\n".join(sender) + "\n\n" + "\n".join(recipient) + "\n\n" + date_line + "\n\n" + objet + "\n\n---\n"