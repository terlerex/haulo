"""
Achat-revente — moteur de calcul du coût de revient débarqué et du net à la revente.

Toutes les règles métier non triviales sont commentées ci-dessous. Aucun taux
n'est codé en dur dans la logique : ils viennent de `params` (table settings,
clé 'deal_params'), avec des valeurs par défaut raisonnables si absentes.

Notes de vérification des taux (pas d'accès web dans cet environnement) :
  - eBay particulier 10% + 0,35€/commande, Cardmarket 5%, Vinted 0% vendeur :
    valeurs fournies par l'utilisateur, non revérifiées en ligne.
  - Date de "dernière vérification" par défaut = date d'écriture de ce module,
    éditable dans les réglages une fois les vrais taux confirmés.
"""

from __future__ import annotations

from datetime import date

DEFAULT_VERIFIED_DATE = "2026-05-22"  # à mettre à jour si tu revérifies les taux

PLATFORMS_BUY = {"vinted", "ebay", "cardmarket", "japan_proxy", "autre"}
PLATFORMS_SELL = {"vinted", "ebay", "cardmarket"}

DEFAULT_DEAL_PARAMS = {
    "vat_rate": 20.0,          # TVA à l'import, %, paramètre — jamais en dur dans le calcul
    "duty_rate": 0.0,          # droits de douane, %, variable selon le bien — 0 par défaut
    "carrier_fee": 20.0,       # frais de dossier transporteur, € fixe par colis (15-30€ usuel)
    "ioss_threshold": 150.0,   # seuil € en dessous duquel l'IOSS peut s'appliquer
    "verified_at": DEFAULT_VERIFIED_DATE,
    "platform_fees": {
        "vinted":     {"pct": 0.0,  "fixed": 0.0,  "label": "Vinted"},
        "ebay":       {"pct": 10.0, "fixed": 0.35, "label": "eBay particulier"},
        "cardmarket": {"pct": 5.0,  "fixed": 0.0,  "label": "Cardmarket"},
    },
}


def merge_params(stored: dict | None) -> dict:
    """Merge des réglages stockés avec les défauts (rétrocompatible, additif)."""
    p = {k: v for k, v in DEFAULT_DEAL_PARAMS.items() if k != "platform_fees"}
    if stored:
        p.update({k: v for k, v in stored.items() if k != "platform_fees"})
    p["platform_fees"] = {
        k: {**v} for k, v in DEFAULT_DEAL_PARAMS["platform_fees"].items()
    }
    if stored and isinstance(stored.get("platform_fees"), dict):
        for k, v in stored["platform_fees"].items():
            if k in p["platform_fees"] and isinstance(v, dict):
                p["platform_fees"][k].update(v)
    return p


# --------------------------------------------------------------------- coût de revient

def landed_cost(deal: dict, params: dict) -> dict:
    """Coût de revient débarqué, détaillé ligne par ligne.

    Règle stricte : la base taxable (TVA + douane) = prix article + port,
    car la TVA à l'import porte sur les deux (transport inclus dans l'assiette).

    Répartition sur le lot :
      - "value" et "equal" : dans le formulaire actuel, un seul prix couvre tout
        le lot (pas de prix par carte individuelle), donc les deux modes donnent
        aujourd'hui le même résultat = cout_total_lot / qty. Le distinguo prendra
        son sens le jour où chaque unité du lot aura un prix de revente propre
        (répartition alors possible au prorata de ces valeurs) ; le code est déjà
        prêt pour ça via `unit_weights`, non utilisé pour l'instant.
    """
    lot_price = float(deal.get("lot_price") or 0)
    lot_shipping = float(deal.get("lot_shipping") or 0)
    qty = max(1, int(deal.get("qty") or 1))
    is_import = bool(deal.get("is_import"))
    is_ioss = bool(deal.get("is_ioss")) and is_import

    base_taxable = lot_price + lot_shipping

    vat_rate = float(params.get("vat_rate", 0)) / 100
    duty_rate = float(params.get("duty_rate", 0)) / 100
    carrier_fee = float(params.get("carrier_fee", 0))

    if not is_import:
        vat_import = 0.0
        duty = 0.0
        dossier = 0.0
    elif is_ioss:
        # IOSS : la TVA est réglée au moment du paiement (donc pas ajoutée ici,
        # on suppose que lot_price la contient déjà si le proxy l'a facturée).
        # Les droits de douane restent dus même sous IOSS (l'IOSS ne couvre QUE la TVA).
        # Les frais de dossier du transporteur sont neutralisés (pas de dédouanement classique).
        vat_import = 0.0
        duty = base_taxable * duty_rate
        dossier = 0.0
    else:
        vat_import = base_taxable * vat_rate
        duty = base_taxable * duty_rate
        dossier = carrier_fee

    total_lot = lot_price + lot_shipping + vat_import + duty + dossier
    per_unit = total_lot / qty

    return {
        "lot_price": lot_price,
        "lot_shipping": lot_shipping,
        "base_taxable": base_taxable,
        "is_import": is_import,
        "is_ioss": is_ioss,
        "vat_rate_pct": params.get("vat_rate", 0),
        "duty_rate_pct": params.get("duty_rate", 0),
        "vat_import": round(vat_import, 2),
        "duty": round(duty, 2),
        "carrier_fee": round(dossier, 2),
        "total_lot": round(total_lot, 2),
        "qty": qty,
        "per_unit": round(per_unit, 2),
        "split_mode": deal.get("split_mode") or "value",
    }


# ------------------------------------------------------------------- net à la revente

def platform_net(price: float, platform: str, deal: dict, params: dict) -> dict:
    """Net encaissé sur une plateforme, détaillé ligne par ligne.

    Vinted : le VENDEUR ne paie aucune commission (0%). Le port sortant et
    l'emballage restent à sa charge. La Protection Acheteur est payée par
    l'acheteur EN PLUS du prix affiché, donc n'entre jamais dans ce calcul.

    eBay particulier : commission = (prix + port si buyer_pays_shipping) * pct
    + frais fixe par commande. "Frais de port facturés inclus" signifie que
    si l'acheteur paie le port en plus du prix, eBay prend AUSSI sa commission
    sur ce port — d'où l'assiette élargie quand buyer_pays_shipping=True.
    Si c'est toi qui paies le port sortant (buyer_pays_shipping=False), il ne
    rentre pas dans l'assiette de commission mais reste une charge déduite du net.

    Cardmarket : commission simple sur le prix de vente.
    """
    fees = params.get("platform_fees", {}).get(platform, {"pct": 0, "fixed": 0})
    pct = float(fees.get("pct", 0)) / 100
    fixed = float(fees.get("fixed", 0))

    shipping_out = float(deal.get("resale_shipping_out") or 0)
    packaging = float(deal.get("packaging_cost") or 0)
    buyer_pays = bool(deal.get("buyer_pays_shipping")) and platform == "ebay"

    if platform == "ebay" and buyer_pays:
        assiette = price + shipping_out
        commission = assiette * pct + fixed
        shipping_charge = 0.0  # l'acheteur paie, ça ne te coûte rien
    else:
        assiette = price
        commission = assiette * pct + fixed
        shipping_charge = shipping_out

    net = price - commission - shipping_charge - packaging

    return {
        "platform": platform,
        "price": round(price, 2),
        "commission_pct": fees.get("pct", 0),
        "commission_fixed": fees.get("fixed", 0),
        "commission": round(commission, 2),
        "shipping_out": round(shipping_charge, 2),
        "packaging": round(packaging, 2),
        "buyer_pays_shipping": buyer_pays,
        "net": round(net, 2),
    }


def floor_price(platform: str, cost_per_unit: float, deal: dict, params: dict) -> float:
    """Prix de vente en dessous duquel net(prix) = cost_per_unit (perte).

    Toutes les formules de commission ici sont affines (pct * x + fixe),
    donc résolution directe, pas d'itération nécessaire.
    """
    fees = params.get("platform_fees", {}).get(platform, {"pct": 0, "fixed": 0})
    pct = float(fees.get("pct", 0)) / 100
    fixed = float(fees.get("fixed", 0))
    shipping_out = float(deal.get("resale_shipping_out") or 0)
    packaging = float(deal.get("packaging_cost") or 0)
    buyer_pays = bool(deal.get("buyer_pays_shipping")) and platform == "ebay"

    # net(p) = p - (pct*(p [+shipping_out si buyer_pays]) + fixed) - shipping_charge - packaging = cost
    if platform == "ebay" and buyer_pays:
        # net = p - pct*(p+shipping_out) - fixed - packaging = cost   (shipping_charge=0)
        # p*(1-pct) = cost + fixed + packaging + pct*shipping_out
        num = cost_per_unit + fixed + packaging + pct * shipping_out
        p = num / (1 - pct) if pct < 1 else float("inf")
    else:
        # net = p - pct*p - fixed - shipping_out - packaging = cost
        num = cost_per_unit + fixed + shipping_out + packaging
        p = num / (1 - pct) if pct < 1 else float("inf")
    return round(p, 2)


# --------------------------------------------------------------------------- synthèse

def build_deal_view(deal: dict, params: dict, item_est: float | None = None) -> dict:
    """Vue complète d'une opération : coût de revient, net par plateforme,
    meilleure plateforme, écarts, détail ligne par ligne dépliable."""
    cost = landed_cost(deal, params)
    per_unit = cost["per_unit"]

    resale_prices = deal.get("resale_prices") or {}
    results = []
    for platform in PLATFORMS_SELL:
        price = resale_prices.get(platform)
        if price is None and item_est is not None:
            price = item_est  # reprise de l'estimation de l'item lié si dispo
        if price is None or price <= 0:
            continue
        net_info = platform_net(float(price), platform, deal, params)
        benefice = net_info["net"] - per_unit
        pct_benef = (benefice / per_unit * 100) if per_unit else None
        plancher = floor_price(platform, per_unit, deal, params)
        results.append({
            **net_info,
            "benefice": round(benefice, 2),
            "benefice_pct": round(pct_benef, 1) if pct_benef is not None else None,
            "floor_price": plancher,
            "label": params.get("platform_fees", {}).get(platform, {}).get("label", platform),
        })

    results.sort(key=lambda r: r["benefice"], reverse=True)
    best = results[0] if results else None
    ecarts = []
    if best:
        for r in results[1:]:
            ecarts.append({"platform": r["platform"], "delta": round(best["benefice"] - r["benefice"], 2)})

    return {
        "cost": cost,
        "results": results,
        "best": best,
        "deltas_vs_best": ecarts,
    }
