from pipeline.matching.cv_parser import parse_cv
from pipeline.matching.data_access import fetch_offers
from pipeline.matching.extract_skills import extract_skills, get_offer_skills
from pipeline.matching.scoring import compute_match_score

CV_PATH = r"C:\Users\PC\OneDrive\Documents\PFE\CV_Clement_Ferry_ChefProjetData.pdf"

cv_text = parse_cv(CV_PATH)
cv_skills = extract_skills(cv_text)
offers = fetch_offers()

candidates = []
for o in offers:
    skills = get_offer_skills(o)
    m = compute_match_score(cv_skills, skills)
    if m.missing_skills and 40 <= m.score < 90:
        candidates.append((m.score, o.get("title"), o.get("company"), o.get("url"), m.matched_skills, m.missing_skills))

candidates.sort(key=lambda x: -x[0])

print(f"{len(candidates)} offres trouvées avec un score entre 40% et 90%\n")
for score, title, company, url, matched, missing in candidates[:8]:
    print(f"[{score}%] {title} — {company}")
    print(f"  ✓ Matché : {', '.join(matched)}")
    print(f"  ✗ Manquant : {', '.join(missing)}")
    print(f"  {url}\n")