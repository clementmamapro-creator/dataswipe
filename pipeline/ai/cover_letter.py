"""cover_letter.py — lettre de motivation fidèle au CV, niveau imposé par le code."""
from __future__ import annotations

from . import _llm, profile

SYSTEM = """Tu rédiges des lettres de motivation françaises pour un candidat, à partir de son CV et d'une offre.

RÈGLES ABSOLUES :
1. FIDÉLITÉ : n'affirme que ce qui figure dans le CV. Aucune compétence, outil, projet, chiffre, employeur ou durée
   inventés. Si l'offre exige une compétence que le candidat n'a pas, ne prétends pas la maîtriser : tu peux dire
   brièvement qu'il s'y forme ou qu'il apprend vite SEULEMENT si la formation du CV le justifie.
2. NIVEAU : respecte le niveau donné dans « FAITS CALCULÉS ». Ne te présente jamais comme senior ou expert si ce n'est
   pas le cas ; assume le profil réel (alternance, jeune diplômé…) comme une force (motivation, rythme d'apprentissage,
   résultats concrets du CV).
3. COHÉRENCE : n'affirme rien qui contredise le CV adapté ; mêmes compétences, même niveau.
4. FORME : français impeccable, sans mot inventé, sans emojis, ton professionnel et sincère, 250 à 320 mots,
   3 à 4 paragraphes (accroche liée à l'entreprise/poste, preuves tirées du CV, adéquation avec l'offre, conclusion).
   Pas de formules creuses. Ne mets AUCUN en-tête (expéditeur, destinataire, date, objet) : il est ajouté par le système.
   Commence par « Madame, Monsieur, » et termine par « Cordialement, » puis le nom du candidat.
5. TON POSITIF : valorise ce que le candidat a fait. N'écris jamais « je reconnais mes lacunes », « je suis conscient que
   je devrai… », « bien que mon profil soit junior comparé aux X ans demandés » ni aucune phrase d'excuse ou d'auto-critique.
   Ne cite pas le nombre d'années demandé par l'offre. Si une compétence demandée manque, n'en parle pas, ou au plus
   en une courte phrase tournée vers l'avenir et appuyée par la formation du CV.
6. RELECTURE : accords (« ma rigueur », « mes connaissances … constituent »), conjugaison et ponctuation parfaits."""


def generate_cover_letter(cv_text: str, offer) -> str:
    f = profile.facts(cv_text, offer)
    desc = (profile._get(offer, "description", "desc", "snippet") or "")[:6000]
    user = f"""FAITS CALCULÉS :
- Nom : {f['name'] or 'non détecté'}
- Expérience : environ {f['years']} an(s) — {f['wording']}
- Poste visé : {f['target']} chez {f['company'] or 'entreprise non précisée'}

OFFRE :
{desc or f['target']}

CV :
{cv_text}

Rédige la lettre (corps uniquement, avec signature)."""
    body = _llm.complete(SYSTEM, user, max_tokens=1400, temperature=0.4).strip()
    return profile.letter_header(f, profile.contacts(cv_text), offer) + "\n" + body