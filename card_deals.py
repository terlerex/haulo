"""
Achat-revente v2 — fiches carte (calcul inversé) et commandes d'import Japon.

Ce module est indépendant de `deals.py` (chantier 5, laissé tel quel) : nouvelles
tables, nouveaux réglages, nouvelle logique. Rien n'est codé en dur dans les
calculs : tout vient de `settings` (clé 'card_deal_settings'), avec les défauts
ci-dessous si absents.

Sources des taux par défaut (vérifiés en ligne le 2026-08-22, cf. commentaires
sur chaque valeur ; à défaut de source fiable, la valeur est laissée à 0) :
  - TVA France 20% : https://www.l-expert-comptable.com/a/529638
  - eBay FR, catégorie cartes à collectionner, 13,25% + 0,42% frais
    réglementaires (= 13,67% effectif) + 0,35€/commande :
    https://www.ebay.fr/help/selling/fees-credits-invoices/...-4822
  - Cardmarket 5%, plafonné 100€/article : https://project151.fr/vendre-cartes-pokemon-cardmarket
  - Vinted Protection Acheteur 0,70€ fixe + 5% du prix article (hors port),
    payée par l'ACHETEUR : https://fripio.app/blog/frais-protection-acheteur-vinted-2026
  - Spread de change PayPal réel ~3-4% (pas 1,5%) : https://wise.com/fr/blog/frais-de-change-paypal
  - Droits de douane : réforme UE au 1er juillet 2026 (suppression du seuil de
    franchise à 150€, remplacé par un forfait de 3€/catégorie tarifaire pour les
    envois IOSS). Pas de taux générique fiable pour des cartes à jouer sous ce
    nouveau régime → laissé à 0% par défaut, éditable.
"""

from __future__ import annotations

from datetime import date

DEFAULT_VERIFIED_DATE = "2026-08-22"

BUY_PLATFORMS = {"ebay", "vinted", "cardmarket", "japan"}
SELL_PLATFORMS = {"ebay", "vinted", "cardmarket"}

DEFAULT_CARD_SETTINGS = {
    "profit_target_pct": 30.0,     # objectif de bénéfice par défaut (marge sur coût, pas sur prix de vente)
    "low_margin_alert_pct": 20.0,  # seuil d'alerte marge faible (import Japon)
    "japan_lot_size": 10,          # taille de lot de référence pour diluer les frais fixes du proxy
    "fx_spread_pct": 3.0,          # majoration réelle constatée (PayPal ~3-4%), pas le taux interbancaire nu
    "import": {
        "vat_rate": 20.0,       # TVA France standard
        "duty_rate": 0.0,       # droits de douane, % — pas de grille fiable pour les cartes, laissé à 0
        "carrier_fee": 20.0,    # frais de dossier transporteur, € fixe par colis (15-30€ usuel)
        "ioss_threshold": 150.0,
        "verified_at": DEFAULT_VERIFIED_DATE,
    },
    # Frais à la REVENTE (utilisés pour le calcul inversé fiche carte ET les
    # lignes de commande d'import : net encaissé = prix x (1-pct) - fixe, plafonné si "cap").
    "sell_fees": {
        "ebay":       {"pct": 13.67, "fixed": 0.35, "cap": None, "label": "eBay (cartes à collectionner)"},
        "vinted":     {"pct": 0.0,   "fixed": 0.0,  "cap": None, "label": "Vinted"},
        "cardmarket": {"pct": 5.0,   "fixed": 0.0,  "cap": 100.0, "label": "Cardmarket"},
    },
    # Frais à l'ACHAT (utilisés pour le back-solve du prix d'achat max par plateforme).
    "buy_fees": {
        "vinted":     {"protection_pct": 5.0, "protection_fixed": 0.70, "default_shipping": 0.0,
                        "label": "Vinted"},
        "ebay":       {"default_shipping": 0.0, "label": "eBay"},
        "cardmarket": {"default_shipping": 0.0, "label": "Cardmarket"},
        "japan":      {"default_shipping": 3.0, "label": "Proxy Japon"},
    },
}


def merge_card_settings(stored: dict | None) -> dict:
    """Merge additif des réglages stockés avec les défauts (rétrocompatible)."""
    s = {k: v for k, v in DEFAULT_CARD_SETTINGS.items()
         if k not in ("import", "sell_fees", "buy_fees")}
    if stored:
        s.update({k: v for k, v in stored.items()
                   if k not in ("import", "sell_fees", "buy_fees")})
    s["import"] = {**DEFAULT_CARD_SETTINGS["import"], **(stored.get("import") if stored else {} or {})}
    s["sell_fees"] = {k: {**v} for k, v in DEFAULT_CARD_SETTINGS["sell_fees"].items()}
    s["buy_fees"] = {k: {**v} for k, v in DEFAULT_CARD_SETTINGS["buy_fees"].items()}
    if stored:
        for k, v in (stored.get("sell_fees") or {}).items():
            if k in s["sell_fees"] and isinstance(v, dict):
                s["sell_fees"][k].update(v)
        for k, v in (stored.get("buy_fees") or {}).items():
            if k in s["buy_fees"] and isinstance(v, dict):
                s["buy_fees"][k].update(v)
    return s


# --------------------------------------------------------------- percentiles

def percentiles(values: list) -> dict:
    """P25/médiane/P75 par interpolation linéaire (méthode "linear", comme numpy
    par défaut). Choisi plutôt que min/max : une vente accidentelle (soldée,
    mauvais état non signalé...) ne doit pas fausser la fourchette de revente."""
    vals = sorted(float(v) for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return {"p25": None, "median": None, "p75": None, "n": 0}
    if n == 1:
        return {"p25": vals[0], "median": vals[0], "p75": vals[0], "n": 1}

    def q(p):
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return vals[lo] + (vals[hi] - vals[lo]) * frac

    return {"p25": round(q(0.25), 2), "median": round(q(0.5), 2), "p75": round(q(0.75), 2), "n": n}


def _days_ago(d: str) -> float:
    try:
        return max(0.0, (date.today() - date.fromisoformat(d[:10])).days)
    except Exception:
        return 9999.0


def resale_range_from_comps(comps: list[dict], window_days: int = 90) -> dict:
    """Fourchette de revente à partir des relevés d'un item lié, sur les
    `window_days` derniers jours (relevés non exclus, prix > 0). Même fenêtre
    que le reste de l'appli (analyse() dans app.py) pour rester cohérent."""
    live = [c for c in comps
            if not c.get("excluded") and float(c.get("price") or 0) > 0
            and _days_ago(c.get("date", "")) <= window_days]
    return percentiles([c["price"] for c in live])


# ------------------------------------------------------------- fiche carte

def net_from_resale(price: float, sell_fee: dict, my_shipping_cost: float) -> dict:
    """N = P x (1-f) - F - E : net encaissé pour un prix de revente P donné,
    f/F = commission/frais fixe de la plateforme de revente, E = mon coût
    d'envoi + emballage à la revente (à ma charge, pas celui de l'acheteur)."""
    pct = float(sell_fee.get("pct", 0)) / 100
    fixed = float(sell_fee.get("fixed", 0))
    cap = sell_fee.get("cap")
    commission = price * pct + fixed
    if cap is not None:
        commission = min(commission, float(cap))
    net = price - commission - my_shipping_cost
    return {"price": price, "commission": round(commission, 2),
            "my_shipping_cost": round(my_shipping_cost, 2), "net": round(net, 2)}


def cost_max(net: float, profit_target_pct: float) -> float:
    """C_max = N / (1+m) : coût de revient total maximum acceptable pour
    respecter l'objectif de bénéfice m (%, sur le COÛT, pas sur le prix de
    vente — 30% veut dire "je récupère 130% de ce que j'ai investi"), pas
    l'inverse (erreur classique : confondre marge sur coût et marge sur prix)."""
    return net / (1 + profit_target_pct / 100)


def buy_max(platform: str, c_max: float, buy_fees: dict, import_params: dict,
            lot_size: int, port: float | None = None, fx_rate: float | None = None,
            fx_spread_pct: float = 0.0) -> dict:
    """Back-solve : à partir du coût de revient max (C_max), le prix d'achat
    affiché maximum sur `platform`. Chaque plateforme a sa propre remontée de
    frais d'achat (cf. docstring du module pour les sources)."""
    bf = buy_fees.get(platform, {})
    p = port if port is not None else float(bf.get("default_shipping", 0))

    if platform == "vinted":
        prot_pct = float(bf.get("protection_pct", 0)) / 100
        prot_fixed = float(bf.get("protection_fixed", 0))
        a_max = (c_max - p - prot_fixed) / (1 + prot_pct) if (1 + prot_pct) else 0.0
        return {"platform": platform, "displayed": round(a_max, 2), "all_in": round(c_max, 2),
                "port": round(p, 2), "currency": "EUR"}

    if platform in ("ebay", "cardmarket"):
        a_max = c_max - p
        return {"platform": platform, "displayed": round(a_max, 2), "all_in": round(c_max, 2),
                "port": round(p, 2), "currency": "EUR"}

    if platform == "japan":
        n_lot = max(1, int(lot_size or 1))
        dossier_share = float(import_params.get("carrier_fee", 0)) / n_lot
        duty = float(import_params.get("duty_rate", 0)) / 100
        vat = float(import_params.get("vat_rate", 0)) / 100
        port_share = p  # `port` déjà exprimé "par carte" pour le proxy (cf. réglages)
        a_eur = (c_max - dossier_share) / ((1 + duty) * (1 + vat)) - port_share
        a_jpy = None
        if fx_rate:
            eff_rate = fx_rate * (1 + fx_spread_pct / 100)  # le spread coûte plus cher en EUR par yen
            a_jpy = round(a_eur / eff_rate, 0) if eff_rate else None
        return {"platform": platform, "displayed": round(a_eur, 2), "all_in": round(c_max, 2),
                "port": round(port_share, 2), "currency": "EUR", "displayed_jpy": a_jpy,
                "dossier_share": round(dossier_share, 2), "fx_rate": fx_rate}

    return {"platform": platform, "displayed": round(c_max - p, 2), "all_in": round(c_max, 2),
            "port": round(p, 2), "currency": "EUR"}


def buy_cost_from_listing(platform: str, price: float, shipping: float, buy_fees: dict,
                           import_params: dict, lot_size: int,
                           fx_rate: float | None = None, fx_spread_pct: float = 0.0,
                           in_jpy: bool = False) -> float:
    """Sens inverse de buy_max : coût de revient réel total pour une annonce
    déjà trouvée (prix affiché + port réels), utilisé pour confronter une
    annonce au calcul."""
    bf = buy_fees.get(platform, {})
    if platform == "vinted":
        prot = price * float(bf.get("protection_pct", 0)) / 100 + float(bf.get("protection_fixed", 0))
        return price + shipping + prot
    if platform in ("ebay", "cardmarket"):
        return price + shipping
    if platform == "japan":
        price_eur = price
        if in_jpy and fx_rate:
            price_eur = price * fx_rate * (1 + fx_spread_pct / 100)
        n_lot = max(1, int(lot_size or 1))
        dossier_share = float(import_params.get("carrier_fee", 0)) / n_lot
        duty = float(import_params.get("duty_rate", 0)) / 100
        vat = float(import_params.get("vat_rate", 0)) / 100
        base = price_eur + shipping
        return base * (1 + duty) * (1 + vat) + dossier_share
    return price + shipping


def build_card_sheet_view(sheet: dict, listings: list[dict], settings: dict,
                           resale_stats: dict, fx_rate: float | None = None) -> dict:
    """Vue complète d'une fiche carte : C_max prudent/optimiste, prix d'achat
    max par plateforme (les 4), et confrontation de chaque annonce suivie."""
    sell_fee = settings["sell_fees"].get(sheet["resale_platform"], {})
    m = float(sheet.get("profit_target_pct") or settings["profit_target_pct"])
    e = float(sheet.get("resale_shipping_cost") or 0) + float(sheet.get("packaging_cost") or 0)

    p25 = resale_stats.get("p25")
    p75 = resale_stats.get("p75")
    scenarios = {}
    for label, price in (("prudent", p25), ("optimiste", p75)):
        if price is None:
            scenarios[label] = None
            continue
        net = net_from_resale(price, sell_fee, e)
        cmax = cost_max(net["net"], m)
        rows = []
        for plat in ("ebay", "vinted", "cardmarket", "japan"):
            rows.append(buy_max(plat, cmax, settings["buy_fees"], settings["import"],
                                 settings["japan_lot_size"], fx_rate=fx_rate,
                                 fx_spread_pct=settings["fx_spread_pct"]))
        scenarios[label] = {"resale_price": price, "net": net, "c_max": round(cmax, 2), "rows": rows}

    listing_checks = []
    prudent = scenarios.get("prudent")
    for lst in listings:
        plat = lst["platform"]
        in_jpy = plat == "japan"
        total_cost = buy_cost_from_listing(
            plat, float(lst["price"]), float(lst.get("shipping") or 0),
            settings["buy_fees"], settings["import"], settings["japan_lot_size"],
            fx_rate=fx_rate, fx_spread_pct=settings["fx_spread_pct"], in_jpy=in_jpy,
        )
        verdict = None
        gap = None
        real_margin_pct = None
        if prudent:
            c_max = prudent["c_max"]
            gap = round(c_max - total_cost, 2)
            verdict = gap >= 0
            if total_cost > 0:
                net_at_p25 = prudent["net"]["net"]
                real_margin_pct = round((net_at_p25 - total_cost) / total_cost * 100, 1)
        listing_checks.append({
            **lst, "total_cost": round(total_cost, 2), "verdict": verdict,
            "gap": gap, "real_margin_pct": real_margin_pct,
        })

    return {"resale_stats": resale_stats, "scenarios": scenarios,
            "listings": listing_checks, "sell_fee": sell_fee, "profit_target_pct": m}


# ------------------------------------------------------- import Japon (commande)

def convert_jpy(amount_jpy: float, fx_rate: float, fx_spread_pct: float) -> float:
    """JPY -> EUR au taux réel constaté (spread inclus, toujours défavorable à
    l'acheteur : on paie plus d'EUR par yen que le taux interbancaire nu)."""
    return amount_jpy * fx_rate * (1 + fx_spread_pct / 100)


def tax_cascade(valeur_douane: float, duty_rate_pct: float, vat_rate_pct: float,
                 carrier_fee: float, ioss_enabled: bool) -> dict:
    """Cascade fiscale, DANS L'ORDRE (la base TVA inclut les droits : piège
    classique si on les calcule en parallèle plutôt qu'en cascade) :
      1. valeur en douane = articles + transport/assurance jusqu'à la frontière UE (déjà en EUR, passé en argument)
      2. droits de douane = valeur en douane x taux
      3. base TVA = valeur en douane + droits
      4. TVA = base TVA x taux
      5. frais de dossier transporteur, fixe par colis
    IOSS ("TVA réglée au paiement") neutralise UNIQUEMENT les étapes 4 et 5 —
    PAS les droits de douane (étape 2), qui restent dus dans tous les cas."""
    duty = valeur_douane * duty_rate_pct / 100
    base_tva = valeur_douane + duty
    if ioss_enabled:
        vat = 0.0
        dossier = 0.0
    else:
        vat = base_tva * vat_rate_pct / 100
        dossier = carrier_fee
    return {
        "valeur_douane": round(valeur_douane, 2), "duty": round(duty, 2),
        "base_tva": round(base_tva, 2), "vat": round(vat, 2), "dossier": round(dossier, 2),
        "total": round(valeur_douane + duty + vat + dossier, 2),
    }


def _round_alloc(target: float, weights: list[float]) -> list[float]:
    """Répartit `target` (déjà arrondi au centime) au prorata de `weights`,
    arrondi ligne par ligne, reliquat d'arrondi ajouté à la ligne de plus
    fort poids — garantit que la somme des lignes reconstitue `target` au
    centime près, quel que soit le nombre de lignes."""
    n = len(weights)
    if n == 0:
        return []
    total_w = sum(weights) or 1.0
    raw = [target * (w / total_w) for w in weights]
    rounded = [round(x, 2) for x in raw]
    remainder = round(target - sum(rounded), 2)
    idx_max = max(range(n), key=lambda i: weights[i])
    rounded[idx_max] = round(rounded[idx_max] + remainder, 2)
    return rounded


def allocate_lines(lines: list[dict], order_total_extra: float, split_mode: str) -> list[float]:
    """Répartit `order_total_extra` (taxes + frais, HORS valeur des articles
    déjà connue par ligne) sur les lignes, au prorata de la valeur (mode
    "value", exact pour TVA/douane) ou à parts égales par unité (mode "equal").
    Le reliquat d'arrondi part sur la ligne la plus chère (au centime près, la
    somme des lignes doit reconstituer le total exact)."""
    if not lines:
        return []
    total_qty = sum(int(l["qty"]) for l in lines)
    if split_mode == "equal":
        weights = [int(l["qty"]) for l in lines]
    else:
        weights = [float(l["unit_price_eur"]) * int(l["qty"]) for l in lines]
    return _round_alloc(round(order_total_extra, 2), weights)


def build_import_order_view(order: dict, lines: list[dict], settings: dict,
                             fx_rate: float | None) -> dict:
    """Vue complète d'une commande d'import : totaux + détail par ligne. Les
    montants "reçus" (order.received_*) écrasent les montants estimés dans le
    calcul final si présents (recalcul post-réception, delta affiché à part)."""
    rate = order.get("fx_rate") or fx_rate
    spread = order.get("fx_spread_pct")
    spread = settings["fx_spread_pct"] if spread is None else float(spread)

    enriched = []
    total_articles_eur = 0.0
    for l in lines:
        unit_eur = convert_jpy(float(l["unit_price_jpy"] or 0), rate, spread) if rate else 0.0
        enriched.append({**l, "unit_price_eur": round(unit_eur, 4)})
        total_articles_eur += unit_eur * int(l["qty"])

    fee_proxy = float(order.get("fee_proxy_pct") if order.get("fee_proxy_pct") is not None else 0)
    fee_domestic = convert_jpy(float(order.get("fee_domestic_jpy") or 0), rate, spread) if rate else 0.0
    fee_consolidation = convert_jpy(float(order.get("fee_consolidation_jpy") or 0), rate, spread) if rate else 0.0
    fee_intl = convert_jpy(float(order.get("fee_intl_shipping_jpy") or 0), rate, spread) if rate else 0.0
    fee_payment_pct = float(order.get("fee_payment_pct") if order.get("fee_payment_pct") is not None else 0)

    proxy_commission_eur = total_articles_eur * fee_proxy / 100
    payment_fee_eur = (total_articles_eur + fee_domestic + fee_consolidation + fee_intl) * fee_payment_pct / 100
    # Frais de service (non taxables, hors assiette douane) : commission proxy,
    # port domestique JP, consolidation, frais de paiement. Distincts du port
    # international qui, lui, entre dans la valeur en douane (étape 1).
    service_fees = proxy_commission_eur + fee_domestic + fee_consolidation + payment_fee_eur

    valeur_douane = total_articles_eur + fee_intl
    ip = order.get("import_params") or settings["import"]
    # order.get(k, default) ne retombe PAS sur `default` quand la clé existe en
    # base avec une valeur NULL (colonnes nullable) : vérification explicite.
    def _override(key, fallback):
        v = order.get(key)
        return v if v is not None else fallback
    duty_rate = _override("duty_rate_pct", ip.get("duty_rate", 0))
    vat_rate = _override("vat_rate_pct", ip.get("vat_rate", 0))
    carrier_fee = _override("carrier_fee_eur", ip.get("carrier_fee", 0))
    ioss = bool(order.get("ioss_enabled"))

    use_received = order.get("status") == "recue" and order.get("received_duty_eur") is not None
    if use_received:
        cascade = {
            "valeur_douane": round(valeur_douane, 2),
            "duty": round(float(order.get("received_duty_eur") or 0), 2),
            "base_tva": None,
            "vat": round(float(order.get("received_vat_eur") or 0), 2),
            "dossier": round(float(order.get("received_carrier_fee_eur") or 0), 2),
        }
        cascade["total"] = round(valeur_douane + cascade["duty"] + cascade["vat"] + cascade["dossier"], 2)
    else:
        cascade = tax_cascade(valeur_douane, float(duty_rate or 0), float(vat_rate or 0),
                               float(carrier_fee or 0), ioss)

    order_total_extra = fee_intl + cascade["duty"] + cascade["vat"] + cascade["dossier"] + service_fees - fee_intl
    # fee_intl est déjà DANS valeur_douane (donc dans le total ci-dessus) : on
    # répartit tout ce qui n'est pas la valeur article elle-même.
    total_extra_to_allocate = (cascade["duty"] + cascade["vat"] + cascade["dossier"]
                                + service_fees + fee_intl)

    # Répartition en deux temps, chacun cent-exact (_round_alloc) : la valeur
    # article elle-même (déjà connue par ligne mais re-arrondie proprement)
    # et les frais/taxes. La somme des deux, par ligne, reconstitue donc le
    # total de commande au centime près (exigé pour la vérification comptable).
    article_weights = [l["unit_price_eur"] * int(l["qty"]) for l in enriched]
    article_alloc = _round_alloc(round(total_articles_eur, 2), article_weights)
    alloc = allocate_lines(enriched, total_extra_to_allocate, order.get("split_mode") or "value")
    sell_fees = settings["sell_fees"]
    line_rows = []
    for l, article_total, extra in zip(enriched, article_alloc, alloc):
        qty = int(l["qty"])
        line_total = round(article_total + extra, 2)
        unit_landed = round(line_total / qty, 2) if qty else 0.0
        target = l.get("resale_target_eur")
        row = {**l, "article_total": article_total, "landed_extra_total": round(extra, 2),
               "landed_total": line_total, "unit_landed_cost": unit_landed}
        if target:
            sf = sell_fees.get(l.get("resale_platform") or "", {})
            net = net_from_resale(float(target), sf, 0.0)["net"]
            profit_unit = net - unit_landed
            profit_total_line = round(net * qty - line_total, 2)  # exact (base landed_total, pas unit arrondi x qty)
            row["net_after_fees"] = round(net, 2)
            row["profit_unit"] = round(profit_unit, 2)
            row["profit_pct"] = round(profit_unit / unit_landed * 100, 1) if unit_landed else None
            row["profit_total"] = profit_total_line
        else:
            row["net_after_fees"] = row["profit_unit"] = row["profit_pct"] = row["profit_total"] = None
        line_rows.append(row)

    line_rows.sort(key=lambda r: (r["profit_pct"] is None, -(r["profit_pct"] or 0)))

    grand_total = total_articles_eur + total_extra_to_allocate
    resale_total = sum(r["net_after_fees"] or 0 for r in line_rows)
    profit_total = sum(r["profit_total"] or 0 for r in line_rows)
    low_threshold = _override("low_margin_alert_pct", settings["low_margin_alert_pct"])
    n_flagged = sum(1 for r in line_rows if r["profit_pct"] is not None and r["profit_pct"] < low_threshold)

    return {
        "fx_rate": rate, "fx_spread_pct": spread,
        "total_articles_eur": round(total_articles_eur, 2),
        "service_fees": {"proxy_commission": round(proxy_commission_eur, 2),
                          "domestic_shipping": round(fee_domestic, 2),
                          "consolidation": round(fee_consolidation, 2),
                          "intl_shipping": round(fee_intl, 2),
                          "payment_fee": round(payment_fee_eur, 2)},
        "cascade": cascade,
        "grand_total_eur": round(grand_total, 2),
        "resale_total_eur": round(resale_total, 2),
        "profit_total_eur": round(profit_total, 2),
        "margin_pct": round(profit_total / grand_total * 100, 1) if grand_total else None,
        "n_flagged": n_flagged,
        "low_margin_alert_pct": low_threshold,
        "lines": line_rows,
        "using_received_amounts": use_received,
        "sum_check": round(sum(r["landed_total"] for r in line_rows), 2),
    }
