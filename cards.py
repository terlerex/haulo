"""
Référentiel de cartes : une entrée unique par carte (identité), que les
fiches carte, lignes d'import, lignes de stock et items du portefeuille
référencent par card_id plutôt que de dupliquer nom/set/numéro/langue/grade.

Ce module est pur (aucun accès DB) : normalisation, score de similarité,
et l'algorithme de rapprochement lui-même, qui prend en entrée des listes
de dicts déjà chargées et renvoie des décisions — à app.py de les exécuter.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

AUTO_LINK_THRESHOLD = 0.92
PROPOSAL_THRESHOLD = 0.65


def normalize_text(s: str | None) -> str:
    """Minuscules, accents supprimés, ponctuation/espaces multiples réduits."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_grade(g: str | None) -> str:
    """PSA 10 / psa-10 / PSA10 -> même token. Ne garde que lettres+chiffres."""
    if not g:
        return ""
    s = unicodedata.normalize("NFKD", g)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def normalize_number(n: str | None) -> str:
    """Nettoie les préfixes (n°, #) et les espaces autour du '/' : "n° 199 / 193" -> "199/193"."""
    if not n:
        return ""
    s = n.strip().lower()
    s = re.sub(r"^(n°|no\.?|#)\s*", "", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s+", "", s)
    return s


def identity_key(name: str, set_name: str, number: str, lang: str, grade: str) -> str:
    return "|".join([normalize_text(name), normalize_text(set_name),
                      normalize_number(number), normalize_text(lang), normalize_grade(grade)])


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def similarity(a: dict, b: dict) -> float:
    """Score pondéré : nom 0.5, set 0.2, numéro 0.15, langue 0.15.
    Le grade est un VERROU, pas un critère pondéré : deux grades non vides et
    différents -> score forcé à 0, jamais de rapprochement, même noms identiques."""
    ga, gb = normalize_grade(a.get("grade")), normalize_grade(b.get("grade"))
    if ga and gb and ga != gb:
        return 0.0

    name_s = _ratio(normalize_text(a.get("name")), normalize_text(b.get("name")))
    set_s = _ratio(normalize_text(a.get("set_name")), normalize_text(b.get("set_name")))
    num_a, num_b = normalize_number(a.get("card_number")), normalize_number(b.get("card_number"))
    num_s = 1.0 if (num_a and num_b and num_a == num_b) else (0.5 if (not num_a or not num_b) else 0.0)
    lang_s = 1.0 if normalize_text(a.get("lang")) == normalize_text(b.get("lang")) else 0.0

    return round(name_s * 0.5 + set_s * 0.2 + num_s * 0.15 + lang_s * 0.15, 4)


def classify(score: float) -> str:
    if score >= AUTO_LINK_THRESHOLD:
        return "auto"
    if score >= PROPOSAL_THRESHOLD:
        return "proposal"
    return "none"


def match_best(record: dict, candidates: list[dict]) -> tuple[dict | None, float]:
    """Meilleure carte candidate pour `record`, et son score. candidates =
    liste de dicts {id, name, set_name, card_number, lang, grade, ...}."""
    best, best_score = None, 0.0
    for c in candidates:
        s = similarity(record, c)
        if s > best_score:
            best, best_score = c, s
    return best, best_score


def build_migration_plan(card_sheets: list[dict], unlinked_records: list[dict]) -> dict:
    """Construit le plan de migration à blanc.

    card_sheets : fiches carte existantes (source de vérité), déjà transformées
      en candidats {id (=sheet id), name, set_name, card_number, lang, grade, ...}.
    unlinked_records : items / lignes d'import / lignes de stock sans card_id,
      chacun {table, id, name, set_name, card_number, lang, grade, ...}.

    Renvoie {auto_links, proposals, creations, candidates} — candidates étant
    la liste des futures entrées `cards` (une par fiche + une par création),
    pour que l'appelant (app.py) puisse les créer réellement à l'exécution.
    """
    # Les fiches carte sont la source de vérité : chacune devient une carte candidate.
    candidates = [dict(c) for c in card_sheets]

    auto_links, proposals, creations = [], [], []
    for rec in unlinked_records:
        best, score = match_best(rec, candidates)
        kind = classify(score)
        if kind == "auto" and best is not None:
            auto_links.append({"table": rec["table"], "id": rec["id"], "card_id": best["id"],
                                "score": score, "label": rec.get("name")})
        elif kind == "proposal" and best is not None:
            # Reste une création : le rapprochement définitif se décide dans
            # l'écran de fusion, jamais silencieusement. `rec["id"]` (id de la
            # ligne source) est CONSERVÉ ici, jamais écrasé — c'est lui qui
            # permet à l'exécution de retrouver quelle ligne mettre à jour.
            creations.append(dict(rec))
            proposals.append({"table": rec["table"], "id": rec["id"], "candidate_card_id": best["id"],
                               "score": score, "label_a": rec.get("name"), "label_b": best.get("name")})
        else:
            creations.append(dict(rec))

    return {
        "auto_links": auto_links,
        "proposals": proposals,
        "creations": creations,
        "counts": {"auto": len(auto_links), "proposals": len(proposals), "creations": len(creations)},
    }
