"""
Gestion du stock d'achat-revente : cycle de vie d'un exemplaire (une ligne =
une carte, jamais une quantité), délais réels, KPI, et l'algorithme "Pick a
card". Module indépendant de card_deals.py, mais réutilise sa logique de
frais de revente (net_from_resale) — aucun calcul de frais dupliqué.

Statuts (pipeline linéaire, deux sorties) :
    achete -> en_cours_import -> en_stock -> en_vente -> vendu
    (sortie) retourne | conserve
"""

from __future__ import annotations

from datetime import date, datetime
from statistics import median, pstdev

import card_deals as card_deals_mod

STATUSES = ["achete", "en_cours_import", "en_stock", "en_vente", "vendu", "retourne", "conserve"]
ACTIVE_STATUSES = {"achete", "en_cours_import", "en_stock", "en_vente"}
# Ordre d'avancement "normal" pour le bouton une-touche "faire avancer" côté UI.
FORWARD_FLOW = ["achete", "en_cours_import", "en_stock", "en_vente", "vendu"]


def _parse(at: str) -> datetime:
    try:
        return datetime.fromisoformat(at)
    except Exception:
        return datetime.fromisoformat(at[:10])


def entered_at(events: list[dict]) -> dict:
    """Première date d'entrée dans chaque statut, triée par `at`. Si un statut
    a été corrigé après coup (édition de `at`), c'est cette valeur stockée qui
    compte — pas de cache, tout est recalculé depuis les événements bruts."""
    ordered = sorted(events, key=lambda e: e["at"])
    seen: dict[str, str] = {}
    for e in ordered:
        st = e["to_status"]
        if st not in seen:
            seen[st] = e["at"]
    return seen


def compute_delays(events: list[dict]) -> dict:
    """Trois délais, séparément, en jours. None si l'étape n'a pas eu lieu
    (ex. pas d'étape import pour un achat domestique) — jamais confondu avec 0."""
    ent = entered_at(events)

    def diff(a: str, b: str):
        if a not in ent or b not in ent:
            return None
        d = (_parse(ent[b]) - _parse(ent[a])).total_seconds() / 86400
        return round(d, 1) if d >= 0 else None

    return {
        "import_days": diff("en_cours_import", "en_stock"),
        "listing_days": diff("en_stock", "en_vente"),
        "sale_days": diff("en_vente", "vendu"),
        "entered_at": ent,
    }


def days_in_current_status(status: str, events: list[dict]) -> float | None:
    ent = entered_at(events)
    if status not in ent:
        return None
    return round((datetime.now() - _parse(ent[status])).total_seconds() / 86400, 1)


# ------------------------------------------------------------------- vente

def compute_sale_net(price: float, platform: str, settings: dict) -> dict:
    """Frais à la vente calculés depuis le profil de plateforme déjà utilisé
    par les fiches carte (card_deals.sell_fees) — aucun nouveau barème."""
    sf = settings["sell_fees"].get(platform, {})
    return card_deals_mod.net_from_resale(price, sf, my_shipping_cost=0.0)


# -------------------------------------------------------------------- KPI

def build_kpis(rows: list[dict], events_by_stock: dict[str, list[dict]]) -> dict:
    """rows = lignes stock_items (dict), events_by_stock = {stock_id: [event,...]}."""
    active = [r for r in rows if r["status"] in ACTIVE_STATUSES]
    sold = [r for r in rows if r["status"] == "vendu"]

    n_active = len(active)
    capital = sum(float(r["cost_basis"] or 0) for r in active)

    now = datetime.now()
    sales_30 = 0
    for r in sold:
        delays = compute_delays(events_by_stock.get(r["id"], []))
        vendu_at = delays["entered_at"].get("vendu")
        if vendu_at and (now - _parse(vendu_at)).days <= 30:
            sales_30 += 1

    revenue = sum(float(r["sale_price"] or 0) for r in sold)
    net_profit = sum(float(_effective_net(r) or 0) - float(r["cost_basis"] or 0) for r in sold)

    sale_days_list = []
    price_gap_list = []
    for r in sold:
        d = compute_delays(events_by_stock.get(r["id"], []))
        if d["sale_days"] is not None:
            sale_days_list.append(d["sale_days"])
        if r.get("target_price") and r.get("sale_price"):
            price_gap_list.append((float(r["sale_price"]) - float(r["target_price"])) / float(r["target_price"]) * 100)

    def with_n(value, n, unit=""):
        return {"value": value, "n": n, "indicative": n < 10}

    return {
        "n_active": n_active,
        "capital_immobilise": round(capital, 2),
        "sales_30d": sales_30,
        "sales_per_day_30d": round(sales_30 / 30, 2),
        "revenue_realized": with_n(round(revenue, 2), len(sold)),
        "net_profit_realized": with_n(round(net_profit, 2), len(sold)),
        "median_sale_days": with_n(round(median(sale_days_list), 1) if sale_days_list else None, len(sale_days_list)),
        "avg_price_gap_pct": with_n(round(sum(price_gap_list) / len(price_gap_list), 1) if price_gap_list else None, len(price_gap_list)),
        "n_total_sold": len(sold),
    }


def _effective_net(row: dict) -> float | None:
    if row.get("sale_net") is not None:
        return float(row["sale_net"])
    return None


# ------------------------------------------------------------- pick a card

MIN_SALES_FOR_RENDEMENT = 15
PRICE_BRACKETS = [(0, 20), (20, 50), (50, 100), (100, 300), (300, float("inf"))]


def _bracket(price: float) -> tuple:
    for lo, hi in PRICE_BRACKETS:
        if lo <= price < hi:
            return (lo, hi)
    return PRICE_BRACKETS[-1]


def estimate_sale_delay(candidate: dict, sold_rows: list[dict], events_by_stock: dict,
                         market_sales_per_month: float | None) -> dict:
    """Délai de vente estimé, dans l'ordre : ventes de la même carte, ventes
    de cartes similaires (type+grade+tranche de prix), volume marché."""
    same = [r for r in sold_rows if r.get("linked_item_id") and r["linked_item_id"] == candidate.get("linked_item_id")]
    same_days = [compute_delays(events_by_stock.get(r["id"], []))["sale_days"] for r in same]
    same_days = [d for d in same_days if d is not None]
    if len(same_days) >= 1:
        return {"days": round(median(same_days), 1), "n": len(same_days), "source": "ventes_meme_carte"}

    price_ref = candidate.get("target_price") or candidate.get("est_value") or 0
    br = _bracket(float(price_ref or 0))
    similar = [r for r in sold_rows if r.get("type") == candidate.get("type")
               and (r.get("grade") or "") == (candidate.get("grade") or "")
               and _bracket(float(r.get("target_price") or r.get("sale_price") or 0)) == br]
    similar_days = [compute_delays(events_by_stock.get(r["id"], []))["sale_days"] for r in similar]
    similar_days = [d for d in similar_days if d is not None]
    if len(similar_days) >= 1:
        return {"days": round(median(similar_days), 1), "n": len(similar_days), "source": "ventes_similaires"}

    if market_sales_per_month and market_sales_per_month > 0:
        return {"days": round(30 / market_sales_per_month, 1), "n": 0, "source": "volume_marche"}
    return {"days": None, "n": 0, "source": None}


def confidence_level(n: int, dispersion_pct: float | None, days_list: list[float] | None = None) -> str:
    """Même échelle que la fiabilité d'estimation (haute/moyenne/faible),
    fondée sur le nombre de ventes observées et leur dispersion."""
    score = (2 if n >= 8 else 1 if n >= 3 else 0)
    if dispersion_pct is not None:
        score += (2 if dispersion_pct < 25 else 1 if dispersion_pct < 50 else 0)
    else:
        score += 0
    if score >= 4:
        return "haute"
    if score >= 2:
        return "moyenne"
    return "faible"


def build_pick_a_card(candidates: list[dict], sold_rows: list[dict], events_by_stock: dict,
                       settings: dict, budget: float | None = None) -> dict:
    """candidates : liste de {kind: 'sheet'|'watch', ..., cost_basis, net_estime,
    linked_item_id, type, grade, target_price, est_value, market_sales_per_month}.
    Le ROI/rendement est calculé ici ; la construction des candidats (à partir
    des fiches carte et de la veille) se fait côté app.py."""
    n_total_sold = len(sold_rows)
    theoretical_mode = n_total_sold < MIN_SALES_FOR_RENDEMENT

    scored = []
    for c in candidates:
        cost = float(c.get("cost_basis") or 0)
        net = c.get("net_estime")
        if not cost or net is None:
            continue
        roi = (net - cost) / cost

        if theoretical_mode:
            scored.append({**c, "roi_net_pct": round(roi * 100, 1), "rendement_pct": None,
                           "delay": None, "confidence": "faible",
                           "reason": f"Classement sur marge théorique (moins de {MIN_SALES_FOR_RENDEMENT} ventes en base) : "
                                     f"ROI net {round(roi*100,1)}% sur {cost:.2f}€ investis."})
            continue

        delay = estimate_sale_delay(c, sold_rows, events_by_stock, c.get("market_sales_per_month"))
        if not delay["days"]:
            continue
        rendement = roi * 365 / delay["days"]
        conf = confidence_level(delay["n"], None)
        src_label = {"ventes_meme_carte": "ventes de cette carte", "ventes_similaires": "ventes de cartes similaires",
                     "volume_marche": "volume marché"}.get(delay["source"], "estimation")
        reason = (f"ROI net {round(roi*100,1)}% sur {cost:.2f}€ investis, vente estimée en {delay['days']:.0f} jours "
                  f"({delay['n']} {src_label}) → {round(rendement*100)}%/an, confiance {conf}.")
        scored.append({**c, "roi_net_pct": round(roi * 100, 1), "rendement_pct": round(rendement * 100, 1),
                       "delay_days": delay["days"], "delay_n": delay["n"], "delay_source": delay["source"],
                       "confidence": conf, "reason": reason})

    sort_key = "roi_net_pct" if theoretical_mode else "rendement_pct"
    scored.sort(key=lambda c: c[sort_key] if c[sort_key] is not None else -1e9, reverse=True)

    result = {"theoretical_mode": theoretical_mode, "n_total_sold": n_total_sold, "top": scored[:5]}

    if budget is not None and budget > 0:
        picked, remaining = [], budget
        for c in scored:
            cost = float(c.get("cost_basis") or 0)
            if cost <= remaining:
                picked.append(c)
                remaining -= cost
        result["budget"] = {"amount": budget, "picks": picked, "remaining": round(remaining, 2),
                             "total_cost": round(budget - remaining, 2)}

    return result
