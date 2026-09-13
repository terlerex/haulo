"""
Conversion ponctuelle : items en veille (items.status='watch') -> fiches
carte (card_sheets), en préparation de la suppression de l'onglet Veille.

La Veille n'est pas une table à part : c'est un statut sur `items`, la même
table et le même moteur d'estimation (comps/estimate/analyse) que le
Portefeuille. Ce script NE SUPPRIME NI NE MODIFIE aucun item — il crée une
fiche carte liée (item_id) à chaque item en veille qui n'en a pas déjà une,
pour que la fourchette de revente reste vivante (relevés partagés) plutôt que
figée à l'instant de la conversion.

Exclusion volontaire : un item en veille créé automatiquement comme simple
point d'attache pour les relevés d'un exemplaire de Stock (linked_item_id
d'une ligne stock_items) n'est pas une vraie veille — ce ne sont pas des
cartes à acheter mais de la plomberie interne. Même exclusion que
_pick_a_card_candidates dans app.py.

Idempotent : un item déjà lié à une fiche carte (card_sheets.item_id) est
ignoré silencieusement, donc rejouable sans doublon.

Usage :
    py -3 scripts/convert_veille_to_card_sheets.py            # aperçu, rien n'est écrit
    py -3 scripts/convert_veille_to_card_sheets.py --apply    # exécute réellement
    DB_PATH=/chemin/vers/portfolio.db py -3 scripts/convert_veille_to_card_sheets.py --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402  (chemin ajusté ci-dessus avant l'import)
import cards as cards_mod  # noqa: E402


def _watch_candidates() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Renvoie (à_convertir, plomberie_stock_exclue, déjà_converti, cartes_référentiel)."""
    with app.db() as con:
        watch_items = [dict(r) for r in con.execute(
            "SELECT * FROM items WHERE status='watch' ORDER BY name"
        )]
        stock_linked_ids = {r["linked_item_id"] for r in con.execute(
            "SELECT DISTINCT linked_item_id FROM stock_items WHERE linked_item_id IS NOT NULL"
        )}
        already_converted_ids = {r["item_id"] for r in con.execute(
            "SELECT item_id FROM card_sheets WHERE item_id IS NOT NULL"
        )}
        ref_cards = [dict(r) for r in con.execute(
            "SELECT id, name, set_name, card_number, lang, grade, type FROM cards WHERE merged_into_id IS NULL"
        )]

    to_convert, plumbing, already = [], [], []
    for it in watch_items:
        if it["id"] in stock_linked_ids:
            plumbing.append(it)
        elif it["id"] in already_converted_ids:
            already.append(it)
        else:
            to_convert.append(it)
    return to_convert, plumbing, already, ref_cards


def build_plan() -> dict:
    to_convert, plumbing, already, ref_cards = _watch_candidates()
    entries = []
    for it in to_convert:
        record = {
            "name": it["name"], "set_name": it.get("set_name") or "", "card_number": "",
            "lang": it.get("lang") or "", "grade": it.get("grade") or "", "type": it.get("type") or "loose",
        }
        best, score = cards_mod.match_best(record, ref_cards)
        kind = cards_mod.classify(score)  # "auto" | "proposal" | "none"
        entries.append({"item": it, "match": best, "score": score, "kind": kind})
    return {"entries": entries, "plumbing_excluded": plumbing, "already_converted": already}


def apply_plan(plan: dict) -> list[dict]:
    now = datetime.now().isoformat(timespec="seconds")
    created = []
    with app.db() as con:
        for row in plan["entries"]:
            it = row["item"]
            card_id = row["match"]["id"] if row["kind"] == "auto" and row["match"] else None
            notes = (it.get("notes") or "").strip()
            if it.get("target_price"):
                obj_note = f"Objectif d'achat repris de la veille : {float(it['target_price']):.2f} €"
                notes = f"{notes}\n{obj_note}".strip() if notes else obj_note
            sid = app.nid()
            con.execute(
                "INSERT INTO card_sheets(id, item_id, name, type, grade, lang, set_name, "
                "resale_mode, resale_platform, card_id, notes, status, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, it["id"], it["name"], it.get("type") or "loose", it.get("grade") or "",
                 it.get("lang") or "", it.get("set_name") or "", "auto", "ebay", card_id, notes,
                 "open", now),
            )
            created.append({
                "item_id": it["id"], "item_name": it["name"], "sheet_id": sid,
                "card_id": card_id, "match_kind": row["kind"], "match_score": row["score"],
            })
    return created


def _fmt_item(it: dict) -> str:
    bits = [it["name"]]
    extra = " · ".join(x for x in (it.get("set_name"), it.get("lang"), it.get("grade")) if x)
    if extra:
        bits.append(f"({extra})")
    return " ".join(bits)


def print_report(plan: dict, created: list[dict] | None) -> None:
    entries = plan["entries"]
    print(f"Items en veille trouvés à convertir : {len(entries)}")
    print(f"Exclus (plomberie Stock, jamais de vraies veilles) : {len(plan['plumbing_excluded'])}")
    print(f"Déjà convertis (fiche carte existante, ignorés) : {len(plan['already_converted'])}")
    print()

    by_kind = {"auto": [], "proposal": [], "none": []}
    for e in entries:
        by_kind[e["kind"]].append(e)

    if by_kind["auto"]:
        print(f"-- Rapprochées automatiquement au référentiel ({len(by_kind['auto'])}) --")
        for e in by_kind["auto"]:
            print(f"  {_fmt_item(e['item'])} -> carte référentiel « {e['match']['name']} » (score {e['score']})")
        print()

    if by_kind["proposal"]:
        print(f"-- Rapprochement incertain, fiche créée SANS lien référentiel — à valider dans l'écran de fusion ({len(by_kind['proposal'])}) --")
        for e in by_kind["proposal"]:
            print(f"  {_fmt_item(e['item'])} -> proche de « {e['match']['name']} » (score {e['score']}, sous le seuil auto)")
        print()

    if by_kind["none"]:
        print(f"-- Aucune correspondance, nouvelle fiche créée sans lien référentiel ({len(by_kind['none'])}) --")
        for e in by_kind["none"]:
            print(f"  {_fmt_item(e['item'])}")
        print()

    not_reportable = [e for e in entries if not (e["item"].get("notes") or "").strip()
                       and not e["item"].get("target_price")]
    reportable_target = [e for e in entries if e["item"].get("target_price")]
    if reportable_target:
        print(f"Objectif d'achat reporté en note (pas de champ équivalent sur la fiche carte) : {len(reportable_target)}")
        for e in reportable_target:
            print(f"  {_fmt_item(e['item'])} : {float(e['item']['target_price']):.2f} €")
        print()
    print("Fourchette de prix : rien à reporter séparément — la fiche est liée à l'item (mode automatique), "
          "elle lit les mêmes relevés en continu.")
    print("Liens d'annonce : aucun champ de ce type sur un item en veille dans ce schéma, rien à reporter.")
    print()

    if created is not None:
        print(f"=== APPLIQUÉ : {len(created)} fiche(s) carte créée(s) ===")
        for c in created:
            print(f"  item {c['item_id']} ({c['item_name']}) -> card_sheet {c['sheet_id']}"
                  f"{' lié à la carte ' + c['card_id'] if c['card_id'] else ' (pas de lien référentiel)'}")
    else:
        print("=== APERÇU SEUL : rien n'a été écrit. Relance avec --apply pour exécuter. ===")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Exécute réellement (sinon, aperçu seul).")
    args = parser.parse_args()

    app.init()
    plan = build_plan()
    if not args.apply:
        print_report(plan, created=None)
        return
    created = apply_plan(plan)
    print_report(plan, created=created)


if __name__ == "__main__":
    main()
