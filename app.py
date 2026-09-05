"""
Portefeuille Pokémon — application web personnelle.

Local :
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000

En ligne (Railway, VPS…) : définir les variables d'environnement
    PORTFOLIO_PASSWORD   mot de passe d'accès (obligatoire dès que le site est public)
    DB_PATH              chemin de la base, ex. /data/portfolio.db sur un volume persistant

Sans PORTFOLIO_PASSWORD, l'accès est libre : réservé à un usage sur réseau local.
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

import media as media_mod
import deals as deals_mod
import card_deals as card_deals_mod
import stock as stock_mod
import cards as cards_mod

BASE = Path(__file__).parent
DB = Path(os.environ.get("DB_PATH") or (BASE / "portfolio.db"))
PASSWORD = os.environ.get("PORTFOLIO_PASSWORD", "").strip()
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "90"))
COOKIE = "pkmn_session"

MEDIA = media_mod.media_dir(DB)  # <dossier DB>/media, jamais /data en dur
DEAL_MEDIA = MEDIA / "_deals"     # sous-namespace dédié pour ne pas collisionner avec les item_id
CARD_SHEET_MEDIA = MEDIA / "_card_sheets"  # une seule photo par fiche, même pipeline que items/deals
STOCK_MEDIA = MEDIA / "_stock"             # idem pour les lignes de stock
CARD_MEDIA = MEDIA / "_cards"              # photo de référence du référentiel de cartes

SOURCES = {
    "ebay": ("eBay — vendu", 1.00),
    "cm_sold": ("Cardmarket — vente", 0.95),
    "gcc": ("Graded Card Center", 0.90),
    # Vinted — vendu : vente conclue, prix DÉJÀ NET côté vendeur (pas de commission,
    # la Protection Acheteur est facturée à l'acheteur). Ce point est central pour le
    # calcul du net à la revente (chantier 5), pas pour l'estimation de valeur.
    "vinted_sold": ("Vinted — vendu", 0.90),
    "cm_trend": ("Cardmarket — tendance", 0.80),
    "cm_low": ("Cardmarket — annonce", 0.45),
    # Vinted — annonce : simple listing, souvent optimiste + concurrentiel, poids faible.
    "vinted_listing": ("Vinted — annonce", 0.35),
    "index": ("Pokéindex / indice", 0.40),
    "manual": ("Estimation perso", 0.50),
    # Une vente réelle de TA carte est le meilleur comparable qui existe :
    # poids au niveau du maximum actuel (eBay vendu), jamais en dessous.
    "own_sale": ("Vente perso", 1.00),
}
# Sources qui prouvent une transaction réelle → alimentent le volume de ventes.
# vinted_sold en fait partie ; vinted_listing NON (annonce n'est pas une vente).
SALE_SOURCES = {"ebay", "cm_sold", "gcc", "vinted_sold", "own_sale"}
DEFAULT_SETTINGS = {
    "halfLife": 60,
    "fees": 12.0,
    "trimK": 3.0,
    "weights": {k: w for k, (_, w) in SOURCES.items()},
}

# --------------------------------------------------------------------------- db

def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS items(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'scelle',
                lang TEXT DEFAULT 'FR',
                grade TEXT DEFAULT '',
                set_name TEXT DEFAULT '',
                qty INTEGER NOT NULL DEFAULT 1,
                buy_price REAL NOT NULL DEFAULT 0,
                buy_date TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS comps(
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                price REAL NOT NULL,
                date TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                note TEXT DEFAULT '',
                excluded INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS comps_item ON comps(item_id);
            CREATE TABLE IF NOT EXISTS snapshots(
                d TEXT PRIMARY KEY, value REAL NOT NULL, invested REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS media(
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,        -- <uuid>.webp
                mime TEXT NOT NULL DEFAULT 'image/webp',
                size_bytes INTEGER NOT NULL,
                width INTEGER, height INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS media_item ON media(item_id, sort_order);
            CREATE TABLE IF NOT EXISTS deals(
                id TEXT PRIMARY KEY,
                item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
                name TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'scelle',
                lang TEXT DEFAULT '',
                grade TEXT DEFAULT '',
                platform TEXT NOT NULL DEFAULT 'autre',
                lot_price REAL NOT NULL DEFAULT 0,
                lot_shipping REAL NOT NULL DEFAULT 0,
                qty INTEGER NOT NULL DEFAULT 1,
                is_import INTEGER NOT NULL DEFAULT 0,
                is_ioss INTEGER NOT NULL DEFAULT 0,
                split_mode TEXT NOT NULL DEFAULT 'value',
                resale_prices TEXT NOT NULL DEFAULT '{}',
                resale_shipping_out REAL NOT NULL DEFAULT 0,
                packaging_cost REAL NOT NULL DEFAULT 0,
                buyer_pays_shipping INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            -- Photos rattachées à un deal (table séparée de `media` car les deals ne
            -- sont pas des items : pas de FK vers items(id), on évite de casser la
            -- contrainte FK ON avec des ids de nature différente).
            CREATE TABLE IF NOT EXISTS deal_media(
                id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime TEXT NOT NULL DEFAULT 'image/webp',
                size_bytes INTEGER NOT NULL,
                width INTEGER, height INTEGER,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS deal_media_deal ON deal_media(deal_id, sort_order);
            -- Prix d'achat détaillés par unité. Facultatif : un item sans ligne ici
            -- continue d'utiliser items.buy_price x items.qty comme avant (aucune
            -- régression). Dès qu'au moins une ligne existe pour un item, la quantité
            -- et le coût de cet item sont ENTIÈREMENT dérivés de ces lignes (somme des
            -- qty, somme des price*qty) — voir build_state().
            CREATE TABLE IF NOT EXISTS purchases(
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                price REAL NOT NULL,
                qty INTEGER NOT NULL DEFAULT 1,
                date TEXT NOT NULL,
                note TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS purchases_item ON purchases(item_id);

            -- Achat-revente v2 : fiches carte (calcul inversé) et commandes
            -- d'import Japon. Tables neuves, indépendantes de deals/deal_media
            -- (chantier 5, laissé intact). CREATE TABLE IF NOT EXISTS est
            -- additif par nature : aucune donnée existante n'est touchée.
            CREATE TABLE IF NOT EXISTS card_sheets(
                id TEXT PRIMARY KEY,
                item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
                name TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'loose',
                grade TEXT DEFAULT '',
                lang TEXT DEFAULT '',
                set_name TEXT DEFAULT '',
                profit_target_pct REAL,
                resale_platform TEXT NOT NULL DEFAULT 'ebay',
                resale_mode TEXT NOT NULL DEFAULT 'auto',
                resale_min REAL, resale_median REAL, resale_max REAL,
                resale_shipping_cost REAL NOT NULL DEFAULT 0,
                packaging_cost REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS card_sheet_listings(
                id TEXT PRIMARY KEY,
                sheet_id TEXT NOT NULL REFERENCES card_sheets(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                url TEXT DEFAULT '',
                price REAL NOT NULL DEFAULT 0,
                shipping REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS csl_sheet ON card_sheet_listings(sheet_id);
            CREATE TABLE IF NOT EXISTS import_orders(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                order_date TEXT,
                supplier TEXT NOT NULL DEFAULT 'Buyee',
                status TEXT NOT NULL DEFAULT 'brouillon',
                fx_rate REAL, fx_rate_at TEXT, fx_spread_pct REAL,
                fee_proxy_pct REAL, fee_domestic_jpy REAL, fee_consolidation_jpy REAL,
                fee_intl_shipping_jpy REAL, fee_payment_pct REAL,
                vat_rate_pct REAL, duty_rate_pct REAL, carrier_fee_eur REAL,
                ioss_enabled INTEGER NOT NULL DEFAULT 0,
                split_mode TEXT NOT NULL DEFAULT 'value',
                low_margin_alert_pct REAL,
                received_duty_eur REAL, received_vat_eur REAL, received_carrier_fee_eur REAL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS import_order_lines(
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES import_orders(id) ON DELETE CASCADE,
                item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
                name TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'scelle',
                qty INTEGER NOT NULL DEFAULT 1,
                unit_price_jpy REAL NOT NULL DEFAULT 0,
                resale_target_eur REAL,
                resale_platform TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS iol_order ON import_order_lines(order_id, sort_order);

            -- Stock d'achat-revente : une ligne = un exemplaire, jamais une
            -- quantité (indispensable pour suivre les dates carte par carte).
            -- Indépendant du Portefeuille : ne pèse jamais dans build_state().
            CREATE TABLE IF NOT EXISTS stock_items(
                id TEXT PRIMARY KEY,
                linked_item_id TEXT REFERENCES items(id) ON DELETE SET NULL,
                name TEXT NOT NULL DEFAULT '', set_name TEXT DEFAULT '', card_number TEXT DEFAULT '',
                lang TEXT DEFAULT 'FR', type TEXT NOT NULL DEFAULT 'loose', grade TEXT DEFAULT '',
                cost_basis REAL NOT NULL DEFAULT 0,
                buy_date TEXT, buy_platform TEXT DEFAULT '', buy_url TEXT DEFAULT '',
                target_price REAL, target_platform TEXT,
                photo_id TEXT, photo_size_bytes INTEGER, photo_width INTEGER, photo_height INTEGER,
                status TEXT NOT NULL DEFAULT 'achete',
                sale_price REAL, sale_platform TEXT,
                sale_net REAL, sale_net_manual INTEGER NOT NULL DEFAULT 0,
                source_order_line_id TEXT REFERENCES import_order_lines(id) ON DELETE SET NULL,
                notes TEXT DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS stock_status ON stock_items(status);
            -- Historique des changements de statut : jamais écrasé, seulement
            -- ajouté (les dates peuvent être corrigées après coup en éditant
            -- une ligne existante). C'est de là que les 3 délais sont recalculés
            -- à chaque lecture, jamais mis en cache sur stock_items.
            CREATE TABLE IF NOT EXISTS stock_events(
                id TEXT PRIMARY KEY,
                stock_id TEXT NOT NULL REFERENCES stock_items(id) ON DELETE CASCADE,
                from_status TEXT, to_status TEXT NOT NULL,
                at TEXT NOT NULL, note TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS stock_events_stock ON stock_events(stock_id, at);

            -- Référentiel de cartes : une entrée par identité (nom+set+numéro+
            -- langue+grade), que items/card_sheets/import_order_lines/stock_items
            -- référencent par card_id (colonnes ajoutées dans migrate(), additif).
            -- Ne remplace ni ne touche le moteur d'estimation existant (comps sur
            -- items) : resale_min/median/max et buy_max_computed sont des
            -- instantanés, pas un recalcul continu.
            CREATE TABLE IF NOT EXISTS cards(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL, set_name TEXT DEFAULT '', card_number TEXT DEFAULT '',
                lang TEXT DEFAULT 'FR', type TEXT NOT NULL DEFAULT 'loose', grade TEXT DEFAULT '',
                identity_key TEXT NOT NULL,
                photo_id TEXT, photo_size_bytes INTEGER, photo_width INTEGER, photo_height INTEGER,
                profit_target_pct REAL,
                resale_mode TEXT NOT NULL DEFAULT 'auto',
                resale_min REAL, resale_median REAL, resale_max REAL,
                buy_max_computed REAL,
                merged_into_id TEXT REFERENCES cards(id),
                notes TEXT DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS cards_identity ON cards(identity_key);
            CREATE TABLE IF NOT EXISTS card_listings(
                id TEXT PRIMARY KEY,
                card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                platform TEXT NOT NULL, url TEXT DEFAULT '',
                price REAL NOT NULL DEFAULT 0, shipping REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS card_listings_card ON card_listings(card_id);
            -- Propositions de rapprochement (score intermédiaire) issues de la
            -- migration ou détectées plus tard : jamais appliquées seules, c'est
            -- l'écran de fusion qui tranche.
            CREATE TABLE IF NOT EXISTS card_merge_suggestions(
                id TEXT PRIMARY KEY,
                card_a_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                card_b_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                score REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            -- Journal des fusions : chaque ligne réaffectée est notée avec sa
            -- valeur précédente, pour qu'une fusion reste annulable (merge_id
            -- regroupe toutes les lignes d'une même opération).
            CREATE TABLE IF NOT EXISTS card_merge_log(
                id TEXT PRIMARY KEY, merge_id TEXT NOT NULL,
                loser_card_id TEXT NOT NULL, winner_card_id TEXT NOT NULL,
                affected_table TEXT NOT NULL, affected_id TEXT NOT NULL,
                previous_card_id TEXT, at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS card_merge_log_merge ON card_merge_log(merge_id);
            """
        )
        migrate(con)


def migrate(con: sqlite3.Connection) -> None:
    """Ajoute les colonnes des versions suivantes sans toucher aux données."""
    add = {
        "items": {
            "status": "TEXT NOT NULL DEFAULT 'owned'",   # owned = possédé, watch = en veille
            "target_price": "REAL NOT NULL DEFAULT 0",   # prix d'achat visé sur un item en veille
            # Lien vers le référentiel de cartes (plomberie) — distinct du fait
            # d'être "un item" : plusieurs items peuvent partager la même carte.
            "card_id": "TEXT REFERENCES cards(id)",
        },
        "comps": {
            "sold_count": "INTEGER NOT NULL DEFAULT 1",  # nb de ventes que ce relevé représente
            # Port séparé du prix article. Règle stricte : l'estimation de valeur
            # se calcule sur `price` seul (mélanger port inclus / exclu fausserait
            # la moyenne). Le coût total = price + shipping est calculé côté build_state.
            "shipping": "REAL NOT NULL DEFAULT 0",
        },
        "import_order_lines": {
            # Devise de SAISIE de la ligne. Défaut 'JPY' : toute ligne déjà en
            # base avant cette migration reste en ¥ avec la même valeur qu'avant
            # (unit_price_jpy inchangé) — comportement strictement identique.
            "unit_currency": "TEXT NOT NULL DEFAULT 'JPY'",
            # Montant réel en € si unit_currency='EUR' — jamais reconverti,
            # jamais recalculé au taux de change (ce n'est pas une estimation).
            "unit_price_eur": "REAL",
            "card_id": "TEXT REFERENCES cards(id)",
            # Même logique que stock_items.target_overridden, appliquée à
            # resale_target_eur/resale_platform.
            "resale_target_overridden": "INTEGER NOT NULL DEFAULT 0",
        },
        "import_orders": {
            # Montant réellement débité en € pour la part ¥ de la commande,
            # saisi a posteriori (relevé bancaire) pour calculer le taux de
            # change effectif obtenu, spread compris.
            "received_debit_eur": "REAL",
            # Port international réellement facturé (€) — remplace la conversion
            # JPY->EUR estimée dans la valeur en douane quand connu (facture
            # transporteur en €, pas une reconversion).
            "received_intl_shipping_eur": "REAL",
            # "Total réellement payé" : filet de secours quand le détail poste
            # par poste (droits/TVA/port/débit ¥) n'est pas connu. L'écart avec
            # l'estimation théorique est alors réparti au prorata de la valeur
            # de chaque ligne, pour obtenir quand même un coût par carte juste.
            "received_total_eur": "REAL",
            # Forfait fixe du proxy, ¥ par commande (ex. Buyee facture 500¥
            # par commande quel que soit le montant — un % seul ne le modélise
            # pas). Multiplié par n_orders si plusieurs commandes/enchères
            # gagnées séparément sont regroupées dans un même colis.
            "fee_proxy_fixed_jpy": "REAL NOT NULL DEFAULT 0",
            "n_orders": "INTEGER NOT NULL DEFAULT 1",
        },
        "card_sheets": {
            # Une seule photo par fiche (pas une galerie) : même pipeline que
            # les items (media.py), stockée dans CARD_SHEET_MEDIA/<sheet_id>/.
            # NULL = pas de photo, cas normal et attendu (facultative).
            "photo_id": "TEXT",
            "photo_size_bytes": "INTEGER",
            "photo_width": "INTEGER",
            "photo_height": "INTEGER",
            # Lien vers le référentiel de cartes (plomberie, indépendant du lien
            # item_id qui existe déjà et qui, lui, pointe vers un exemplaire précis).
            "card_id": "TEXT REFERENCES cards(id)",
            # Absent du modèle initial des fiches carte ; ajouté pour que
            # l'identité du référentiel (nom+set+numéro+langue+grade) puisse
            # s'appuyer dessus. Vide par défaut sur les fiches existantes.
            "card_number": "TEXT DEFAULT ''",
        },
        "stock_items": {
            "card_id": "TEXT REFERENCES cards(id)",
            # Passe à 1 quand target_price/target_platform diverge de la valeur
            # par défaut de la carte liée (cards.resale_target_eur / .default_
            # resale_platform) — calculé côté serveur à chaque écriture, jamais
            # saisi tel quel par le client. Porte le repère visuel "modifié".
            "target_overridden": "INTEGER NOT NULL DEFAULT 0",
        },
        "cards": {
            # Prix de vente visé par défaut de la carte (distinct de resale_
            # median, qui est une statistique marché) : propagé aux nouvelles
            # lignes de commande/stock créées via le sélecteur, éditable sur
            # la fiche. Idem pour la plateforme de revente par défaut.
            "resale_target_eur": "REAL",
            "default_resale_platform": "TEXT",
        },
    }
    for table, cols in add.items():
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def get_settings() -> dict:
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='settings'").fetchone()
    s = dict(DEFAULT_SETTINGS)
    if row:
        stored = json.loads(row["v"])
        s.update({k: v for k, v in stored.items() if k != "weights"})
        s["weights"] = {**DEFAULT_SETTINGS["weights"], **stored.get("weights", {})}
    return s


def put_settings(s: dict) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO settings(k,v) VALUES('settings',?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (json.dumps(s),),
        )


def get_deal_params() -> dict:
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='deal_params'").fetchone()
    return deals_mod.merge_params(json.loads(row["v"]) if row else None)


def put_deal_params(p: dict) -> dict:
    current = get_deal_params()
    current.update({k: v for k, v in p.items() if k != "platform_fees"})
    if isinstance(p.get("platform_fees"), dict):
        for k, v in p["platform_fees"].items():
            if k in current["platform_fees"] and isinstance(v, dict):
                current["platform_fees"][k].update(v)
    with db() as con:
        con.execute(
            "INSERT INTO settings(k,v) VALUES('deal_params',?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (json.dumps(current),),
        )
    return current


def get_card_settings() -> dict:
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='card_deal_settings'").fetchone()
    return card_deals_mod.merge_card_settings(json.loads(row["v"]) if row else None)


def _num(v, fallback):
    """Cast tolérant : le JS envoie parfois un nombre en string. Les calculs
    (card_deals.py) font des opérations arithmétiques directes sur ces valeurs
    (ex. 1 + fx_spread_pct/100) sans re-caster : une string y ferait planter
    l'appel réseau/calcul, donc on caste une fois pour toutes ici, à l'écriture."""
    if v in (None, ""):
        return fallback
    try:
        return float(v)
    except (TypeError, ValueError):
        return fallback


def put_card_settings(p: dict) -> dict:
    current = get_card_settings()
    for k, v in p.items():
        if k in ("import", "sell_fees", "buy_fees") and isinstance(v, dict):
            for kk, vv in v.items():
                if kk in current[k] and isinstance(vv, dict):
                    for kkk, vvv in vv.items():
                        current[k][kk][kkk] = _num(vvv, current[k][kk].get(kkk))
                elif kk in current[k]:
                    current[k][kk] = _num(vv, current[k][kk])
        elif k == "japan_lot_size":
            current[k] = int(_num(v, current[k]))
        elif k == "profit_target_pct":
            current[k] = max(0.0, _num(v, current[k]))  # <=-100% ferait planter cost_max (division par ~0)
        else:
            current[k] = _num(v, current.get(k, v))
    with db() as con:
        con.execute(
            "INSERT INTO settings(k,v) VALUES('card_deal_settings',?) "
            "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (json.dumps(current),),
        )
    return current


def fetch_jpy_eur_rate() -> float | None:
    """Taux JPY->EUR via frankfurter.dev (ECB, gratuit, sans clé). Timeout
    court, échec silencieux : ne doit JAMAIS bloquer un enregistrement."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.frankfurter.dev/v1/latest?base=JPY&symbols=EUR",
            headers={"User-Agent": "portefeuille-pokemon"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode("utf-8"))
        rate = data.get("rates", {}).get("EUR")
        return float(rate) if rate else None
    except Exception:
        return None


# ------------------------------------------------------------------------ auth

def session_secret() -> bytes:
    """Clé de signature des sessions, générée une fois et gardée en base :
    les sessions survivent aux redémarrages et aux redéploiements."""
    with db() as con:
        row = con.execute("SELECT v FROM settings WHERE k='secret'").fetchone()
        if row:
            return row["v"].encode()
        val = secrets.token_hex(32)
        con.execute("INSERT INTO settings(k,v) VALUES('secret',?)", (val,))
    return val.encode()


def make_session() -> str:
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(session_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_session(raw: str | None) -> bool:
    if not raw or "." not in raw:
        return False
    exp, sig = raw.split(".", 1)
    good = hmac.new(session_secret(), exp.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False


_tries: dict[str, list] = {}


def throttled(ip: str) -> bool:
    """Cinq essais ratés par quart d'heure et par IP."""
    now = time.time()
    n, first = _tries.get(ip, [0, now])
    if now - first > 900:
        n, first = 0, now
    _tries[ip] = [n + 1, first]
    return n >= 5

# ------------------------------------------------------------------- estimation

def _days(d: str) -> float:
    try:
        return max(0.0, (date.today() - date.fromisoformat(d[:10])).days)
    except Exception:
        return 0.0


def _weight(c: dict, s: dict) -> float:
    sw = float(s["weights"].get(c["source"], 0.5))
    decay = max(0.5 ** (_days(c["date"]) / max(1, s["halfLife"])), 0.02)
    return sw * decay


def estimate(item: dict, s: dict) -> dict:
    """Moyenne pondérée des relevés : poids = source x fraîcheur, aberrants écartés."""
    live = [c for c in item["comps"] if not c["excluded"] and c["price"] > 0]
    points = []
    if not live:
        for c in item["comps"]:
            points.append({**c, "weight": 0.0, "out": False})
        return {
            "value": item["buy_price"] or None, "fallback": True,
            "conf": "faible", "n": 0, "points": points,
        }

    prices = [c["price"] for c in live]
    med = median(prices)
    mad = median([abs(p - med) for p in prices])
    cut = s["trimK"] * 1.4826 * mad if mad > 0 else float("inf")

    kept = []
    for c in live:
        out = len(live) >= 4 and abs(c["price"] - med) > cut
        p = {**c, "weight": round(_weight(c, s), 4), "out": out}
        points.append(p)
        if not out:
            kept.append(p)
    if not kept:  # tout écarté : on garde tout
        kept = [p for p in points if not p["excluded"]]

    for c in item["comps"]:
        if c["excluded"]:
            points.append({**c, "weight": 0.0, "out": False})

    tw = sum(p["weight"] for p in kept) or 1.0
    value = sum(p["weight"] * p["price"] for p in kept) / tw

    mean = sum(p["price"] for p in kept) / len(kept)
    var = sum((p["price"] - mean) ** 2 for p in kept) / len(kept)
    cv = (var ** 0.5 / mean) if mean else 1.0
    fresh = min(_days(p["date"]) for p in kept)

    score = (2 if len(kept) >= 5 else 1 if len(kept) >= 3 else 0)
    score += (2 if cv < 0.15 else 1 if cv < 0.30 else 0)
    score += (2 if fresh <= 30 else 1 if fresh <= 90 else 0)
    conf = "haute" if score >= 5 else "moyenne" if score >= 3 else "faible"

    return {"value": value, "fallback": False, "conf": conf, "n": len(kept), "points": points}

# -------------------------------------------------------------------- analyse

def _lin_fit(pts: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Moindres carrés sur (jours avant aujourd'hui, prix). Renvoie (pente/jour, prix aujourd'hui)."""
    n = len(pts)
    if n < 3:
        return None
    xs = [-a for a, _ in pts]          # -30 = il y a 30 jours, 0 = aujourd'hui
    ys = [p for _, p in pts]
    if max(xs) - min(xs) < 14:         # série trop courte pour parler de tendance
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return slope, my + slope * (0 - mx)


def analyse(item: dict) -> dict:
    """Lecture du marché à partir des relevés : tendance, volume de ventes, dispersion."""
    live = [c for c in item["comps"] if not c["excluded"] and c["price"] > 0]
    out = {
        "trend30": None,      # variation % des 30 derniers jours vs les 60 précédents
        "slope_pct": None,    # pente de la régression, en % par mois
        "fit": None,          # droite de tendance pour le graphique
        "sales_month": None,  # ventes constatées par mois
        "sales_90": 0,        # ventes constatées sur 90 jours
        "spread": None,       # dispersion (max-min)/médiane sur 90 jours
        "low90": None, "high90": None,
        "n": len(live), "span": 0,
    }
    if not live:
        return out

    aged = [(_days(c["date"]), c) for c in live]
    out["span"] = int(max(a for a, _ in aged) - min(a for a, _ in aged))

    recent = [c["price"] for a, c in aged if a <= 30]
    before = [c["price"] for a, c in aged if 30 < a <= 90]
    if recent and before:
        m0, m1 = median(before), median(recent)
        if m0:
            out["trend30"] = (m1 - m0) / m0 * 100

    fit = _lin_fit([(a, c["price"]) for a, c in aged if a <= 180])
    if fit:
        slope, now_price = fit
        out["fit"] = {"slope": slope, "now": now_price}
        if now_price:
            out["slope_pct"] = slope * 30 / now_price * 100

    sales = [c for a, c in aged if a <= 90 and c["source"] in SALE_SOURCES]
    if sales:
        n_sales = sum(int(c.get("sold_count") or 1) for c in sales)
        oldest = max(_days(c["date"]) for c in sales)
        window = max(30.0, min(90.0, oldest))     # pas d'extrapolation sur 3 jours de recul
        out["sales_90"] = n_sales
        out["sales_month"] = n_sales * 30 / window

    w90 = [c["price"] for a, c in aged if a <= 90] or [c["price"] for _, c in aged]
    med = median(w90)
    out["low90"], out["high90"] = min(w90), max(w90)
    if med:
        out["spread"] = (max(w90) - min(w90)) / med * 100
    return out


# ------------------------------------------------------------------------ state

def load_items() -> list[dict]:
    with db() as con:
        items = [dict(r) for r in con.execute("SELECT * FROM items")]
        comps = [dict(r) for r in con.execute("SELECT * FROM comps ORDER BY date DESC")]
        photos = [dict(r) for r in con.execute(
            "SELECT id, item_id, filename, mime, size_bytes, width, height, sort_order, created_at "
            "FROM media ORDER BY item_id, sort_order, created_at"
        )]
        purchases = [dict(r) for r in con.execute(
            "SELECT id, item_id, price, qty, date, note FROM purchases ORDER BY date DESC"
        )]
    by_item: dict[str, list] = {}
    for c in comps:
        c["excluded"] = bool(c["excluded"])
        c["shipping"] = float(c.get("shipping") or 0)
        # Coût total (article + port) : sert à évaluer une opportunité d'achat.
        # N'est PAS utilisé par estimate() qui reste sur price seul.
        c["total"] = float(c["price"]) + c["shipping"]
        by_item.setdefault(c["item_id"], []).append(c)
    photos_by_item: dict[str, list] = {}
    for p in photos:
        p["url"] = f"/api/items/{p['item_id']}/photos/{p['id']}"
        p["thumb_url"] = f"/api/items/{p['item_id']}/photos/{p['id']}/thumb"
        photos_by_item.setdefault(p["item_id"], []).append(p)
    purchases_by_item: dict[str, list] = {}
    for pu in purchases:
        purchases_by_item.setdefault(pu["item_id"], []).append(pu)
    for it in items:
        it["comps"] = by_item.get(it["id"], [])
        it["photos"] = photos_by_item.get(it["id"], [])
        it["purchases"] = purchases_by_item.get(it["id"], [])
        # Photo du référentiel de cartes, séparée de la galerie propre à l'item
        # (`photos`) : plomberie exposée par l'API, l'interface ne s'en sert pas
        # encore (pas de retouche visuelle demandée à cette étape).
        it["card_photo_url"], it["card_photo_thumb_url"] = _resolve_photo_urls(it.get("card_id"), None, None)
    return items


def build_state(snapshot: bool = True) -> dict:
    s = get_settings()
    items = load_items()
    for it in items:
        it["est"] = estimate(it, s)
        it["stats"] = analyse(it)
        # Prix d'achat détaillés (chantier "prix d'achat par unité") : dès qu'au
        # moins une ligne existe, qty et buy_price affichés/utilisés viennent
        # ENTIÈREMENT de ces lignes (somme des quantités, coût réel total). Sans
        # ligne, comportement strictement inchangé : buy_price x qty du formulaire.
        lots = it["purchases"]
        if lots:
            lot_qty = sum(int(l["qty"]) for l in lots)
            lot_cost = sum(float(l["price"]) * int(l["qty"]) for l in lots)
            it["qty"] = lot_qty
            it["buy_price"] = round(lot_cost / lot_qty, 2) if lot_qty else 0.0  # PRU moyen pondéré
            it["cost"] = lot_cost
        else:
            it["cost"] = it["buy_price"] * it["qty"]
        it["value"] = (it["est"]["value"] or 0) * it["qty"]
        if it["status"] == "watch":                      # une veille ne pèse pas au bilan
            it["value"] = it["cost"] = 0.0
            it["gap"] = ((it["est"]["value"] - it["target_price"]) / it["target_price"] * 100
                         if it["target_price"] and it["est"]["value"] else None)
    owned = [i for i in items if i["status"] == "owned"]
    value = sum(i["value"] for i in owned)
    invested = sum(i["cost"] for i in owned)
    if snapshot and items:
        with db() as con:
            con.execute(
                "INSERT INTO snapshots(d,value,invested) VALUES(?,?,?) "
                "ON CONFLICT(d) DO UPDATE SET value=excluded.value, invested=excluded.invested",
                (date.today().isoformat(), value, invested),
            )
    with db() as con:
        snaps = [dict(r) for r in con.execute("SELECT * FROM snapshots ORDER BY d")]
    return {
        "items": items,
        "snapshots": snaps,
        "settings": s,
        "sources": {k: {"label": lbl, "w": w} for k, (lbl, w) in SOURCES.items()},
        "totals": {
            "value": value,
            "invested": invested,
            "pnl": value - invested,
            "net": value * (1 - s["fees"] / 100) - invested,
            "units": sum(i["qty"] for i in owned),
            "watching": sum(1 for i in items if i["status"] == "watch"),
        },
    }

# -------------------------------------------------------------------------- api

app = FastAPI(title="Portefeuille Pokémon")
init()


OPEN_PATHS = {"/api/login", "/api/ping", "/login", "/login.html"}


@app.middleware("http")
async def auth(request: Request, call_next):
    if not PASSWORD or request.url.path in OPEN_PATHS:
        return await call_next(request)
    if valid_session(request.cookies.get(COOKIE)):
        return await call_next(request)
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "session expirée"}, status_code=401)
    return FileResponse(BASE / "static" / "login.html", status_code=200)


def set_session_cookie(resp: Response, request: Request) -> None:
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie(COOKIE, make_session(), max_age=SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", secure=https, path="/")


@app.post("/api/login")
async def api_login(request: Request, p: dict = Body(...)):
    ip = request.headers.get("x-forwarded-for", "?").split(",")[0].strip() or "?"
    if throttled(ip):
        raise HTTPException(429, "trop d'essais, réessaie dans 15 minutes")
    if not PASSWORD or not hmac.compare_digest(str(p.get("password", "")), PASSWORD):
        raise HTTPException(401, "mot de passe incorrect")
    _tries.pop(ip, None)
    resp = JSONResponse({"ok": True})
    set_session_cookie(resp, request)
    return resp


@app.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


def nid() -> str:
    return secrets.token_hex(5)


FIELDS = ["name", "type", "lang", "grade", "set_name", "qty", "buy_price", "buy_date",
          "notes", "status", "target_price"]


def clean(p: dict) -> dict:
    return {
        "name": str(p.get("name", "")).strip()[:200],
        "type": p.get("type") if p.get("type") in ("scelle", "loose", "gradee") else "scelle",
        "lang": str(p.get("lang", "FR"))[:10],
        "grade": str(p.get("grade", ""))[:40],
        "set_name": str(p.get("set_name", ""))[:120],
        "qty": max(1, int(p.get("qty") or 1)),
        "buy_price": max(0.0, float(p.get("buy_price") or 0)),
        "buy_date": str(p.get("buy_date") or date.today().isoformat())[:10],
        "notes": str(p.get("notes", ""))[:2000],
        "status": "watch" if p.get("status") == "watch" else "owned",
        "target_price": max(0.0, float(p.get("target_price") or 0)),
    }


@app.get("/api/state")
def api_state():
    return build_state()


@app.post("/api/items")
def api_add_item(p: dict = Body(...)):
    d = clean(p)
    if not d["name"]:
        raise HTTPException(400, "nom manquant")
    iid = nid()
    with db() as con:
        con.execute(
            f"INSERT INTO items(id,{','.join(FIELDS)},created_at) VALUES(?,{','.join('?' * len(FIELDS))},?)",
            (iid, *[d[f] for f in FIELDS], datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": iid}


@app.put("/api/items/{iid}")
def api_edit_item(iid: str, p: dict = Body(...)):
    d = clean(p)
    with db() as con:
        cur = con.execute(
            f"UPDATE items SET {','.join(f + '=?' for f in FIELDS)} WHERE id=?",
            (*[d[f] for f in FIELDS], iid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "item introuvable")
    return {"ok": True}


@app.delete("/api/items/{iid}")
def api_del_item(iid: str):
    with db() as con:
        con.execute("DELETE FROM comps WHERE item_id=?", (iid,))
        con.execute("DELETE FROM media WHERE item_id=?", (iid,))
        con.execute("DELETE FROM purchases WHERE item_id=?", (iid,))
        con.execute("DELETE FROM items WHERE id=?", (iid,))
    media_mod.delete_item_dir(MEDIA, iid)   # efface aussi les fichiers physiques
    return {"ok": True}


@app.post("/api/items/{iid}/comps")
def api_add_comp(iid: str, p: dict = Body(...)):
    price = float(p.get("price") or 0)
    if price <= 0:
        raise HTTPException(400, "prix invalide")
    shipping = max(0.0, float(p.get("shipping") or 0))
    cid = nid()
    with db() as con:
        if not con.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
            raise HTTPException(404, "item introuvable")
        con.execute(
            "INSERT INTO comps(id,item_id,price,date,source,note,excluded,sold_count,shipping) "
            "VALUES(?,?,?,?,?,?,0,?,?)",
            (cid, iid, price, str(p.get("date") or date.today().isoformat())[:10],
             p.get("source") if p.get("source") in SOURCES else "manual",
             str(p.get("note", ""))[:200], max(1, int(p.get("sold_count") or 1)),
             shipping),
        )
    return {"id": cid}


@app.patch("/api/comps/{cid}")
def api_toggle_comp(cid: str):
    with db() as con:
        con.execute("UPDATE comps SET excluded = 1 - excluded WHERE id=?", (cid,))
    return {"ok": True}


@app.put("/api/comps/{cid}")
def api_edit_comp(cid: str, p: dict = Body(...)):
    """Édite un relevé (prix / port / note / source / date / nb ventes)."""
    price = float(p.get("price") or 0)
    if price <= 0:
        raise HTTPException(400, "prix invalide")
    with db() as con:
        cur = con.execute(
            "UPDATE comps SET price=?, shipping=?, date=?, source=?, note=?, sold_count=? WHERE id=?",
            (price,
             max(0.0, float(p.get("shipping") or 0)),
             str(p.get("date") or date.today().isoformat())[:10],
             p.get("source") if p.get("source") in SOURCES else "manual",
             str(p.get("note", ""))[:200],
             max(1, int(p.get("sold_count") or 1)),
             cid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "relevé introuvable")
    return {"ok": True}


@app.delete("/api/comps/{cid}")
def api_del_comp(cid: str):
    with db() as con:
        con.execute("DELETE FROM comps WHERE id=?", (cid,))
    return {"ok": True}


# ---------------------------------------------------------------- prix d'achat

@app.post("/api/items/{iid}/purchases")
def api_add_purchase(iid: str, p: dict = Body(...)):
    """Ajoute un prix d'achat détaillé pour tout ou partie de la quantité d'un item.
    Dès la première ligne posée, qty/buy_price de l'item sont dérivés de l'ensemble
    des lignes (voir build_state)."""
    price = float(p.get("price") or 0)
    if price <= 0:
        raise HTTPException(400, "prix invalide")
    qty = max(1, int(p.get("qty") or 1))
    pid = nid()
    with db() as con:
        if not con.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
            raise HTTPException(404, "item introuvable")
        con.execute(
            "INSERT INTO purchases(id,item_id,price,qty,date,note) VALUES(?,?,?,?,?,?)",
            (pid, iid, price, qty, str(p.get("date") or date.today().isoformat())[:10],
             str(p.get("note", ""))[:200]),
        )
    return {"id": pid}


@app.put("/api/purchases/{pid}")
def api_edit_purchase(pid: str, p: dict = Body(...)):
    price = float(p.get("price") or 0)
    if price <= 0:
        raise HTTPException(400, "prix invalide")
    qty = max(1, int(p.get("qty") or 1))
    with db() as con:
        cur = con.execute(
            "UPDATE purchases SET price=?, qty=?, date=?, note=? WHERE id=?",
            (price, qty, str(p.get("date") or date.today().isoformat())[:10],
             str(p.get("note", ""))[:200], pid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "prix d'achat introuvable")
    return {"ok": True}


@app.delete("/api/purchases/{pid}")
def api_del_purchase(pid: str):
    with db() as con:
        con.execute("DELETE FROM purchases WHERE id=?", (pid,))
    return {"ok": True}


@app.put("/api/settings")
def api_settings(p: dict = Body(...)):
    s = get_settings()
    s["halfLife"] = max(7, int(p.get("halfLife") or s["halfLife"]))
    s["fees"] = max(0.0, float(p.get("fees", s["fees"])))
    s["trimK"] = max(1.0, float(p.get("trimK") or s["trimK"]))
    for k, v in (p.get("weights") or {}).items():
        if k in SOURCES:
            s["weights"][k] = max(0.0, min(2.0, float(v)))
    put_settings(s)
    return s


@app.post("/api/items/{iid}/buy")
def api_buy(iid: str, p: dict = Body(...)):
    """Fait passer un item de la veille au portefeuille."""
    price = max(0.0, float(p.get("buy_price") or 0))
    qty = max(1, int(p.get("qty") or 1))
    when = str(p.get("buy_date") or date.today().isoformat())[:10]
    with db() as con:
        cur = con.execute(
            "UPDATE items SET status='owned', buy_price=?, qty=?, buy_date=? WHERE id=?",
            (price, qty, when, iid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "item introuvable")
    return {"ok": True}


@app.post("/api/items/{iid}/watch")
def api_watch(iid: str):
    """Renvoie un item en veille (achat annulé, revendu…)."""
    with db() as con:
        con.execute("UPDATE items SET status='watch' WHERE id=?", (iid,))
    return {"ok": True}


@app.post("/api/snapshot")
def api_snapshot():
    build_state(snapshot=True)
    return {"ok": True}


# --------------------------------------------------------------------------- photos

@app.post("/api/items/{iid}/photos")
async def api_add_photo(iid: str, file: UploadFile = File(...)):
    """Upload une photo pour un item. Vérifie taille + type + limite 8 photos."""
    with db() as con:
        if not con.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
            raise HTTPException(404, "item introuvable")
        n = con.execute("SELECT COUNT(*) AS n FROM media WHERE item_id=?", (iid,)).fetchone()["n"]
    if n >= media_mod.MAX_PHOTOS_PER_ITEM:
        raise HTTPException(400, f"limite atteinte : {media_mod.MAX_PHOTOS_PER_ITEM} photos par item")

    raw = await file.read()
    try:
        info = media_mod.save_photo(MEDIA, iid, raw, (file.content_type or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))

    now = datetime.now().isoformat(timespec="seconds")
    with db() as con:
        # sort_order = fin de liste : max + 1 (première photo = 0, sert de vignette)
        maxo = con.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM media WHERE item_id=?",
            (iid,),
        ).fetchone()["m"]
        con.execute(
            "INSERT INTO media(id,item_id,filename,mime,size_bytes,width,height,sort_order,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (info["id"], iid, info["filename"], "image/webp",
             info["size_bytes"], info["width"], info["height"], maxo + 1, now),
        )
    return {
        "id": info["id"],
        "url": f"/api/items/{iid}/photos/{info['id']}",
        "thumb_url": f"/api/items/{iid}/photos/{info['id']}/thumb",
        "sort_order": maxo + 1,
    }


@app.delete("/api/items/{iid}/photos/{pid}")
def api_del_photo(iid: str, pid: str):
    with db() as con:
        row = con.execute(
            "SELECT id FROM media WHERE item_id=? AND id=?", (iid, pid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "photo introuvable")
        con.execute("DELETE FROM media WHERE id=?", (pid,))
    media_mod.delete_photo(MEDIA, iid, pid)
    return {"ok": True}


@app.put("/api/items/{iid}/photos/order")
def api_reorder_photos(iid: str, p: dict = Body(...)):
    """Réordonne les photos d'un item. body: {order: [pid, pid, ...]}"""
    order = p.get("order")
    if not isinstance(order, list):
        raise HTTPException(400, "order doit être une liste")
    with db() as con:
        rows = {r["id"] for r in con.execute("SELECT id FROM media WHERE item_id=?", (iid,))}
        # Ignore silencieusement les ids inconnus, applique l'ordre pour les autres.
        for i, pid in enumerate(order):
            if pid in rows:
                con.execute("UPDATE media SET sort_order=? WHERE id=?", (i, pid))
    return {"ok": True}


@app.get("/api/items/{iid}/photos/{pid}")
def api_get_photo(iid: str, pid: str):
    """Sert l'original de la photo. Protégé par le middleware auth global."""
    path = media_mod.photo_path(MEDIA, iid, pid, thumb=False)
    if not path:
        raise HTTPException(404, "photo introuvable")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/items/{iid}/photos/{pid}/thumb")
def api_get_thumb(iid: str, pid: str):
    """Sert la vignette 400 px de la photo."""
    path = media_mod.photo_path(MEDIA, iid, pid, thumb=True)
    if not path:
        raise HTTPException(404, "vignette introuvable")
    return FileResponse(path, media_type="image/webp")


# ------------------------------------------------------------------ achat-revente

DEAL_FIELDS = ["item_id", "name", "type", "lang", "grade", "platform", "lot_price",
               "lot_shipping", "qty", "is_import", "is_ioss", "split_mode",
               "resale_shipping_out", "packaging_cost", "buyer_pays_shipping",
               "status", "notes"]


def clean_deal(p: dict) -> dict:
    return {
        "item_id": (str(p["item_id"]) if p.get("item_id") else None),
        "name": str(p.get("name", ""))[:200],
        "type": p.get("type") if p.get("type") in ("scelle", "loose", "gradee") else "scelle",
        "lang": str(p.get("lang", ""))[:10],
        "grade": str(p.get("grade", ""))[:40],
        "platform": p.get("platform") if p.get("platform") in deals_mod.PLATFORMS_BUY else "autre",
        "lot_price": max(0.0, float(p.get("lot_price") or 0)),
        "lot_shipping": max(0.0, float(p.get("lot_shipping") or 0)),
        "qty": max(1, int(p.get("qty") or 1)),
        "is_import": int(bool(p.get("is_import"))),
        "is_ioss": int(bool(p.get("is_ioss"))),
        "split_mode": p.get("split_mode") if p.get("split_mode") in ("value", "equal") else "value",
        "resale_shipping_out": max(0.0, float(p.get("resale_shipping_out") or 0)),
        "packaging_cost": max(0.0, float(p.get("packaging_cost") or 0)),
        "buyer_pays_shipping": int(bool(p.get("buyer_pays_shipping"))),
        "status": "done" if p.get("status") == "done" else "open",
        "notes": str(p.get("notes", ""))[:2000],
    }


def _deal_row_to_dict(row: dict) -> dict:
    d = dict(row)
    d["is_import"] = bool(d["is_import"])
    d["is_ioss"] = bool(d["is_ioss"])
    d["buyer_pays_shipping"] = bool(d["buyer_pays_shipping"])
    try:
        d["resale_prices"] = json.loads(d.get("resale_prices") or "{}")
    except Exception:
        d["resale_prices"] = {}
    return d


def _deal_photos(did: str) -> list[dict]:
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, deal_id, filename, mime, size_bytes, width, height, sort_order, created_at "
            "FROM deal_media WHERE deal_id=? ORDER BY sort_order, created_at", (did,)
        )]
    for p in rows:
        p["url"] = f"/api/deals/{did}/photos/{p['id']}"
        p["thumb_url"] = f"/api/deals/{did}/photos/{p['id']}/thumb"
    return rows


def _deal_view(row: dict, items_by_id: dict) -> dict:
    d = _deal_row_to_dict(row)
    params = get_deal_params()
    item_est = None
    if d["item_id"] and d["item_id"] in items_by_id:
        item_est = items_by_id[d["item_id"]]["est"]["value"]
    computed = deals_mod.build_deal_view(d, params, item_est=item_est)
    d["computed"] = computed
    d["photos"] = _deal_photos(d["id"])
    return d


@app.get("/api/deals")
def api_list_deals():
    st = build_state(snapshot=False)
    items_by_id = {i["id"]: i for i in st["items"]}
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM deals ORDER BY created_at DESC")]
    return {"deals": [_deal_view(r, items_by_id) for r in rows], "params": get_deal_params()}


@app.post("/api/deals")
def api_add_deal(p: dict = Body(...)):
    d = clean_deal(p)
    if not d["item_id"] and not d["name"]:
        raise HTTPException(400, "nom manquant (ou lien vers un item existant)")
    resale_prices = p.get("resale_prices") or {}
    resale_prices = {k: float(v) for k, v in resale_prices.items()
                      if k in deals_mod.PLATFORMS_SELL and v not in (None, "")}
    did = nid()
    with db() as con:
        con.execute(
            f"INSERT INTO deals(id,{','.join(DEAL_FIELDS)},resale_prices,created_at) "
            f"VALUES(?,{','.join('?' * len(DEAL_FIELDS))},?,?)",
            (did, *[d[f] for f in DEAL_FIELDS], json.dumps(resale_prices),
             datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": did}


@app.put("/api/deals/{did}")
def api_edit_deal(did: str, p: dict = Body(...)):
    d = clean_deal(p)
    resale_prices = p.get("resale_prices") or {}
    resale_prices = {k: float(v) for k, v in resale_prices.items()
                      if k in deals_mod.PLATFORMS_SELL and v not in (None, "")}
    with db() as con:
        cur = con.execute(
            f"UPDATE deals SET {','.join(f + '=?' for f in DEAL_FIELDS)}, resale_prices=? WHERE id=?",
            (*[d[f] for f in DEAL_FIELDS], json.dumps(resale_prices), did),
        )
        if not cur.rowcount:
            raise HTTPException(404, "opération introuvable")
    return {"ok": True}


@app.delete("/api/deals/{did}")
def api_del_deal(did: str):
    with db() as con:
        con.execute("DELETE FROM deal_media WHERE deal_id=?", (did,))
        con.execute("DELETE FROM deals WHERE id=?", (did,))
    media_mod.delete_item_dir(DEAL_MEDIA, did)
    return {"ok": True}


@app.post("/api/deals/{did}/realize")
def api_realize_deal(did: str):
    """Marque l'opération réalisée : bascule au portefeuille avec le coût de
    revient réel comme prix d'achat. Crée l'item si le deal n'en avait pas.
    Les photos du deal sont copiées sur l'item (le deal garde les siennes,
    l'historique de l'opération reste consultable)."""
    with db() as con:
        row = con.execute("SELECT * FROM deals WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "opération introuvable")
    d = _deal_row_to_dict(dict(row))
    params = get_deal_params()
    cost = deals_mod.landed_cost(d, params)
    per_unit = cost["per_unit"]

    iid = d["item_id"]
    now = datetime.now().isoformat(timespec="seconds")
    with db() as con:
        if iid:
            con.execute(
                "UPDATE items SET status='owned', buy_price=?, qty=?, buy_date=? WHERE id=?",
                (per_unit, d["qty"] or 1, date.today().isoformat(), iid),
            )
        else:
            iid = nid()
            con.execute(
                "INSERT INTO items(id,name,type,lang,grade,set_name,qty,buy_price,buy_date,notes,status,target_price,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, d["name"] or "Item sans nom", d["type"], d["lang"] or "FR", d["grade"], "",
                 d["qty"] or 1, per_unit, date.today().isoformat(), d["notes"], "owned", 0.0, now),
            )
        con.execute("UPDATE deals SET status='done', item_id=? WHERE id=?", (iid, did))

    # Copie (pas déplacement) des photos du deal vers l'item.
    for ph in _deal_photos(did):
        src = media_mod.photo_path(DEAL_MEDIA, did, ph["id"], thumb=False)
        src_thumb = media_mod.photo_path(DEAL_MEDIA, did, ph["id"], thumb=True)
        if not src:
            continue
        new_pid = secrets.token_hex(8)
        dest_dir = MEDIA / iid
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{new_pid}.webp").write_bytes(src.read_bytes())
        if src_thumb:
            (dest_dir / f"{new_pid}.thumb.webp").write_bytes(src_thumb.read_bytes())
        with db() as con:
            maxo = con.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS m FROM media WHERE item_id=?", (iid,)
            ).fetchone()["m"]
            con.execute(
                "INSERT INTO media(id,item_id,filename,mime,size_bytes,width,height,sort_order,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (new_pid, iid, f"{new_pid}.webp", ph["mime"], ph["size_bytes"],
                 ph["width"], ph["height"], maxo + 1, now),
            )

    return {"ok": True, "item_id": iid, "buy_price": per_unit}


@app.get("/api/deal-params")
def api_get_deal_params():
    return get_deal_params()


@app.put("/api/deal-params")
def api_put_deal_params(p: dict = Body(...)):
    return put_deal_params(p)


# --- photos sur les deals (mêmes règles que sur les items : 8 max, 10 Mo, auth globale) ---

@app.post("/api/deals/{did}/photos")
async def api_add_deal_photo(did: str, file: UploadFile = File(...)):
    with db() as con:
        if not con.execute("SELECT 1 FROM deals WHERE id=?", (did,)).fetchone():
            raise HTTPException(404, "opération introuvable")
        n = con.execute("SELECT COUNT(*) AS n FROM deal_media WHERE deal_id=?", (did,)).fetchone()["n"]
    if n >= media_mod.MAX_PHOTOS_PER_ITEM:
        raise HTTPException(400, f"limite atteinte : {media_mod.MAX_PHOTOS_PER_ITEM} photos par opération")

    raw = await file.read()
    try:
        info = media_mod.save_photo(DEAL_MEDIA, did, raw, (file.content_type or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))

    now = datetime.now().isoformat(timespec="seconds")
    with db() as con:
        maxo = con.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM deal_media WHERE deal_id=?", (did,)
        ).fetchone()["m"]
        con.execute(
            "INSERT INTO deal_media(id,deal_id,filename,mime,size_bytes,width,height,sort_order,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (info["id"], did, info["filename"], "image/webp",
             info["size_bytes"], info["width"], info["height"], maxo + 1, now),
        )
    return {"id": info["id"], "url": f"/api/deals/{did}/photos/{info['id']}",
            "thumb_url": f"/api/deals/{did}/photos/{info['id']}/thumb"}


@app.delete("/api/deals/{did}/photos/{pid}")
def api_del_deal_photo(did: str, pid: str):
    with db() as con:
        if not con.execute("SELECT id FROM deal_media WHERE deal_id=? AND id=?", (did, pid)).fetchone():
            raise HTTPException(404, "photo introuvable")
        con.execute("DELETE FROM deal_media WHERE id=?", (pid,))
    media_mod.delete_photo(DEAL_MEDIA, did, pid)
    return {"ok": True}


@app.put("/api/deals/{did}/photos/order")
def api_reorder_deal_photos(did: str, p: dict = Body(...)):
    order = p.get("order")
    if not isinstance(order, list):
        raise HTTPException(400, "order doit être une liste")
    with db() as con:
        rows = {r["id"] for r in con.execute("SELECT id FROM deal_media WHERE deal_id=?", (did,))}
        for i, pid in enumerate(order):
            if pid in rows:
                con.execute("UPDATE deal_media SET sort_order=? WHERE id=?", (i, pid))
    return {"ok": True}


@app.get("/api/deals/{did}/photos/{pid}")
def api_get_deal_photo(did: str, pid: str):
    path = media_mod.photo_path(DEAL_MEDIA, did, pid, thumb=False)
    if not path:
        raise HTTPException(404, "photo introuvable")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/deals/{did}/photos/{pid}/thumb")
def api_get_deal_thumb(did: str, pid: str):
    path = media_mod.photo_path(DEAL_MEDIA, did, pid, thumb=True)
    if not path:
        raise HTTPException(404, "vignette introuvable")
    return FileResponse(path, media_type="image/webp")


# ------------------------------------------------------------- achat-revente v2
# Fiches carte (calcul inversé) et commandes d'import Japon. Indépendant de
# `deals`/`deal_media` (chantier 5), laissés intacts et non affichés côté UI.

CARD_SHEET_FIELDS = ["item_id", "name", "type", "grade", "lang", "set_name",
                      "profit_target_pct", "resale_platform", "resale_mode",
                      "resale_min", "resale_median", "resale_max",
                      "resale_shipping_cost", "packaging_cost", "status", "notes"]


def clean_card_sheet(p: dict) -> dict:
    def numopt(k):
        v = p.get(k)
        return float(v) if v not in (None, "") else None
    return {
        "item_id": (str(p["item_id"]) if p.get("item_id") else None),
        "name": str(p.get("name", ""))[:200],
        "type": p.get("type") if p.get("type") in ("loose", "gradee") else "loose",
        "grade": str(p.get("grade", ""))[:40],
        "lang": str(p.get("lang", ""))[:10],
        "set_name": str(p.get("set_name", ""))[:120],
        "profit_target_pct": (max(0.0, numopt("profit_target_pct")) if numopt("profit_target_pct") is not None else None),
        "resale_platform": p.get("resale_platform") if p.get("resale_platform") in card_deals_mod.SELL_PLATFORMS else "ebay",
        "resale_mode": "manual" if p.get("resale_mode") == "manual" else "auto",
        "resale_min": numopt("resale_min"),
        "resale_median": numopt("resale_median"),
        "resale_max": numopt("resale_max"),
        "resale_shipping_cost": max(0.0, float(p.get("resale_shipping_cost") or 0)),
        "packaging_cost": max(0.0, float(p.get("packaging_cost") or 0)),
        "status": p.get("status") if p.get("status") in ("open", "archived", "done") else "open",
        "notes": str(p.get("notes", ""))[:2000],
    }


def _card_sheet_view(row: dict, items_by_id: dict, card_settings: dict, fx_rate: float | None) -> dict:
    d = dict(row)
    with db() as con:
        listings = [dict(r) for r in con.execute(
            "SELECT * FROM card_sheet_listings WHERE sheet_id=? ORDER BY created_at DESC", (d["id"],)
        )]
    if d["resale_mode"] == "manual":
        resale_stats = {"p25": d["resale_min"], "median": d["resale_median"],
                         "p75": d["resale_max"], "n": None, "manual": True}
    else:
        comps = items_by_id.get(d["item_id"], {}).get("comps", []) if d["item_id"] else []
        resale_stats = card_deals_mod.resale_range_from_comps(comps)
        resale_stats["manual"] = False
    # "is not None", pas "or" : un objectif explicitement mis à 0% (seuil de
    # rentabilité) est une valeur légitime, pas une absence de valeur — "or"
    # la confondrait avec None/vide et la remplacerait silencieusement par le défaut.
    pt = d["profit_target_pct"]
    sheet_for_calc = {**d, "profit_target_pct": pt if pt is not None else card_settings["profit_target_pct"]}
    computed = card_deals_mod.build_card_sheet_view(sheet_for_calc, listings, card_settings, resale_stats, fx_rate=fx_rate)
    d["listings"] = computed.pop("listings")
    d["computed"] = computed
    if d["item_id"] and d["item_id"] in items_by_id:
        d["item_name"] = items_by_id[d["item_id"]]["name"]
    own_url = f"/api/card-sheets/{d['id']}/photo" if d.get("photo_id") else None
    own_thumb = f"/api/card-sheets/{d['id']}/photo/thumb" if d.get("photo_id") else None
    d["photo_url"], d["photo_thumb_url"] = _resolve_photo_urls(d.get("card_id"), own_url, own_thumb)
    return d


@app.get("/api/card-deals")
def api_list_card_deals():
    st = build_state(snapshot=False)
    items_by_id = {i["id"]: i for i in st["items"]}
    cs = get_card_settings()
    fx_rate = fetch_jpy_eur_rate()  # court, échec silencieux -> None si frankfurter.dev est injoignable
    with db() as con:
        sheets = [dict(r) for r in con.execute("SELECT * FROM card_sheets ORDER BY created_at DESC")]
        orders = [dict(r) for r in con.execute("SELECT * FROM import_orders ORDER BY created_at DESC")]
        lines_all = [dict(r) for r in con.execute(
            "SELECT * FROM import_order_lines ORDER BY order_id, sort_order"
        )]
        cards_by_id = {r["id"]: dict(r) for r in con.execute(
            "SELECT id,name,set_name,card_number,lang,grade,type,photo_id,buy_max_computed FROM cards"
        )}
        stock_count_by_line = {r["source_order_line_id"]: r["n"] for r in con.execute(
            "SELECT source_order_line_id, COUNT(*) AS n FROM stock_items "
            "WHERE source_order_line_id IS NOT NULL GROUP BY source_order_line_id"
        )}
    lines_by_order: dict[str, list] = {}
    for l in lines_all:
        lines_by_order.setdefault(l["order_id"], []).append(l)
    sheet_views = [_card_sheet_view(r, items_by_id, cs, fx_rate) for r in sheets]
    order_views = []
    for o in orders:
        lines = lines_by_order.get(o["id"], [])
        computed = card_deals_mod.build_import_order_view(o, lines, cs, fx_rate)
        ov = dict(o)
        ov["lines"] = computed.pop("lines")
        # Les lignes de commande n'ont pas leurs propres colonnes set/numéro/
        # langue/grade (saisie volontairement pauvre, cf. _identity_fields_
        # order_line) : la carte liée est la seule source de cette identité
        # riche, jointe ici pour l'affichage plutôt que dupliquée en base.
        for row in ov["lines"]:
            c = cards_by_id.get(row.get("card_id"))
            row["card_snapshot"] = None if not c else {
                "id": c["id"], "name": c["name"], "set_name": c["set_name"], "card_number": c["card_number"],
                "lang": c["lang"], "grade": c["grade"], "type": c["type"],
                "buy_max_computed": c["buy_max_computed"],
                **_card_photo_urls(c),
            }
            row["sent_to_stock"] = bool(stock_count_by_line.get(row["id"]))
            # Alerte de dépassement : jamais bloquante, juste visible tout de
            # suite sur la ligne (montant en rouge côté frontend) plutôt qu'à
            # la réception du colis. Comparé au coût tout compris (landed,
            # taxes/frais inclus) — pas au prix article brut — puisque
            # buy_max_computed est lui-même un prix "tout compris" prudent.
            bm = c.get("buy_max_computed") if c else None
            unit_eur = row.get("unit_landed_cost")
            over = round(unit_eur - bm, 2) if (bm is not None and unit_eur) else None
            row["buy_over_max_eur"] = over if (over is not None and over > 0) else None
            row["buy_over_max_pct"] = round(over / bm * 100, 1) if (row["buy_over_max_eur"] and bm) else None
        computed["n_over_max"] = sum(1 for row in ov["lines"] if row.get("buy_over_max_eur"))
        ov["computed"] = computed
        order_views.append(ov)
    return {"card_sheets": sheet_views, "import_orders": order_views, "settings": cs, "fx_rate": fx_rate}


@app.get("/api/card-settings")
def api_get_card_settings():
    return get_card_settings()


@app.put("/api/card-settings")
def api_put_card_settings(p: dict = Body(...)):
    return put_card_settings(p)


@app.get("/api/fx/jpy")
def api_fx_jpy():
    rate = fetch_jpy_eur_rate()
    return {"rate": rate, "ok": rate is not None}


# --- fiches carte ---

@app.post("/api/card-sheets")
def api_add_card_sheet(p: dict = Body(...)):
    d = clean_card_sheet(p)
    if not d["item_id"] and not d["name"]:
        raise HTTPException(400, "nom manquant (ou lien vers un item existant)")
    sid = nid()
    with db() as con:
        con.execute(
            f"INSERT INTO card_sheets(id,{','.join(CARD_SHEET_FIELDS)},created_at) "
            f"VALUES(?,{','.join('?' * len(CARD_SHEET_FIELDS))},?)",
            (sid, *[d[f] for f in CARD_SHEET_FIELDS], datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": sid}


@app.put("/api/card-sheets/{sid}")
def api_edit_card_sheet(sid: str, p: dict = Body(...)):
    d = clean_card_sheet(p)
    with db() as con:
        cur = con.execute(
            f"UPDATE card_sheets SET {','.join(f + '=?' for f in CARD_SHEET_FIELDS)} WHERE id=?",
            (*[d[f] for f in CARD_SHEET_FIELDS], sid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "fiche introuvable")
    return {"ok": True}


@app.delete("/api/card-sheets/{sid}")
def api_del_card_sheet(sid: str):
    with db() as con:
        con.execute("DELETE FROM card_sheet_listings WHERE sheet_id=?", (sid,))
        con.execute("DELETE FROM card_sheets WHERE id=?", (sid,))
    media_mod.delete_item_dir(CARD_SHEET_MEDIA, sid)  # pas d'orphelin sur le volume
    return {"ok": True}


@app.post("/api/card-sheets/{sid}/archive")
def api_archive_card_sheet(sid: str):
    with db() as con:
        cur = con.execute("UPDATE card_sheets SET status='archived' WHERE id=?", (sid,))
        if not cur.rowcount:
            raise HTTPException(404, "fiche introuvable")
    return {"ok": True}


@app.post("/api/card-sheets/{sid}/realize")
def api_realize_card_sheet(sid: str, p: dict = Body(...)):
    """Bascule au portefeuille avec le prix d'achat réellement constaté (coût
    de revient réel), pas le prix max calculé — l'utilisateur saisit ce qu'il
    a vraiment payé."""
    with db() as con:
        row = con.execute("SELECT * FROM card_sheets WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "fiche introuvable")
    d = dict(row)
    buy_price = max(0.0, float(p.get("buy_price") or 0))
    qty = max(1, int(p.get("qty") or 1))
    buy_date = str(p.get("buy_date") or date.today().isoformat())[:10]
    now = datetime.now().isoformat(timespec="seconds")
    iid = d["item_id"]
    with db() as con:
        if iid:
            con.execute("UPDATE items SET status='owned', buy_price=?, qty=?, buy_date=? WHERE id=?",
                        (buy_price, qty, buy_date, iid))
        else:
            iid = nid()
            con.execute(
                "INSERT INTO items(id,name,type,lang,grade,set_name,qty,buy_price,buy_date,notes,status,target_price,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, d["name"] or "Item sans nom", d["type"] if d["type"] in ("loose", "gradee") else "loose",
                 d["lang"] or "FR", d["grade"], d["set_name"] or "", qty, buy_price, buy_date,
                 d["notes"], "owned", 0.0, now),
            )
        con.execute("UPDATE card_sheets SET status='done', item_id=? WHERE id=?", (iid, sid))
    return {"ok": True, "item_id": iid, "buy_price": buy_price}


def clean_card_listing(p: dict) -> dict:
    return {
        "platform": p.get("platform") if p.get("platform") in card_deals_mod.BUY_PLATFORMS else "ebay",
        "url": str(p.get("url", ""))[:500],
        "price": max(0.0, float(p.get("price") or 0)),
        "shipping": max(0.0, float(p.get("shipping") or 0)),
    }


@app.post("/api/card-sheets/{sid}/listings")
def api_add_card_listing(sid: str, p: dict = Body(...)):
    d = clean_card_listing(p)
    lid = nid()
    with db() as con:
        if not con.execute("SELECT 1 FROM card_sheets WHERE id=?", (sid,)).fetchone():
            raise HTTPException(404, "fiche introuvable")
        con.execute(
            "INSERT INTO card_sheet_listings(id,sheet_id,platform,url,price,shipping,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (lid, sid, d["platform"], d["url"], d["price"], d["shipping"],
             datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": lid}


@app.delete("/api/card-sheets/{sid}/listings/{lid}")
def api_del_card_listing(sid: str, lid: str):
    with db() as con:
        con.execute("DELETE FROM card_sheet_listings WHERE id=? AND sheet_id=?", (lid, sid))
    return {"ok": True}


# --- photo de fiche carte (une seule, facultative — mêmes règles que les items) ---

@app.post("/api/card-sheets/{sid}/photo")
async def api_add_card_sheet_photo(sid: str, file: UploadFile = File(...)):
    """Upload (ou remplace) l'unique photo d'une fiche. Entièrement facultatif :
    une fiche sans photo se crée et se calcule normalement."""
    with db() as con:
        row = con.execute("SELECT photo_id FROM card_sheets WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "fiche introuvable")
        old_photo_id = row["photo_id"]

    raw = await file.read()
    try:
        info = media_mod.save_photo(CARD_SHEET_MEDIA, sid, raw, (file.content_type or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))

    with db() as con:
        con.execute(
            "UPDATE card_sheets SET photo_id=?, photo_size_bytes=?, photo_width=?, photo_height=? WHERE id=?",
            (info["id"], info["size_bytes"], info["width"], info["height"], sid),
        )
    if old_photo_id:
        # Remplacement : l'ancien fichier devient orphelin sur le volume si on ne l'efface pas.
        media_mod.delete_photo(CARD_SHEET_MEDIA, sid, old_photo_id)
    return {"id": info["id"], "url": f"/api/card-sheets/{sid}/photo",
            "thumb_url": f"/api/card-sheets/{sid}/photo/thumb"}


@app.delete("/api/card-sheets/{sid}/photo")
def api_del_card_sheet_photo(sid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM card_sheets WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "fiche introuvable")
        pid = row["photo_id"]
        con.execute(
            "UPDATE card_sheets SET photo_id=NULL, photo_size_bytes=NULL, photo_width=NULL, photo_height=NULL WHERE id=?",
            (sid,),
        )
    if pid:
        media_mod.delete_photo(CARD_SHEET_MEDIA, sid, pid)
    return {"ok": True}


@app.get("/api/card-sheets/{sid}/photo")
def api_get_card_sheet_photo(sid: str):
    """Sert l'original. Protégé par le middleware auth global — jamais public."""
    with db() as con:
        row = con.execute("SELECT photo_id FROM card_sheets WHERE id=?", (sid,)).fetchone()
    pid = row["photo_id"] if row else None
    path = media_mod.photo_path(CARD_SHEET_MEDIA, sid, pid, thumb=False) if pid else None
    if not path:
        raise HTTPException(404, "photo introuvable")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/card-sheets/{sid}/photo/thumb")
def api_get_card_sheet_thumb(sid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM card_sheets WHERE id=?", (sid,)).fetchone()
    pid = row["photo_id"] if row else None
    path = media_mod.photo_path(CARD_SHEET_MEDIA, sid, pid, thumb=True) if pid else None
    if not path:
        raise HTTPException(404, "vignette introuvable")
    return FileResponse(path, media_type="image/webp")


# --- commandes d'import Japon ---

IMPORT_ORDER_FIELDS = ["name", "order_date", "supplier", "fx_spread_pct",
                        "fee_proxy_pct", "fee_proxy_fixed_jpy", "n_orders",
                        "fee_domestic_jpy", "fee_consolidation_jpy",
                        "fee_intl_shipping_jpy", "fee_payment_pct",
                        "vat_rate_pct", "duty_rate_pct", "carrier_fee_eur",
                        "ioss_enabled", "split_mode", "low_margin_alert_pct", "notes"]


def clean_import_order(p: dict) -> dict:
    def numopt(k):
        v = p.get(k)
        return float(v) if v not in (None, "") else None
    return {
        "name": str(p.get("name", ""))[:200],
        "order_date": str(p.get("order_date") or date.today().isoformat())[:10],
        "supplier": str(p.get("supplier") or "Buyee")[:80],
        "fx_spread_pct": numopt("fx_spread_pct"),
        "fee_proxy_pct": max(0.0, float(p.get("fee_proxy_pct") or 0)),
        "fee_proxy_fixed_jpy": max(0.0, float(p.get("fee_proxy_fixed_jpy") or 0)),
        "n_orders": max(1, int(p.get("n_orders") or 1)),
        "fee_domestic_jpy": max(0.0, float(p.get("fee_domestic_jpy") or 0)),
        "fee_consolidation_jpy": max(0.0, float(p.get("fee_consolidation_jpy") or 0)),
        "fee_intl_shipping_jpy": max(0.0, float(p.get("fee_intl_shipping_jpy") or 0)),
        "fee_payment_pct": max(0.0, float(p.get("fee_payment_pct") or 0)),
        "vat_rate_pct": numopt("vat_rate_pct"),
        "duty_rate_pct": numopt("duty_rate_pct"),
        "carrier_fee_eur": numopt("carrier_fee_eur"),
        "ioss_enabled": int(bool(p.get("ioss_enabled"))),
        "split_mode": p.get("split_mode") if p.get("split_mode") in ("value", "equal") else "value",
        "low_margin_alert_pct": numopt("low_margin_alert_pct"),
        "notes": str(p.get("notes", ""))[:2000],
    }


@app.post("/api/import-orders")
def api_add_import_order(p: dict = Body(...)):
    d = clean_import_order(p)
    oid = nid()
    with db() as con:
        con.execute(
            f"INSERT INTO import_orders(id,{','.join(IMPORT_ORDER_FIELDS)},created_at) "
            f"VALUES(?,{','.join('?' * len(IMPORT_ORDER_FIELDS))},?)",
            (oid, *[d[f] for f in IMPORT_ORDER_FIELDS], datetime.now().isoformat(timespec="seconds")),
        )
    return {"id": oid}


@app.put("/api/import-orders/{oid}")
def api_edit_import_order(oid: str, p: dict = Body(...)):
    with db() as con:
        row = con.execute("SELECT status FROM import_orders WHERE id=?", (oid,)).fetchone()
        if not row:
            raise HTTPException(404, "commande introuvable")
        if row["status"] != "brouillon":
            raise HTTPException(400, "commande déjà passée : seuls les montants reçus sont modifiables (voir /receive)")
        d = clean_import_order(p)
        con.execute(
            f"UPDATE import_orders SET {','.join(f + '=?' for f in IMPORT_ORDER_FIELDS)} WHERE id=?",
            (*[d[f] for f in IMPORT_ORDER_FIELDS], oid),
        )
    return {"ok": True}


@app.delete("/api/import-orders/{oid}")
def api_del_import_order(oid: str):
    with db() as con:
        con.execute("DELETE FROM import_order_lines WHERE order_id=?", (oid,))
        con.execute("DELETE FROM import_orders WHERE id=?", (oid,))
    return {"ok": True}


@app.post("/api/import-orders/{oid}/refresh-fx")
def api_refresh_fx(oid: str):
    """Rafraîchit le taux JPY->EUR, uniquement tant que la commande est en
    brouillon (au-delà, le taux est figé pour la reproductibilité du calcul)."""
    with db() as con:
        row = con.execute("SELECT status FROM import_orders WHERE id=?", (oid,)).fetchone()
        if not row:
            raise HTTPException(404, "commande introuvable")
        if row["status"] != "brouillon":
            raise HTTPException(400, "taux déjà figé (commande passée)")
    rate = fetch_jpy_eur_rate()
    if rate is None:
        raise HTTPException(503, "taux de change indisponible pour le moment (frankfurter.dev injoignable)")
    with db() as con:
        con.execute("UPDATE import_orders SET fx_rate=?, fx_rate_at=? WHERE id=?",
                    (rate, datetime.now().isoformat(timespec="seconds"), oid))
    return {"ok": True, "fx_rate": rate}


@app.post("/api/import-orders/{oid}/status")
def api_set_order_status(oid: str, p: dict = Body(...)):
    """Transition de statut. Au passage à 'commandee', le taux de change est
    figé une fois pour toutes (reproductibilité du calcul même si le taux
    bouge après) — sauf s'il l'était déjà (repassage impossible en arrière)."""
    new_status = p.get("status")
    if new_status not in ("brouillon", "commandee", "recue"):
        raise HTTPException(400, "statut invalide")
    with db() as con:
        row = con.execute("SELECT * FROM import_orders WHERE id=?", (oid,)).fetchone()
        if not row:
            raise HTTPException(404, "commande introuvable")
        d = dict(row)
        if new_status == "commandee" and d["status"] == "brouillon":
            lines = [dict(r) for r in con.execute(
                "SELECT * FROM import_order_lines WHERE order_id=?", (oid,)
            )]
            # Une commande entièrement saisie en € n'a besoin d'aucun taux de
            # change : elle doit pouvoir être validée même si frankfurter.dev
            # est injoignable (aucun appel réseau requis dans ce cas).
            if card_deals_mod.order_needs_fx(d, lines):
                rate = d["fx_rate"] or fetch_jpy_eur_rate()
                if rate is None:
                    raise HTTPException(503, "taux de change indisponible : réessaie, ou repasse en brouillon pour raffraîchir plus tard")
            else:
                rate = d["fx_rate"]
            con.execute("UPDATE import_orders SET status=?, fx_rate=?, fx_rate_at=? WHERE id=?",
                        (new_status, rate, d["fx_rate_at"] or datetime.now().isoformat(timespec="seconds"), oid))
        else:
            con.execute("UPDATE import_orders SET status=? WHERE id=?", (new_status, oid))
    return {"ok": True}


@app.put("/api/import-orders/{oid}/debit")
def api_set_order_debit(oid: str, p: dict = Body(...)):
    """Montant réellement débité en € (relevé bancaire) : éditable à tout
    moment, quel que soit le statut — sert uniquement à calculer le taux de
    change effectif obtenu, n'affecte aucun autre calcul de la commande."""
    v = p.get("received_debit_eur")
    val = max(0.0, float(v)) if v not in (None, "") else None
    with db() as con:
        cur = con.execute("UPDATE import_orders SET received_debit_eur=? WHERE id=?", (val, oid))
        if not cur.rowcount:
            raise HTTPException(404, "commande introuvable")
    return {"ok": True}


@app.post("/api/import-orders/{oid}/receive")
def api_receive_order(oid: str, p: dict = Body(...)):
    """Saisie des montants réellement facturés à réception (port international,
    droits, TVA, frais de dossier) : le coût de revient est recalculé
    ENTIÈREMENT sur ces montants réels côté build_import_order_view (par ligne
    et au total), l'écart estimé/réel reste visible (computed.order_gap_*,
    computed.lines[].gap_*). Rappelable à volonté une fois la commande reçue
    (pas seulement au premier passage) pour corriger une saisie."""
    def numopt(k):
        v = p.get(k)
        return max(0.0, float(v)) if v not in (None, "") else None
    with db() as con:
        cur = con.execute(
            "UPDATE import_orders SET status='recue', received_duty_eur=?, received_vat_eur=?, "
            "received_carrier_fee_eur=?, received_intl_shipping_eur=?, received_total_eur=? WHERE id=?",
            (numopt("received_duty_eur"), numopt("received_vat_eur"), numopt("received_carrier_fee_eur"),
             numopt("received_intl_shipping_eur"), numopt("received_total_eur"), oid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "commande introuvable")
    return {"ok": True}


def clean_order_line(p: dict) -> dict:
    currency = "EUR" if p.get("unit_currency") == "EUR" else "JPY"
    return {
        "item_id": (str(p["item_id"]) if p.get("item_id") else None),
        "name": str(p.get("name", ""))[:200],
        "type": p.get("type") if p.get("type") in ("scelle", "loose", "gradee") else "scelle",
        "qty": max(1, int(p.get("qty") or 1)),
        "unit_currency": currency,
        "unit_price_jpy": max(0.0, float(p.get("unit_price_jpy") or 0)),
        # Montant réel, saisi et conservé tel quel — jamais recalculé au taux
        # de change (cf. card_deals.build_import_order_view).
        "unit_price_eur": (max(0.0, float(p["unit_price_eur"])) if p.get("unit_price_eur") not in (None, "") else None),
        "resale_target_eur": (float(p["resale_target_eur"]) if p.get("resale_target_eur") not in (None, "") else None),
        "resale_platform": p.get("resale_platform") if p.get("resale_platform") in card_deals_mod.SELL_PLATFORMS else None,
        "card_id": (str(p["card_id"]) if p.get("card_id") else None),
    }


@app.post("/api/import-orders/{oid}/lines")
def api_add_order_line(oid: str, p: dict = Body(...)):
    d = clean_order_line(p)
    if not d["name"]:
        raise HTTPException(400, "nom manquant")
    lid = nid()
    with db() as con:
        if not con.execute("SELECT 1 FROM import_orders WHERE id=?", (oid,)).fetchone():
            raise HTTPException(404, "commande introuvable")
        maxo = con.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM import_order_lines WHERE order_id=?", (oid,)
        ).fetchone()["m"]
        overridden = _resale_overridden(con, d["card_id"], d["resale_target_eur"], d["resale_platform"])
        con.execute(
            "INSERT INTO import_order_lines(id,order_id,item_id,name,type,qty,unit_currency,"
            "unit_price_jpy,unit_price_eur,resale_target_eur,resale_platform,sort_order,card_id,"
            "resale_target_overridden)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, oid, d["item_id"], d["name"], d["type"], d["qty"], d["unit_currency"],
             d["unit_price_jpy"], d["unit_price_eur"], d["resale_target_eur"], d["resale_platform"], maxo + 1,
             d["card_id"], overridden),
        )
    return {"id": lid}


@app.put("/api/import-order-lines/{lid}")
def api_edit_order_line(lid: str, p: dict = Body(...)):
    d = clean_order_line(p)
    with db() as con:
        overridden = _resale_overridden(con, d["card_id"], d["resale_target_eur"], d["resale_platform"])
        cur = con.execute(
            "UPDATE import_order_lines SET item_id=?,name=?,type=?,qty=?,unit_currency=?,"
            "unit_price_jpy=?,unit_price_eur=?,resale_target_eur=?,resale_platform=?,card_id=?,"
            "resale_target_overridden=? WHERE id=?",
            (d["item_id"], d["name"], d["type"], d["qty"], d["unit_currency"],
             d["unit_price_jpy"], d["unit_price_eur"], d["resale_target_eur"], d["resale_platform"],
             d["card_id"], overridden, lid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "ligne introuvable")
    return {"ok": True}


@app.put("/api/import-order-lines/{lid}/reset-resale-target")
def api_reset_order_line_resale_target(lid: str):
    """« Revenir à la valeur de la fiche » : réaligne la ligne sur la valeur
    actuelle de la carte liée et efface le repère de surcharge."""
    with db() as con:
        row = con.execute("SELECT card_id FROM import_order_lines WHERE id=?", (lid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        if not row["card_id"]:
            raise HTTPException(400, "ligne non liée à une carte du référentiel")
        card = con.execute("SELECT resale_target_eur, default_resale_platform FROM cards WHERE id=?",
                            (row["card_id"],)).fetchone()
        con.execute(
            "UPDATE import_order_lines SET resale_target_eur=?, resale_platform=?, resale_target_overridden=0 "
            "WHERE id=?",
            (card["resale_target_eur"] if card else None, card["default_resale_platform"] if card else None, lid),
        )
    return {"ok": True}


@app.delete("/api/import-order-lines/{lid}")
def api_del_order_line(lid: str):
    with db() as con:
        con.execute("DELETE FROM import_order_lines WHERE id=?", (lid,))
    return {"ok": True}


@app.post("/api/import-order-lines/{lid}/realize")
def api_realize_order_line(lid: str, p: dict = Body(...)):
    """Bascule une ligne au portefeuille avec son coût de revient calculé
    comme prix d'achat, sauf surcharge explicite dans le corps (buy_price)."""
    with db() as con:
        line = con.execute("SELECT * FROM import_order_lines WHERE id=?", (lid,)).fetchone()
        if not line:
            raise HTTPException(404, "ligne introuvable")
        line = dict(line)
        order = dict(con.execute("SELECT * FROM import_orders WHERE id=?", (line["order_id"],)).fetchone())
        lines = [dict(r) for r in con.execute(
            "SELECT * FROM import_order_lines WHERE order_id=? ORDER BY sort_order", (line["order_id"],)
        )]
    cs = get_card_settings()
    computed = card_deals_mod.build_import_order_view(order, lines, cs, order["fx_rate"])
    row = next((r for r in computed["lines"] if r["id"] == lid), None)
    unit_cost = float(p["buy_price"]) if p.get("buy_price") not in (None, "") else (row["unit_landed_cost"] if row else 0.0)
    qty = max(1, int(p.get("qty") or line["qty"]))
    buy_date = str(p.get("buy_date") or date.today().isoformat())[:10]
    now = datetime.now().isoformat(timespec="seconds")
    iid = line["item_id"]
    with db() as con:
        if iid:
            con.execute("UPDATE items SET status='owned', buy_price=?, qty=?, buy_date=? WHERE id=?",
                        (unit_cost, qty, buy_date, iid))
        else:
            iid = nid()
            con.execute(
                "INSERT INTO items(id,name,type,lang,grade,set_name,qty,buy_price,buy_date,notes,status,target_price,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, line["name"] or "Item sans nom", line["type"], "JP", "", "", qty, unit_cost, buy_date,
                 "", "owned", 0.0, now),
            )
        con.execute("UPDATE import_order_lines SET item_id=? WHERE id=?", (iid, lid))
    return {"ok": True, "item_id": iid, "buy_price": unit_cost}


# --------------------------------------------------------------------- stock

STOCK_FIELDS = ["linked_item_id", "name", "set_name", "card_number", "lang", "type", "grade",
                "cost_basis", "buy_date", "buy_platform", "buy_url",
                "target_price", "target_platform", "notes", "source_order_line_id",
                "card_id", "target_overridden"]


def clean_stock_item(p: dict) -> dict:
    def numopt(k):
        v = p.get(k)
        return float(v) if v not in (None, "") else None
    return {
        "linked_item_id": (str(p["linked_item_id"]) if p.get("linked_item_id") else None),
        "name": str(p.get("name", "")).strip()[:200],
        "set_name": str(p.get("set_name", ""))[:120],
        "card_number": str(p.get("card_number", ""))[:40],
        "lang": str(p.get("lang", "FR"))[:10],
        "type": p.get("type") if p.get("type") in ("loose", "gradee") else "loose",
        "grade": str(p.get("grade", ""))[:40],
        "cost_basis": max(0.0, float(p.get("cost_basis") or 0)),
        "buy_date": str(p.get("buy_date") or date.today().isoformat())[:10],
        "buy_platform": str(p.get("buy_platform", ""))[:80],
        "buy_url": str(p.get("buy_url", ""))[:500],
        "target_price": numopt("target_price"),
        "target_platform": p.get("target_platform") if p.get("target_platform") in card_deals_mod.SELL_PLATFORMS else None,
        "notes": str(p.get("notes", ""))[:2000],
        "source_order_line_id": (str(p["source_order_line_id"]) if p.get("source_order_line_id") else None),
        "card_id": (str(p["card_id"]) if p.get("card_id") else None),
        # Recalculé côté serveur juste avant l'écriture (cf. _resale_overridden) ;
        # 0 par défaut ici, jamais pris tel quel depuis le client.
        "target_overridden": 0,
    }


def _stock_photo_urls(row: dict) -> dict:
    if row.get("photo_id"):
        return {"photo_url": f"/api/stock/{row['id']}/photo", "photo_thumb_url": f"/api/stock/{row['id']}/photo/thumb"}
    return {"photo_url": None, "photo_thumb_url": None}


def _stock_view(row: dict, events: list[dict], cards_by_id: dict | None = None,
                 source_orders: dict | None = None) -> dict:
    d = dict(row)
    delays = stock_mod.compute_delays(events)
    d["delays"] = {"import_days": delays["import_days"], "listing_days": delays["listing_days"],
                    "sale_days": delays["sale_days"]}
    d["days_in_status"] = stock_mod.days_in_current_status(d["status"], events)
    d["events"] = events
    d.update(_stock_photo_urls(d))
    d["photo_url"], d["photo_thumb_url"] = _resolve_photo_urls(d.get("card_id"), d["photo_url"], d["photo_thumb_url"])
    cb = d.get("cost_basis")
    d["expected_margin_pct"] = (round((d["target_price"] - cb) / cb * 100, 1)
                                 if d.get("target_price") and cb else None)
    # Alerte de dépassement : le prix d'achat réel comparé au prix max prudent
    # de la carte liée. Jamais bloquant — juste visible avant que ça devienne
    # une découverte à la réception du colis.
    card = (cards_by_id or {}).get(d.get("card_id"))
    bm = card.get("buy_max_computed") if card else None
    over = round(cb - bm, 2) if (bm is not None and cb) else None
    d["buy_over_max_eur"] = over if (over is not None and over > 0) else None
    d["buy_over_max_pct"] = round(over / bm * 100, 1) if (d["buy_over_max_eur"] and bm) else None
    # Origine du coût de revient, quand il vient d'un envoi direct depuis une
    # commande d'import — traçabilité du montant, pas juste un lien décoratif.
    d["source_order"] = (source_orders or {}).get(d.get("source_order_line_id"))
    return d


@app.get("/api/stock")
def api_list_stock():
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM stock_items ORDER BY created_at DESC")]
        all_events = [dict(r) for r in con.execute("SELECT * FROM stock_events ORDER BY at")]
        cards_by_id = {r["id"]: dict(r) for r in con.execute("SELECT id, buy_max_computed FROM cards")}
        source_orders = {r["line_id"]: {"order_id": r["order_id"], "order_name": r["order_name"]} for r in con.execute(
            "SELECT iol.id AS line_id, io.id AS order_id, io.name AS order_name "
            "FROM import_order_lines iol JOIN import_orders io ON io.id = iol.order_id"
        )}
    events_by_stock: dict[str, list] = {}
    for e in all_events:
        events_by_stock.setdefault(e["stock_id"], []).append(e)
    views = [_stock_view(r, events_by_stock.get(r["id"], []), cards_by_id, source_orders) for r in rows]
    kpis = stock_mod.build_kpis(rows, events_by_stock)
    n_over_max = sum(1 for v in views if v.get("buy_over_max_eur"))
    return {"stock": views, "kpis": kpis, "n_over_max": n_over_max}


@app.post("/api/stock")
def api_add_stock(p: dict = Body(...)):
    d = clean_stock_item(p)
    if not d["name"]:
        raise HTTPException(400, "nom manquant")
    now = datetime.now().isoformat(timespec="seconds")
    iid = d["linked_item_id"]
    sid = nid()
    with db() as con:
        if not iid:
            # Toujours un item lié : même sans lien explicite, il en faut un
            # pour que le relevé "vente perso" ait un endroit où exister.
            # En veille : ne pèse jamais dans le portefeuille.
            iid = nid()
            con.execute(
                "INSERT INTO items(id,name,type,lang,grade,set_name,qty,buy_price,buy_date,notes,status,target_price,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, d["name"], d["type"], d["lang"] or "FR", d["grade"], d["set_name"],
                 1, 0.0, d["buy_date"], "", "watch", 0.0, now),
            )
            d["linked_item_id"] = iid
        d["target_overridden"] = _resale_overridden(con, d["card_id"], d["target_price"], d["target_platform"])
        con.execute(
            f"INSERT INTO stock_items(id,{','.join(STOCK_FIELDS)},status,created_at) "
            f"VALUES(?,{','.join('?' * len(STOCK_FIELDS))},?,?)",
            (sid, *[d[f] for f in STOCK_FIELDS], "achete", now),
        )
        con.execute("INSERT INTO stock_events(id,stock_id,from_status,to_status,at) VALUES(?,?,?,?,?)",
                    (nid(), sid, None, "achete", d["buy_date"]))
    return {"id": sid, "linked_item_id": iid}


@app.put("/api/stock/{sid}")
def api_edit_stock(sid: str, p: dict = Body(...)):
    d = clean_stock_item(p)
    if not d["name"]:
        raise HTTPException(400, "nom manquant")
    with db() as con:
        d["target_overridden"] = _resale_overridden(con, d["card_id"], d["target_price"], d["target_platform"])
        cur = con.execute(
            f"UPDATE stock_items SET {','.join(f + '=?' for f in STOCK_FIELDS)} WHERE id=?",
            (*[d[f] for f in STOCK_FIELDS], sid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "ligne introuvable")
    return {"ok": True}


@app.put("/api/stock/{sid}/reset-target")
def api_reset_stock_target(sid: str):
    """« Revenir à la valeur de la fiche » côté stock."""
    with db() as con:
        row = con.execute("SELECT card_id FROM stock_items WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        if not row["card_id"]:
            raise HTTPException(400, "ligne non liée à une carte du référentiel")
        card = con.execute("SELECT resale_target_eur, default_resale_platform FROM cards WHERE id=?",
                            (row["card_id"],)).fetchone()
        con.execute(
            "UPDATE stock_items SET target_price=?, target_platform=?, target_overridden=0 WHERE id=?",
            (card["resale_target_eur"] if card else None, card["default_resale_platform"] if card else None, sid),
        )
    return {"ok": True}


@app.post("/api/stock/{sid}/duplicate")
def api_duplicate_stock(sid: str, p: dict = Body(...)):
    """« Dupliquer ×N » : N nouveaux exemplaires indépendants (même carte,
    même prix d'achat de départ), chacun avec son propre id — jamais une
    quantité sur une seule ligne (cf. le principe du module stock)."""
    n = max(1, min(20, int(p.get("n") or 1)))
    with db() as con:
        row = con.execute("SELECT * FROM stock_items WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        d = dict(row)
        now = datetime.now().isoformat(timespec="seconds")
        new_ids = []
        for _ in range(n):
            new_id = nid()
            con.execute(
                f"INSERT INTO stock_items(id,{','.join(STOCK_FIELDS)},status,created_at) "
                f"VALUES(?,{','.join('?' * len(STOCK_FIELDS))},?,?)",
                (new_id, *[d[f] for f in STOCK_FIELDS], "achete", now),
            )
            con.execute("INSERT INTO stock_events(id,stock_id,from_status,to_status,at) VALUES(?,?,?,?,?)",
                        (nid(), new_id, None, "achete", d.get("buy_date") or date.today().isoformat()))
            new_ids.append(new_id)
    return {"ids": new_ids}


@app.delete("/api/stock/{sid}")
def api_del_stock(sid: str):
    with db() as con:
        con.execute("DELETE FROM stock_events WHERE stock_id=?", (sid,))
        con.execute("DELETE FROM stock_items WHERE id=?", (sid,))
    media_mod.delete_item_dir(STOCK_MEDIA, sid)
    return {"ok": True}


def _add_own_sale_comp(iid: str | None, price: float, at: str) -> None:
    if not iid:
        return
    with db() as con:
        if not con.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
            return
        con.execute(
            "INSERT INTO comps(id,item_id,price,date,source,note,excluded,sold_count,shipping) VALUES(?,?,?,?,?,?,?,?,?)",
            (nid(), iid, price, str(at)[:10], "own_sale", "", 0, 1, 0.0),
        )


def _transfer_stock_to_portfolio(stock_row: dict) -> str:
    """Toujours un NOUVEL item portefeuille (jamais de réécriture de
    linked_item_id) : plusieurs lignes de stock peuvent partager le même item
    lié pour les relevés de prix (même carte), sans se marcher dessus ici."""
    now = datetime.now().isoformat(timespec="seconds")
    iid = nid()
    with db() as con:
        con.execute(
            "INSERT INTO items(id,name,type,lang,grade,set_name,qty,buy_price,buy_date,notes,status,target_price,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, stock_row["name"], stock_row["type"], stock_row["lang"] or "FR", stock_row["grade"],
             stock_row["set_name"], 1, stock_row["cost_basis"], stock_row["buy_date"] or date.today().isoformat(),
             stock_row["notes"], "owned", 0.0, now),
        )
    return iid


@app.post("/api/stock/{sid}/status")
def api_stock_status(sid: str, p: dict = Body(...)):
    to_status = p.get("to_status")
    if to_status not in stock_mod.STATUSES:
        raise HTTPException(400, "statut invalide")
    at = p.get("at") or datetime.now().isoformat(timespec="seconds")
    with db() as con:
        row = con.execute("SELECT * FROM stock_items WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        d = dict(row)
        cur_status = d["status"]
        updates: dict = {"status": to_status}
        if to_status == "vendu":
            if p.get("sale_price") in (None, "") or not p.get("sale_platform"):
                raise HTTPException(400, "prix de vente et plateforme requis")
            sale_price = float(p["sale_price"])
            sale_platform = p["sale_platform"]
            manual_net = p.get("sale_net") not in (None, "")
            if manual_net:
                sale_net = float(p["sale_net"])
            else:
                cs = get_card_settings()
                sale_net = stock_mod.compute_sale_net(sale_price, sale_platform, cs)["net"]
            updates.update({"sale_price": sale_price, "sale_platform": sale_platform,
                             "sale_net": sale_net, "sale_net_manual": int(manual_net)})
        con.execute(f"UPDATE stock_items SET {','.join(k + '=?' for k in updates)} WHERE id=?",
                    (*updates.values(), sid))
        con.execute("INSERT INTO stock_events(id,stock_id,from_status,to_status,at) VALUES(?,?,?,?,?)",
                    (nid(), sid, cur_status, to_status, at))
    if to_status == "vendu":
        _add_own_sale_comp(d["linked_item_id"], updates["sale_price"], at)
    new_item_id = None
    if to_status == "conserve":
        new_item_id = _transfer_stock_to_portfolio(d)
    return {"ok": True, "item_id": new_item_id}


@app.put("/api/stock/{sid}/sale")
def api_correct_stock_sale(sid: str, p: dict = Body(...)):
    """Corrige les montants d'une vente déjà enregistrée, sans rejouer le
    changement de statut (donc sans dupliquer l'événement ni le relevé)."""
    with db() as con:
        row = con.execute("SELECT * FROM stock_items WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        d = dict(row)
        if d["status"] != "vendu":
            raise HTTPException(400, "cette ligne n'est pas vendue")
        sale_price = float(p["sale_price"]) if p.get("sale_price") not in (None, "") else d["sale_price"]
        sale_platform = p.get("sale_platform") or d["sale_platform"]
        manual_net = p.get("sale_net") not in (None, "")
        if manual_net:
            sale_net = float(p["sale_net"])
        else:
            cs = get_card_settings()
            sale_net = stock_mod.compute_sale_net(sale_price, sale_platform, cs)["net"]
        con.execute(
            "UPDATE stock_items SET sale_price=?, sale_platform=?, sale_net=?, sale_net_manual=? WHERE id=?",
            (sale_price, sale_platform, sale_net, int(manual_net), sid),
        )
    return {"ok": True}


@app.get("/api/stock/{sid}/events")
def api_get_stock_events(sid: str):
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM stock_events WHERE stock_id=? ORDER BY at", (sid,))]
    return {"events": rows}


@app.put("/api/stock-events/{eid}")
def api_edit_stock_event(eid: str, p: dict = Body(...)):
    """Correction d'une date après coup — les 3 délais sont recalculés à la
    prochaine lecture, rien d'autre à faire côté serveur."""
    at = p.get("at")
    if not at:
        raise HTTPException(400, "date manquante")
    with db() as con:
        cur = con.execute("UPDATE stock_events SET at=? WHERE id=?", (at, eid))
        if not cur.rowcount:
            raise HTTPException(404, "événement introuvable")
    return {"ok": True}


@app.post("/api/items/{iid}/transfer-to-stock")
def api_transfer_item_to_stock(iid: str):
    """Portefeuille -> Stock (l'inverse de 'conservé'). qty>1 : décrémente
    d'une unité (le reste continue de compter normalement). qty=1 : l'item
    passe en veille (ne compte plus, mais l'historique de relevés survit —
    jamais de suppression, ce serait perdre la donnée marché)."""
    with db() as con:
        row = con.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, "item introuvable")
        it = dict(row)
        if con.execute("SELECT 1 FROM purchases WHERE item_id=?", (iid,)).fetchone():
            raise HTTPException(400, "item avec prix d'achat détaillés : ajuste les lots manuellement avant transfert")
        if it["qty"] > 1:
            con.execute("UPDATE items SET qty=? WHERE id=?", (it["qty"] - 1, iid))
        else:
            con.execute("UPDATE items SET status='watch' WHERE id=?", (iid,))
    d = {
        "linked_item_id": iid, "name": it["name"], "set_name": it["set_name"], "card_number": "",
        "lang": it["lang"], "type": it["type"] if it["type"] in ("loose", "gradee") else "loose",
        "grade": it["grade"], "cost_basis": it["buy_price"],
        "buy_date": it["buy_date"] or date.today().isoformat(),
        "buy_platform": "", "buy_url": "", "target_price": None, "target_platform": None,
        "notes": "", "source_order_line_id": None,
        "card_id": it.get("card_id"), "target_overridden": 0,
    }
    sid = nid()
    now = datetime.now().isoformat(timespec="seconds")
    with db() as con:
        con.execute(
            f"INSERT INTO stock_items(id,{','.join(STOCK_FIELDS)},status,created_at) "
            f"VALUES(?,{','.join('?' * len(STOCK_FIELDS))},?,?)",
            (sid, *[d[f] for f in STOCK_FIELDS], "en_stock", now),
        )
        con.execute("INSERT INTO stock_events(id,stock_id,from_status,to_status,at) VALUES(?,?,?,?,?)",
                    (nid(), sid, None, "en_stock", now))
    return {"id": sid}


@app.post("/api/import-order-lines/{lid}/to-stock")
def api_line_to_stock(lid: str):
    """Commande d'import -> Stock, directement (sans détour par le porte-
    feuille). Le prix d'achat de chaque exemplaire est le COÛT DE REVIENT
    calculé de la ligne (article + part des frais/taxes), les montants
    réellement facturés si la commande est reçue avec des frais réels saisis
    — jamais le seul prix d'article. qty>1 -> un stock_item par exemplaire,
    répartis au centime près (même logique que le total de la commande) pour
    que leur somme reconstitue exactement le coût de la ligne."""
    with db() as con:
        line = con.execute("SELECT * FROM import_order_lines WHERE id=?", (lid,)).fetchone()
        if not line:
            raise HTTPException(404, "ligne introuvable")
        line = dict(line)
        if con.execute("SELECT 1 FROM stock_items WHERE source_order_line_id=?", (lid,)).fetchone():
            raise HTTPException(400, "cette ligne a déjà été envoyée au stock")
        order = dict(con.execute("SELECT * FROM import_orders WHERE id=?", (line["order_id"],)).fetchone())
        lines = [dict(r) for r in con.execute(
            "SELECT * FROM import_order_lines WHERE order_id=? ORDER BY sort_order", (line["order_id"],)
        )]
        card = None
        if line.get("card_id"):
            crow = con.execute("SELECT * FROM cards WHERE id=?", (line["card_id"],)).fetchone()
            card = dict(crow) if crow else None
    cs = get_card_settings()
    computed = card_deals_mod.build_import_order_view(order, lines, cs, order["fx_rate"])
    row = next((r for r in computed["lines"] if r["id"] == lid), None)
    if not row:
        raise HTTPException(400, "impossible de calculer le coût de cette ligne")
    qty = max(1, int(line["qty"]))
    per_unit_cost = (card_deals_mod._round_alloc(row["landed_total"], [1.0] * qty)
                      if qty > 1 else [row["landed_total"]])
    name = card["name"] if card else (line["name"] or "Carte sans nom")
    set_name = card["set_name"] if card else ""
    card_number = card["card_number"] if card else ""
    lang = (card["lang"] if card else "") or "FR"
    grade = card["grade"] if card else ""
    ctype = card["type"] if card else (line["type"] if line["type"] in ("loose", "gradee") else "loose")
    buy_date = str(order.get("order_date") or date.today().isoformat())[:10]
    now = datetime.now().isoformat(timespec="seconds")
    new_ids = []
    with db() as con:
        for cost in per_unit_cost:
            sid = nid()
            d = {
                "linked_item_id": None, "name": name, "set_name": set_name, "card_number": card_number,
                "lang": lang, "type": ctype, "grade": grade, "cost_basis": cost, "buy_date": buy_date,
                "buy_platform": order.get("supplier") or "", "buy_url": "",
                "target_price": line.get("resale_target_eur"), "target_platform": line.get("resale_platform"),
                "notes": "", "source_order_line_id": lid,
                "card_id": line.get("card_id"), "target_overridden": 0,
            }
            con.execute(
                f"INSERT INTO stock_items(id,{','.join(STOCK_FIELDS)},status,created_at) "
                f"VALUES(?,{','.join('?' * len(STOCK_FIELDS))},?,?)",
                (sid, *[d[f] for f in STOCK_FIELDS], "achete", now),
            )
            con.execute("INSERT INTO stock_events(id,stock_id,from_status,to_status,at) VALUES(?,?,?,?,?)",
                        (nid(), sid, None, "achete", buy_date))
            new_ids.append(sid)
    return {"ids": new_ids}


# --- photo de ligne de stock (une seule, facultative — même pipeline que items/fiches) ---

@app.post("/api/stock/{sid}/photo")
async def api_add_stock_photo(sid: str, file: UploadFile = File(...)):
    with db() as con:
        row = con.execute("SELECT photo_id FROM stock_items WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        old_photo_id = row["photo_id"]
    raw = await file.read()
    try:
        info = media_mod.save_photo(STOCK_MEDIA, sid, raw, (file.content_type or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    with db() as con:
        con.execute(
            "UPDATE stock_items SET photo_id=?, photo_size_bytes=?, photo_width=?, photo_height=? WHERE id=?",
            (info["id"], info["size_bytes"], info["width"], info["height"], sid),
        )
    if old_photo_id:
        media_mod.delete_photo(STOCK_MEDIA, sid, old_photo_id)
    return {"id": info["id"], "url": f"/api/stock/{sid}/photo", "thumb_url": f"/api/stock/{sid}/photo/thumb"}


@app.delete("/api/stock/{sid}/photo")
def api_del_stock_photo(sid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM stock_items WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "ligne introuvable")
        pid = row["photo_id"]
        con.execute(
            "UPDATE stock_items SET photo_id=NULL, photo_size_bytes=NULL, photo_width=NULL, photo_height=NULL WHERE id=?",
            (sid,),
        )
    if pid:
        media_mod.delete_photo(STOCK_MEDIA, sid, pid)
    return {"ok": True}


@app.get("/api/stock/{sid}/photo")
def api_get_stock_photo(sid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM stock_items WHERE id=?", (sid,)).fetchone()
    pid = row["photo_id"] if row else None
    path = media_mod.photo_path(STOCK_MEDIA, sid, pid, thumb=False) if pid else None
    if not path:
        raise HTTPException(404, "photo introuvable")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/stock/{sid}/photo/thumb")
def api_get_stock_thumb(sid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM stock_items WHERE id=?", (sid,)).fetchone()
    pid = row["photo_id"] if row else None
    path = media_mod.photo_path(STOCK_MEDIA, sid, pid, thumb=True) if pid else None
    if not path:
        raise HTTPException(404, "vignette introuvable")
    return FileResponse(path, media_type="image/webp")


# --- Pick a card ---

def _pick_a_card_candidates(st: dict, cs: dict) -> list[dict]:
    items_by_id = {i["id"]: i for i in st["items"]}
    candidates = []
    with db() as con:
        sheets = [dict(r) for r in con.execute("SELECT * FROM card_sheets WHERE status='open'")]
        # Items en veille créés automatiquement comme simple point d'attache
        # pour les relevés du stock (aucun item_id fourni à la création d'une
        # ligne) : ce ne sont pas des cartes à acheter, à exclure des candidats.
        stock_linked_ids = {r["linked_item_id"] for r in con.execute(
            "SELECT DISTINCT linked_item_id FROM stock_items WHERE linked_item_id IS NOT NULL"
        )}
    fx_rate = fetch_jpy_eur_rate()
    for row in sheets:
        view = _card_sheet_view(row, items_by_id, cs, fx_rate)
        prudent = view["computed"]["scenarios"]["prudent"]
        if not prudent:
            continue
        ok_listings = [l for l in view["listings"] if l.get("verdict") is True]
        # Priorité à une annonce RÉELLEMENT trouvée sous le seuil (opportunité
        # concrète) ; sinon repli sur le plafond théorique du calcul inversé.
        cost_basis = min((l["total_cost"] for l in ok_listings), default=prudent["c_max"])
        item = items_by_id.get(row["item_id"]) if row["item_id"] else None
        candidates.append({
            "kind": "sheet", "id": row["id"], "name": view.get("item_name") or row["name"] or "Fiche sans nom",
            "cost_basis": round(cost_basis, 2), "net_estime": prudent["net"]["net"],
            "linked_item_id": row["item_id"], "type": row["type"], "grade": row["grade"],
            "target_price": prudent["resale_price"], "est_value": item["est"]["value"] if item else None,
            "market_sales_per_month": item["stats"]["sales_month"] if item else None,
            "photo_url": view.get("photo_thumb_url"),
        })
    for item in st["items"]:
        if item["status"] != "watch" or item["id"] in stock_linked_ids:
            continue
        est_val = item["est"]["value"]
        if not est_val:
            continue
        best_net = None
        for plat in card_deals_mod.SELL_PLATFORMS:
            sf = cs["sell_fees"].get(plat, {})
            n = card_deals_mod.net_from_resale(est_val, sf, 0.0)["net"]
            if best_net is None or n > best_net:
                best_net = n
        cost_basis = item["target_price"] or est_val
        candidates.append({
            "kind": "watch", "id": item["id"], "name": item["name"],
            "cost_basis": round(cost_basis, 2), "net_estime": best_net,
            "linked_item_id": item["id"], "type": item["type"], "grade": item["grade"],
            "target_price": item["target_price"] or None, "est_value": est_val,
            "market_sales_per_month": item["stats"]["sales_month"],
            "photo_url": ((item["photos"] or [{}])[0].get("thumb_url") if item.get("photos") else None),
        })
    return candidates


@app.get("/api/stock/pick-a-card")
def api_pick_a_card(budget: float | None = None):
    st = build_state(snapshot=False)
    cs = get_card_settings()
    candidates = _pick_a_card_candidates(st, cs)
    with db() as con:
        sold_rows = [dict(r) for r in con.execute("SELECT * FROM stock_items WHERE status='vendu'")]
        all_events = [dict(r) for r in con.execute("SELECT * FROM stock_events ORDER BY at")]
    events_by_stock: dict[str, list] = {}
    for e in all_events:
        events_by_stock.setdefault(e["stock_id"], []).append(e)
    return stock_mod.build_pick_a_card(candidates, sold_rows, events_by_stock, cs, budget=budget)


# --------------------------------------------------------- référentiel de cartes

def _copy_sheet_photo_to_card(sheet_id: str, sheet_photo_id: str, card_id: str) -> str | None:
    """Copie les deux fichiers déjà traités (original + vignette) d'une fiche
    carte vers le dossier de la carte du référentiel — pas un nouvel upload,
    juste un changement d'emplacement, avec un nouvel id de fichier pour ne
    jamais partager un id entre deux entités. Renvoie le nouveau photo_id, ou
    None si les fichiers sources sont introuvables."""
    orig = media_mod.photo_path(CARD_SHEET_MEDIA, sheet_id, sheet_photo_id, thumb=False)
    thumb = media_mod.photo_path(CARD_SHEET_MEDIA, sheet_id, sheet_photo_id, thumb=True)
    if not orig or not thumb:
        return None
    new_id = secrets.token_hex(8)
    dest = CARD_MEDIA / card_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{new_id}.webp").write_bytes(orig.read_bytes())
    (dest / f"{new_id}.thumb.webp").write_bytes(thumb.read_bytes())
    return new_id


CARD_FIELDS = ["name", "set_name", "card_number", "lang", "type", "grade", "profit_target_pct",
               "resale_mode", "resale_min", "resale_median", "resale_max", "buy_max_computed",
               "resale_target_eur", "default_resale_platform", "notes"]
CARD_REF_TABLES = ["items", "card_sheets", "import_order_lines", "stock_items", "card_listings"]


def clean_card(p: dict) -> dict:
    def numopt(k):
        v = p.get(k)
        return float(v) if v not in (None, "") else None
    return {
        "name": str(p.get("name", "")).strip()[:200],
        "set_name": str(p.get("set_name", ""))[:120],
        "card_number": str(p.get("card_number", ""))[:40],
        "lang": str(p.get("lang", "FR"))[:10],
        "type": p.get("type") if p.get("type") in ("loose", "gradee") else "loose",
        "grade": str(p.get("grade", ""))[:40],
        "profit_target_pct": numopt("profit_target_pct"),
        "resale_mode": "manual" if p.get("resale_mode") == "manual" else "auto",
        "resale_min": numopt("resale_min"), "resale_median": numopt("resale_median"), "resale_max": numopt("resale_max"),
        "buy_max_computed": numopt("buy_max_computed"),
        "resale_target_eur": numopt("resale_target_eur"),
        "default_resale_platform": (p.get("default_resale_platform")
                                     if p.get("default_resale_platform") in card_deals_mod.SELL_PLATFORMS else None),
        "notes": str(p.get("notes", ""))[:2000],
    }


def _resale_overridden(con: sqlite3.Connection, card_id: str | None, target, platform) -> int:
    """1 si (target, platform) diverge de la valeur par défaut de la carte
    liée — jamais saisi par le client, toujours recalculé côté serveur au
    moment de l'écriture. Sans carte liée, la question n'a pas de sens (0)."""
    if not card_id:
        return 0
    row = con.execute("SELECT resale_target_eur, default_resale_platform FROM cards WHERE id=?", (card_id,)).fetchone()
    if not row:
        return 0
    return int((target != row["resale_target_eur"]) or (platform != row["default_resale_platform"]))


def _identity_fields_items(row: dict) -> dict:
    return {"name": row["name"], "set_name": row.get("set_name") or "", "card_number": "",
            "lang": row.get("lang") or "", "grade": row.get("grade") or "",
            "type": row.get("type") if row.get("type") in ("loose", "gradee") else "loose"}


def _identity_fields_card_sheet(row: dict) -> dict:
    return {"name": row["name"], "set_name": row.get("set_name") or "", "card_number": row.get("card_number") or "",
            "lang": row.get("lang") or "", "grade": row.get("grade") or "",
            "type": row.get("type") if row.get("type") in ("loose", "gradee") else "loose"}


def _identity_fields_order_line(row: dict) -> dict:
    # Saisie volontairement pauvre à l'origine (nom/qté/prix seulement) : peu
    # de matière pour un rapprochement fiable, le score reflète honnêtement ça.
    return {"name": row["name"], "set_name": "", "card_number": "", "lang": "", "grade": "",
            "type": row.get("type") if row.get("type") in ("loose", "gradee") else "loose"}


def _identity_fields_stock(row: dict) -> dict:
    return {"name": row["name"], "set_name": row.get("set_name") or "", "card_number": row.get("card_number") or "",
            "lang": row.get("lang") or "", "grade": row.get("grade") or "",
            "type": row.get("type") if row.get("type") in ("loose", "gradee") else "loose"}


def _card_photo_urls(row: dict) -> dict:
    if row.get("photo_id"):
        return {"photo_url": f"/api/cards/{row['id']}/photo", "photo_thumb_url": f"/api/cards/{row['id']}/photo/thumb"}
    return {"photo_url": None, "photo_thumb_url": None}


def _resolve_photo_urls(card_id: str | None, own_url: str | None, own_thumb: str | None) -> tuple:
    """Règle de surcharge : la photo propre de l'exemplaire prime si elle
    existe (cet exemplaire précis peut différer visuellement — centrage, état
    réel photographié), sinon on retombe sur celle du référentiel (jamais
    d'écran vide juste parce que l'exemplaire n'a pas sa propre photo)."""
    if own_url:
        return own_url, own_thumb
    if card_id:
        with db() as con:
            row = con.execute("SELECT photo_id FROM cards WHERE id=?", (card_id,)).fetchone()
        if row and row["photo_id"]:
            return f"/api/cards/{card_id}/photo", f"/api/cards/{card_id}/photo/thumb"
    return own_url, own_thumb


def _card_view(row: dict) -> dict:
    d = dict(row)
    d.update(_card_photo_urls(d))
    exemplaires = []
    importable_sheet_photo = None
    with db() as con:
        for table, status_field in (("items", "status"), ("card_sheets", "status"),
                                     ("import_order_lines", None), ("stock_items", "status")):
            for r in con.execute(f"SELECT * FROM {table} WHERE card_id=?", (d["id"],)):
                rd = dict(r)
                exemplaires.append({"table": table, "id": rd["id"], "label": rd.get("name"),
                                     "status": rd.get(status_field) if status_field else None})
                # Cartes migrées avant que l'upload direct sur la carte n'existe :
                # la fiche liée avait déjà une photo, jamais recopiée. Propose
                # de la reprendre plutôt que de forcer un nouvel upload.
                if table == "card_sheets" and rd.get("photo_id") and not d.get("photo_id") and importable_sheet_photo is None:
                    importable_sheet_photo = rd["id"]
    d["exemplaires"] = exemplaires
    d["importable_sheet_photo"] = importable_sheet_photo
    return d


@app.get("/api/cards")
def api_list_cards():
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM cards WHERE merged_into_id IS NULL ORDER BY name"
        )]
    return {"cards": [_card_view(r) for r in rows]}


@app.post("/api/cards")
def api_add_card(p: dict = Body(...)):
    """Création manuelle, depuis le sélecteur ("créer cette carte") quand
    aucune entrée du référentiel ne correspond — sans quitter l'écran de
    saisie. La photo et les relevés viendront plus tard, depuis la fiche."""
    d = clean_card(p)
    if not d["name"]:
        raise HTTPException(400, "nom manquant")
    cid = nid()
    ik = cards_mod.identity_key(d["name"], d["set_name"], d["card_number"], d["lang"], d["grade"])
    with db() as con:
        con.execute(
            f"INSERT INTO cards(id,{','.join(CARD_FIELDS)},identity_key,created_at) "
            f"VALUES(?,{','.join('?' * len(CARD_FIELDS))},?,?)",
            (cid, *[d[f] for f in CARD_FIELDS], ik, datetime.now().isoformat(timespec="seconds")),
        )
    return _card_picker_entry(d | {"id": cid, "photo_id": None})


def _card_picker_entry(c: dict, counts: dict | None = None) -> dict:
    return {
        "id": c["id"], "name": c["name"], "set_name": c.get("set_name") or "",
        "card_number": c.get("card_number") or "", "lang": c.get("lang") or "",
        "type": c.get("type") or "loose", "grade": c.get("grade") or "",
        "resale_min": c.get("resale_min"), "resale_median": c.get("resale_median"), "resale_max": c.get("resale_max"),
        "buy_max_computed": c.get("buy_max_computed"),
        "resale_target_eur": c.get("resale_target_eur"), "default_resale_platform": c.get("default_resale_platform"),
        **_card_photo_urls(c),
        "counts": counts or {"bought": 0, "in_stock": 0, "sold": 0},
    }


@app.get("/api/cards/picker")
def api_cards_picker():
    """Liste compacte pour le sélecteur (bouton + des commandes/du stock) :
    pas les exemplaires complets de l'écran de fusion, juste de quoi
    chercher, comparer et décider un prix d'achat en un coup d'œil. Chargée
    une fois à l'ouverture, filtrée côté client ensuite (collection perso :
    quelques centaines de cartes au plus, aucune latence perceptible)."""
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM cards WHERE merged_into_id IS NULL ORDER BY name"
        )]
        stock_rows = con.execute(
            "SELECT card_id, status, COUNT(*) AS n FROM stock_items "
            "WHERE card_id IS NOT NULL GROUP BY card_id, status"
        ).fetchall()
    counts_by_card: dict[str, dict] = {}
    for r in stock_rows:
        c = counts_by_card.setdefault(r["card_id"], {"bought": 0, "in_stock": 0, "sold": 0})
        c["bought"] += r["n"]
        if r["status"] == "vendu":
            c["sold"] += r["n"]
        elif r["status"] in stock_mod.ACTIVE_STATUSES:
            c["in_stock"] += r["n"]
    return {"cards": [_card_picker_entry(r, counts_by_card.get(r["id"])) for r in rows]}


# --- migration : simulation puis exécution ---

def _build_migration_inputs():
    with db() as con:
        sheets = [dict(r) for r in con.execute("SELECT * FROM card_sheets")]
        items = [dict(r) for r in con.execute("SELECT * FROM items WHERE card_id IS NULL")]
        lines = [dict(r) for r in con.execute("SELECT * FROM import_order_lines WHERE card_id IS NULL")]
        stocks = [dict(r) for r in con.execute("SELECT * FROM stock_items WHERE card_id IS NULL")]
    candidates = [{"id": s["id"], **_identity_fields_card_sheet(s)} for s in sheets]
    unlinked = (
        [{"table": "items", "id": it["id"], **_identity_fields_items(it)} for it in items]
        + [{"table": "import_order_lines", "id": l["id"], **_identity_fields_order_line(l)} for l in lines]
        + [{"table": "stock_items", "id": st["id"], **_identity_fields_stock(st)} for st in stocks]
    )
    return sheets, candidates, unlinked


@app.get("/api/cards/migration-preview")
def api_cards_migration_preview():
    """Lecture seule : ne touche rien, montre ce que /migration-run ferait."""
    sheets, candidates, unlinked = _build_migration_inputs()
    plan = cards_mod.build_migration_plan(candidates, unlinked)
    already_migrated = sum(1 for s in sheets if s.get("card_id"))
    plan["already_migrated_sheets"] = already_migrated
    return plan


@app.post("/api/cards/migration-run")
def api_cards_migration_run():
    """Rejouable sans dégât : toute ligne déjà pourvue d'un card_id est ignorée."""
    sheets, candidates, unlinked = _build_migration_inputs()
    plan = cards_mod.build_migration_plan(candidates, unlinked)
    now = datetime.now().isoformat(timespec="seconds")
    sheet_to_card: dict[str, str] = {}
    counts = {"cards_created_from_sheets": 0, "cards_created_new": 0, "auto_linked": 0, "proposals": 0}
    cs = get_card_settings()
    items_by_id = {i["id"]: i for i in build_state(snapshot=False)["items"]}

    with db() as con:
        for s in sheets:
            if s.get("card_id"):
                sheet_to_card[s["id"]] = s["card_id"]
                continue
            f = _identity_fields_card_sheet(s)
            cid = nid()
            buy_max = None
            try:
                view = _card_sheet_view(s, items_by_id, cs, None)
                prudent = view["computed"]["scenarios"]["prudent"]
                buy_max = prudent["c_max"] if prudent else None
            except Exception:
                buy_max = None
            # La fiche carte est la source de vérité : si elle a déjà une
            # photo, la carte nouvellement créée en hérite tout de suite —
            # pas de fenêtre où le référentiel serait sans photo alors
            # qu'une fiche liée en avait une.
            photo_id = photo_size = photo_w = photo_h = None
            if s.get("photo_id"):
                photo_id = _copy_sheet_photo_to_card(s["id"], s["photo_id"], cid)
                if photo_id:
                    photo_size, photo_w, photo_h = s.get("photo_size_bytes"), s.get("photo_width"), s.get("photo_height")
            con.execute(
                "INSERT INTO cards(id,name,set_name,card_number,lang,type,grade,identity_key,"
                "profit_target_pct,resale_mode,resale_min,resale_median,resale_max,buy_max_computed,"
                "resale_target_eur,default_resale_platform,photo_id,photo_size_bytes,photo_width,photo_height,"
                "notes,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, f["name"], f["set_name"], f["card_number"], f["lang"], f["type"], f["grade"],
                 cards_mod.identity_key(f["name"], f["set_name"], f["card_number"], f["lang"], f["grade"]),
                 s.get("profit_target_pct"), s.get("resale_mode") or "auto",
                 s.get("resale_min"), s.get("resale_median"), s.get("resale_max"), buy_max,
                 s.get("resale_median"), s.get("resale_platform"),
                 photo_id, photo_size, photo_w, photo_h,
                 s.get("notes") or "", now),
            )
            con.execute("UPDATE card_sheets SET card_id=? WHERE id=?", (cid, s["id"]))
            sheet_to_card[s["id"]] = cid
            counts["cards_created_from_sheets"] += 1

        for link in plan["auto_links"]:
            real_card_id = sheet_to_card.get(link["card_id"], link["card_id"])
            con.execute(f"UPDATE {link['table']} SET card_id=? WHERE id=?", (real_card_id, link["id"]))
            counts["auto_linked"] += 1

        for rec in plan["creations"]:
            cid = nid()
            con.execute(
                "INSERT INTO cards(id,name,set_name,card_number,lang,type,grade,identity_key,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (cid, rec["name"], rec.get("set_name") or "", rec.get("card_number") or "",
                 rec.get("lang") or "", rec.get("type") or "loose", rec.get("grade") or "",
                 cards_mod.identity_key(rec["name"], rec.get("set_name"), rec.get("card_number"),
                                         rec.get("lang"), rec.get("grade")), now),
            )
            con.execute(f"UPDATE {rec['table']} SET card_id=? WHERE id=?", (cid, rec["id"]))
            rec["_new_card_id"] = cid
            counts["cards_created_new"] += 1

        creation_index = {(r["table"], r["id"]): r["_new_card_id"] for r in plan["creations"]}
        for prop in plan["proposals"]:
            new_card_id = creation_index.get((prop["table"], prop["id"]))
            other_card_id = sheet_to_card.get(prop["candidate_card_id"], prop["candidate_card_id"])
            if not new_card_id or new_card_id == other_card_id:
                continue
            con.execute(
                "INSERT INTO card_merge_suggestions(id,card_a_id,card_b_id,score,status,created_at) VALUES(?,?,?,?,?,?)",
                (nid(), new_card_id, other_card_id, prop["score"], "pending", now),
            )
            counts["proposals"] += 1

    return {"ok": True, "counts": counts}


# --- écran de fusion ---

@app.get("/api/cards/merge-suggestions")
def api_list_merge_suggestions():
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM card_merge_suggestions WHERE status='pending' ORDER BY created_at DESC"
        )]
        cards_by_id = {r["id"]: dict(r) for r in con.execute("SELECT * FROM cards")}
    out = []
    for r in rows:
        a, b = cards_by_id.get(r["card_a_id"]), cards_by_id.get(r["card_b_id"])
        if not a or not b:
            continue
        out.append({**r, "card_a": {**a, **_card_photo_urls(a)}, "card_b": {**b, **_card_photo_urls(b)}})
    return {"suggestions": out}


@app.post("/api/cards/merge-suggestions/{sid}/dismiss")
def api_dismiss_merge_suggestion(sid: str):
    with db() as con:
        cur = con.execute("UPDATE card_merge_suggestions SET status='dismissed' WHERE id=? AND status='pending'", (sid,))
        if not cur.rowcount:
            raise HTTPException(404, "proposition introuvable")
    return {"ok": True}


@app.post("/api/cards/merge")
def api_merge_cards(p: dict = Body(...)):
    """Fusionne loser_id dans winner_id : toutes les lignes qui référençaient
    loser basculent sur winner. loser n'est jamais supprimée (tombstone
    merged_into_id) : la fusion reste annulable via /merge/{merge_id}/undo."""
    loser_id, winner_id = p.get("loser_id"), p.get("winner_id")
    if not loser_id or not winner_id or loser_id == winner_id:
        raise HTTPException(400, "loser_id et winner_id requis et différents")
    merge_id = nid()
    now = datetime.now().isoformat(timespec="seconds")
    with db() as con:
        if not con.execute("SELECT 1 FROM cards WHERE id=?", (loser_id,)).fetchone() or \
           not con.execute("SELECT 1 FROM cards WHERE id=?", (winner_id,)).fetchone():
            raise HTTPException(404, "carte introuvable")
        for table in CARD_REF_TABLES:
            rows = con.execute(f"SELECT id, card_id FROM {table} WHERE card_id=?", (loser_id,)).fetchall()
            for r in rows:
                con.execute(f"UPDATE {table} SET card_id=? WHERE id=?", (winner_id, r["id"]))
                con.execute(
                    "INSERT INTO card_merge_log(id,merge_id,loser_card_id,winner_card_id,affected_table,"
                    "affected_id,previous_card_id,at) VALUES(?,?,?,?,?,?,?,?)",
                    (nid(), merge_id, loser_id, winner_id, table, r["id"], r["card_id"], now),
                )
        con.execute("UPDATE cards SET merged_into_id=? WHERE id=?", (winner_id, loser_id))
        con.execute(
            "UPDATE card_merge_suggestions SET status='merged' WHERE status='pending' AND "
            "((card_a_id=? AND card_b_id=?) OR (card_a_id=? AND card_b_id=?))",
            (loser_id, winner_id, winner_id, loser_id),
        )
    return {"ok": True, "merge_id": merge_id}


@app.post("/api/cards/merge/{merge_id}/undo")
def api_undo_merge(merge_id: str):
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM card_merge_log WHERE merge_id=?", (merge_id,))]
        if not rows:
            raise HTTPException(404, "fusion introuvable (déjà annulée ou id inconnu)")
        loser_id, winner_id = rows[0]["loser_card_id"], rows[0]["winner_card_id"]
        for r in rows:
            con.execute(f"UPDATE {r['affected_table']} SET card_id=? WHERE id=?",
                        (r["previous_card_id"], r["affected_id"]))
        con.execute("UPDATE cards SET merged_into_id=NULL WHERE id=?", (loser_id,))
        con.execute("DELETE FROM card_merge_log WHERE merge_id=?", (merge_id,))
        # Remet en attente la proposition correspondante, sinon elle reste
        # marquée "merged" alors que la fusion vient d'être défaite.
        con.execute(
            "UPDATE card_merge_suggestions SET status='pending' WHERE status='merged' AND "
            "((card_a_id=? AND card_b_id=?) OR (card_a_id=? AND card_b_id=?))",
            (loser_id, winner_id, winner_id, loser_id),
        )
    return {"ok": True}



@app.get("/api/cards/{cid}")
def api_get_card(cid: str):
    with db() as con:
        row = con.execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "carte introuvable")
    return _card_view(dict(row))


@app.put("/api/cards/{cid}")
def api_edit_card(cid: str, p: dict = Body(...)):
    d = clean_card(p)
    if not d["name"]:
        raise HTTPException(400, "nom manquant")
    ik = cards_mod.identity_key(d["name"], d["set_name"], d["card_number"], d["lang"], d["grade"])
    with db() as con:
        cur = con.execute(
            f"UPDATE cards SET {','.join(f + '=?' for f in CARD_FIELDS)}, identity_key=? WHERE id=?",
            (*[d[f] for f in CARD_FIELDS], ik, cid),
        )
        if not cur.rowcount:
            raise HTTPException(404, "carte introuvable")
    return {"ok": True}


@app.delete("/api/cards/{cid}")
def api_del_card(cid: str):
    """Refuse, ne cascade jamais : une carte encore référencée doit d'abord
    être détachée (ou ses exemplaires supprimés) explicitement ailleurs."""
    with db() as con:
        for table in ("items", "card_sheets", "import_order_lines", "stock_items"):
            if con.execute(f"SELECT 1 FROM {table} WHERE card_id=?", (cid,)).fetchone():
                raise HTTPException(400, f"carte encore référencée ({table}) : détache-la d'abord")
        cur = con.execute("DELETE FROM cards WHERE id=?", (cid,))
        if not cur.rowcount:
            raise HTTPException(404, "carte introuvable")
    media_mod.delete_item_dir(CARD_MEDIA, cid)
    return {"ok": True}


# --- photo de référence (une seule, propagée à tous les exemplaires liés) ---

@app.post("/api/cards/{cid}/photo")
async def api_add_card_photo(cid: str, file: UploadFile = File(...)):
    with db() as con:
        row = con.execute("SELECT photo_id FROM cards WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "carte introuvable")
        old_photo_id = row["photo_id"]
    raw = await file.read()
    try:
        info = media_mod.save_photo(CARD_MEDIA, cid, raw, (file.content_type or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    with db() as con:
        con.execute(
            "UPDATE cards SET photo_id=?, photo_size_bytes=?, photo_width=?, photo_height=? WHERE id=?",
            (info["id"], info["size_bytes"], info["width"], info["height"], cid),
        )
    if old_photo_id:
        media_mod.delete_photo(CARD_MEDIA, cid, old_photo_id)
    return {"id": info["id"], "url": f"/api/cards/{cid}/photo", "thumb_url": f"/api/cards/{cid}/photo/thumb"}


@app.post("/api/cards/{cid}/photo/import-from-sheet")
def api_import_card_photo_from_sheet(cid: str):
    """Reprend la photo d'une fiche carte déjà liée, pour les cartes migrées
    avant que l'upload direct sur la carte n'existe (la fiche avait une
    photo, jamais recopiée vers le référentiel). Simple copie de fichiers
    déjà traités, pas un nouvel upload."""
    with db() as con:
        card = con.execute("SELECT photo_id FROM cards WHERE id=?", (cid,)).fetchone()
        if not card:
            raise HTTPException(404, "carte introuvable")
        if card["photo_id"]:
            raise HTTPException(400, "cette carte a déjà une photo")
        sheet = con.execute(
            "SELECT id, photo_id, photo_size_bytes, photo_width, photo_height FROM card_sheets "
            "WHERE card_id=? AND photo_id IS NOT NULL LIMIT 1", (cid,)
        ).fetchone()
        if not sheet:
            raise HTTPException(400, "aucune fiche liée n'a de photo à reprendre")
        sheet = dict(sheet)
    new_id = _copy_sheet_photo_to_card(sheet["id"], sheet["photo_id"], cid)
    if not new_id:
        raise HTTPException(400, "fichier de la photo introuvable")
    with db() as con:
        con.execute(
            "UPDATE cards SET photo_id=?, photo_size_bytes=?, photo_width=?, photo_height=? WHERE id=?",
            (new_id, sheet["photo_size_bytes"], sheet["photo_width"], sheet["photo_height"], cid),
        )
    return {"id": new_id, "url": f"/api/cards/{cid}/photo", "thumb_url": f"/api/cards/{cid}/photo/thumb"}


@app.delete("/api/cards/{cid}/photo")
def api_del_card_photo(cid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM cards WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "carte introuvable")
        pid = row["photo_id"]
        con.execute(
            "UPDATE cards SET photo_id=NULL, photo_size_bytes=NULL, photo_width=NULL, photo_height=NULL WHERE id=?",
            (cid,),
        )
    if pid:
        media_mod.delete_photo(CARD_MEDIA, cid, pid)
    return {"ok": True}


@app.get("/api/cards/{cid}/photo")
def api_get_card_photo(cid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM cards WHERE id=?", (cid,)).fetchone()
    pid = row["photo_id"] if row else None
    path = media_mod.photo_path(CARD_MEDIA, cid, pid, thumb=False) if pid else None
    if not path:
        raise HTTPException(404, "photo introuvable")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/cards/{cid}/photo/thumb")
def api_get_card_thumb(cid: str):
    with db() as con:
        row = con.execute("SELECT photo_id FROM cards WHERE id=?", (cid,)).fetchone()
    pid = row["photo_id"] if row else None
    path = media_mod.photo_path(CARD_MEDIA, cid, pid, thumb=True) if pid else None
    if not path:
        raise HTTPException(404, "vignette introuvable")
    return FileResponse(path, media_type="image/webp")


# --------------------------------------------------------------------------- export

def _deals_export_list() -> list[dict]:
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM deals")]
    out = []
    for row in rows:
        d = _deal_row_to_dict(row)
        d["photos"] = [
            {k: v for k, v in p.items() if k not in ("url", "thumb_url", "deal_id")}
            for p in _deal_photos(d["id"])
        ]
        out.append(d)
    return out


def _card_deals_export() -> dict:
    with db() as con:
        sheets = [dict(r) for r in con.execute("SELECT * FROM card_sheets")]
        listings = [dict(r) for r in con.execute("SELECT * FROM card_sheet_listings")]
        orders = [dict(r) for r in con.execute("SELECT * FROM import_orders")]
        lines = [dict(r) for r in con.execute("SELECT * FROM import_order_lines")]
    listings_by_sheet: dict[str, list] = {}
    for l in listings:
        listings_by_sheet.setdefault(l["sheet_id"], []).append(l)
    for s in sheets:
        s["listings"] = listings_by_sheet.get(s["id"], [])
    lines_by_order: dict[str, list] = {}
    for l in lines:
        lines_by_order.setdefault(l["order_id"], []).append(l)
    for o in orders:
        o["lines"] = lines_by_order.get(o["id"], [])
    return {"card_sheets": sheets, "import_orders": orders, "card_deal_settings": get_card_settings()}


def _stock_export() -> dict:
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM stock_items")]
        events = [dict(r) for r in con.execute("SELECT * FROM stock_events")]
    events_by_stock: dict[str, list] = {}
    for e in events:
        events_by_stock.setdefault(e["stock_id"], []).append(e)
    for r in rows:
        r["events"] = events_by_stock.get(r["id"], [])
    return {"stock_items": rows}


def _cards_export() -> dict:
    with db() as con:
        cards = [dict(r) for r in con.execute("SELECT * FROM cards")]
        listings = [dict(r) for r in con.execute("SELECT * FROM card_listings")]
        suggestions = [dict(r) for r in con.execute("SELECT * FROM card_merge_suggestions")]
        log = [dict(r) for r in con.execute("SELECT * FROM card_merge_log")]
    listings_by_card: dict[str, list] = {}
    for l in listings:
        listings_by_card.setdefault(l["card_id"], []).append(l)
    for c in cards:
        c["listings"] = listings_by_card.get(c["id"], [])
    return {"cards": cards, "card_merge_suggestions": suggestions, "card_merge_log": log}


@app.get("/api/export")
def api_export():
    st = build_state(snapshot=False)
    return {
        "items": st["items"], "snapshots": st["snapshots"], "settings": st["settings"],
        "deals": _deals_export_list(), "deal_params": get_deal_params(),
        **_card_deals_export(), **_stock_export(), **_cards_export(),
    }


@app.get("/api/export.zip")
def api_export_zip():
    """Export complet : data.json + tous les fichiers media (items + deals) dans un ZIP."""
    import io, zipfile
    st = build_state(snapshot=False)
    payload = {
        "items": st["items"], "snapshots": st["snapshots"], "settings": st["settings"],
        "deals": _deals_export_list(), "deal_params": get_deal_params(),
        **_card_deals_export(), **_stock_export(), **_cards_export(),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(payload, ensure_ascii=False, indent=2))
        for it in st["items"]:
            for f in media_mod.list_item_files(MEDIA, it["id"]):
                # Chemin relatif dans le ZIP : media/<item_id>/<filename>
                z.write(f, arcname=f"media/{it['id']}/{f.name}")
        for d in payload["deals"]:
            for f in media_mod.list_item_files(DEAL_MEDIA, d["id"]):
                # Namespace séparé pour les deals : deal_media/<deal_id>/<filename>
                z.write(f, arcname=f"deal_media/{d['id']}/{f.name}")
        for cs in payload["card_sheets"]:
            for f in media_mod.list_item_files(CARD_SHEET_MEDIA, cs["id"]):
                # Namespace séparé pour les fiches carte : card_sheet_media/<sheet_id>/<filename>
                z.write(f, arcname=f"card_sheet_media/{cs['id']}/{f.name}")
        for si in payload["stock_items"]:
            for f in media_mod.list_item_files(STOCK_MEDIA, si["id"]):
                # Namespace séparé pour le stock : stock_media/<stock_id>/<filename>
                z.write(f, arcname=f"stock_media/{si['id']}/{f.name}")
        for c in payload["cards"]:
            for f in media_mod.list_item_files(CARD_MEDIA, c["id"]):
                # Namespace séparé pour le référentiel : card_media/<card_id>/<filename>
                z.write(f, arcname=f"card_media/{c['id']}/{f.name}")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="portefeuille.zip"'},
    )


@app.post("/api/import")
async def api_import(file: UploadFile = File(...), replace: bool = True):
    """Accepte l'export de la version fichier unique comme celui du serveur.

    Détecte automatiquement si le fichier est un JSON pur ou un ZIP :
    - ZIP → contient data.json + un dossier media/<item_id>/*.webp
    - JSON → import sans médias (les entrées photos sont ignorées côté fichiers)
    """
    raw = await file.read()

    import io, zipfile

    zip_photos: dict[str, dict[str, bytes]] = {}       # {item_id: {filename: bytes}}
    zip_deal_photos: dict[str, dict[str, bytes]] = {}  # {deal_id: {filename: bytes}}
    zip_card_photos: dict[str, dict[str, bytes]] = {}  # {sheet_id: {filename: bytes}}
    zip_stock_photos: dict[str, dict[str, bytes]] = {}  # {stock_id: {filename: bytes}}
    zip_card_ref_photos: dict[str, dict[str, bytes]] = {}  # {card_id: {filename: bytes}}
    if raw[:4] == b"PK\x03\x04":  # signature ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                try:
                    data_bytes = z.read("data.json")
                except KeyError:
                    raise HTTPException(400, "ZIP sans data.json")
                data: Any = json.loads(data_bytes.decode("utf-8"))
                for name in z.namelist():
                    parts = name.split("/")
                    if len(parts) == 3 and parts[0] == "media" and parts[2]:
                        iid, fname = parts[1], parts[2]
                        zip_photos.setdefault(iid, {})[fname] = z.read(name)
                    elif len(parts) == 3 and parts[0] == "deal_media" and parts[2]:
                        did, fname = parts[1], parts[2]
                        zip_deal_photos.setdefault(did, {})[fname] = z.read(name)
                    elif len(parts) == 3 and parts[0] == "card_sheet_media" and parts[2]:
                        sid, fname = parts[1], parts[2]
                        zip_card_photos.setdefault(sid, {})[fname] = z.read(name)
                    elif len(parts) == 3 and parts[0] == "stock_media" and parts[2]:
                        stid, fname = parts[1], parts[2]
                        zip_stock_photos.setdefault(stid, {})[fname] = z.read(name)
                    elif len(parts) == 3 and parts[0] == "card_media" and parts[2]:
                        crid, fname = parts[1], parts[2]
                        zip_card_ref_photos.setdefault(crid, {})[fname] = z.read(name)
        except zipfile.BadZipFile:
            raise HTTPException(400, "ZIP invalide")
    else:
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(400, "format inattendu (ni JSON ni ZIP)")

    items = data.get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "format inattendu")
    with db() as con:
        if replace:
            con.execute("DELETE FROM comps")
            con.execute("DELETE FROM media")
            con.execute("DELETE FROM purchases")
            con.execute("DELETE FROM items")
            con.execute("DELETE FROM snapshots")
            con.execute("DELETE FROM deal_media")
            con.execute("DELETE FROM deals")
            con.execute("DELETE FROM card_sheet_listings")
            con.execute("DELETE FROM card_sheets")
            con.execute("DELETE FROM import_order_lines")
            con.execute("DELETE FROM import_orders")
            con.execute("DELETE FROM stock_events")
            con.execute("DELETE FROM stock_items")
            con.execute("DELETE FROM card_merge_log")
            con.execute("DELETE FROM card_merge_suggestions")
            con.execute("DELETE FROM card_listings")
            con.execute("DELETE FROM cards")
        # Les cartes du référentiel doivent exister AVANT tout ce qui les
        # référence (card_id REFERENCES cards(id), contrainte FK immédiate) :
        # restaurées en premier, dans cette même transaction.
        for c in data.get("cards") or []:
            crid = str(c.get("id") or nid())
            cd = clean_card(c)
            ik = cards_mod.identity_key(cd["name"], cd["set_name"], cd["card_number"], cd["lang"], cd["grade"])
            photo_id = photo_size = photo_w = photo_h = None
            src_photo_id = c.get("photo_id")
            if src_photo_id:
                files_for_card = zip_card_ref_photos.get(crid, {})
                fname, thumb_name = f"{src_photo_id}.webp", f"{src_photo_id}.thumb.webp"
                if fname in files_for_card:
                    dpath = CARD_MEDIA / crid
                    dpath.mkdir(parents=True, exist_ok=True)
                    (dpath / fname).write_bytes(files_for_card[fname])
                    if thumb_name in files_for_card:
                        (dpath / thumb_name).write_bytes(files_for_card[thumb_name])
                    photo_id = src_photo_id
                    photo_size = c.get("photo_size_bytes")
                    photo_w = c.get("photo_width")
                    photo_h = c.get("photo_height")
            con.execute(
                f"INSERT OR REPLACE INTO cards(id,{','.join(CARD_FIELDS)},identity_key,"
                "photo_id,photo_size_bytes,photo_width,photo_height,merged_into_id,created_at) "
                f"VALUES(?,{','.join('?' * len(CARD_FIELDS))},?,?,?,?,?,?,?)",
                (crid, *[cd[f] for f in CARD_FIELDS], ik, photo_id, photo_size, photo_w, photo_h,
                 c.get("merged_into_id"),
                 str(c.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
            )
            for lst in c.get("listings") or []:
                con.execute(
                    "INSERT OR REPLACE INTO card_listings(id,card_id,platform,url,price,shipping,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (str(lst.get("id") or nid()), crid,
                     lst.get("platform") if lst.get("platform") in card_deals_mod.BUY_PLATFORMS else "ebay",
                     str(lst.get("url", ""))[:500], max(0.0, float(lst.get("price") or 0)),
                     max(0.0, float(lst.get("shipping") or 0)),
                     str(lst.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
                )
        for sug in data.get("card_merge_suggestions") or []:
            con.execute(
                "INSERT OR REPLACE INTO card_merge_suggestions(id,card_a_id,card_b_id,score,status,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (str(sug.get("id") or nid()), sug.get("card_a_id"), sug.get("card_b_id"),
                 float(sug.get("score") or 0), sug.get("status") or "pending",
                 str(sug.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
            )
        for lg in data.get("card_merge_log") or []:
            con.execute(
                "INSERT OR REPLACE INTO card_merge_log(id,merge_id,loser_card_id,winner_card_id,"
                "affected_table,affected_id,previous_card_id,at) VALUES(?,?,?,?,?,?,?,?)",
                (str(lg.get("id") or nid()), lg.get("merge_id"), lg.get("loser_card_id"), lg.get("winner_card_id"),
                 lg.get("affected_table"), lg.get("affected_id"), lg.get("previous_card_id"),
                 str(lg.get("at") or datetime.now().isoformat(timespec="seconds"))),
            )
        for it in items:
            iid = str(it.get("id") or nid())
            d = clean({**it, "set_name": it.get("set_name") or it.get("set", "")})
            con.execute(
                f"INSERT OR REPLACE INTO items(id,{','.join(FIELDS)},card_id,created_at) "
                f"VALUES(?,{','.join('?' * len(FIELDS))},?,?)",
                (iid, *[d[f] for f in FIELDS], it.get("card_id"),
                 datetime.now().isoformat(timespec="seconds")),
            )
            for c in it.get("comps") or []:
                con.execute(
                    "INSERT OR REPLACE INTO comps(id,item_id,price,date,source,note,excluded,sold_count,shipping) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (str(c.get("id") or nid()), iid, float(c.get("price") or 0),
                     str(c.get("date") or date.today().isoformat())[:10],
                     c.get("source") if c.get("source") in SOURCES else "manual",
                     str(c.get("note", ""))[:200], int(bool(c.get("excluded"))),
                     max(1, int(c.get("sold_count") or 1)),
                     max(0.0, float(c.get("shipping") or 0))),
                )
            # Photos : ne restaure les entrées DB que si les fichiers sont là (ZIP).
            # Sinon (import JSON pur) on ignore silencieusement pour ne pas créer
            # des références orphelines vers des fichiers inexistants.
            files_for_item = zip_photos.get(iid, {})
            for ph in it.get("photos") or []:
                fname = ph.get("filename") or ""
                if fname and fname in files_for_item:
                    # Écrit le fichier sur disque avant l'INSERT DB
                    d = MEDIA / iid
                    d.mkdir(parents=True, exist_ok=True)
                    (d / fname).write_bytes(files_for_item[fname])
                    # La vignette peut être présente aussi
                    pid = fname.removesuffix(".webp")
                    thumb_name = f"{pid}.thumb.webp"
                    if thumb_name in files_for_item:
                        (d / thumb_name).write_bytes(files_for_item[thumb_name])
                    con.execute(
                        "INSERT OR REPLACE INTO media(id,item_id,filename,mime,size_bytes,width,height,sort_order,created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (str(ph.get("id") or pid), iid, fname,
                         str(ph.get("mime", "image/webp")),
                         int(ph.get("size_bytes") or len(files_for_item[fname])),
                         ph.get("width"), ph.get("height"),
                         int(ph.get("sort_order") or 0),
                         str(ph.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
                    )
            for pu in it.get("purchases") or []:
                con.execute(
                    "INSERT OR REPLACE INTO purchases(id,item_id,price,qty,date,note) VALUES(?,?,?,?,?,?)",
                    (str(pu.get("id") or nid()), iid, float(pu.get("price") or 0),
                     max(1, int(pu.get("qty") or 1)),
                     str(pu.get("date") or date.today().isoformat())[:10],
                     str(pu.get("note", ""))[:200]),
                )
        for s in data.get("snapshots") or []:
            con.execute(
                "INSERT OR REPLACE INTO snapshots(d,value,invested) VALUES(?,?,?)",
                (str(s.get("d"))[:10], float(s.get("value") or 0), float(s.get("invested") or 0)),
            )
        for dl in data.get("deals") or []:
            did = str(dl.get("id") or nid())
            dd = clean_deal(dl)
            resale_prices = dl.get("resale_prices") or {}
            resale_prices = {k: float(v) for k, v in resale_prices.items()
                              if k in deals_mod.PLATFORMS_SELL and v not in (None, "")}
            con.execute(
                f"INSERT OR REPLACE INTO deals(id,{','.join(DEAL_FIELDS)},resale_prices,created_at) "
                f"VALUES(?,{','.join('?' * len(DEAL_FIELDS))},?,?)",
                (did, *[dd[f] for f in DEAL_FIELDS], json.dumps(resale_prices),
                 str(dl.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
            )
            files_for_deal = zip_deal_photos.get(did, {})
            for ph in dl.get("photos") or []:
                fname = ph.get("filename") or ""
                if fname and fname in files_for_deal:
                    dpath = DEAL_MEDIA / did
                    dpath.mkdir(parents=True, exist_ok=True)
                    (dpath / fname).write_bytes(files_for_deal[fname])
                    pid = fname.removesuffix(".webp")
                    thumb_name = f"{pid}.thumb.webp"
                    if thumb_name in files_for_deal:
                        (dpath / thumb_name).write_bytes(files_for_deal[thumb_name])
                    con.execute(
                        "INSERT OR REPLACE INTO deal_media(id,deal_id,filename,mime,size_bytes,width,height,sort_order,created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (str(ph.get("id") or pid), did, fname,
                         str(ph.get("mime", "image/webp")),
                         int(ph.get("size_bytes") or len(files_for_deal[fname])),
                         ph.get("width"), ph.get("height"),
                         int(ph.get("sort_order") or 0),
                         str(ph.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
                    )
        for cs in data.get("card_sheets") or []:
            sid = str(cs.get("id") or nid())
            csd = clean_card_sheet(cs)
            # Photo facultative : ne restaure la référence en base QUE si le
            # fichier est réellement présent dans le ZIP (comme pour les items).
            # Import JSON pur, ou ZIP incomplet/édité à la main -> photo_id
            # reste NULL, jamais de référence pointant vers un fichier absent.
            photo_id = photo_size = photo_w = photo_h = None
            src_photo_id = cs.get("photo_id")
            if src_photo_id:
                files_for_sheet = zip_card_photos.get(sid, {})
                fname, thumb_name = f"{src_photo_id}.webp", f"{src_photo_id}.thumb.webp"
                if fname in files_for_sheet:
                    d = CARD_SHEET_MEDIA / sid
                    d.mkdir(parents=True, exist_ok=True)
                    (d / fname).write_bytes(files_for_sheet[fname])
                    if thumb_name in files_for_sheet:
                        (d / thumb_name).write_bytes(files_for_sheet[thumb_name])
                    photo_id = src_photo_id
                    photo_size = cs.get("photo_size_bytes")
                    photo_w = cs.get("photo_width")
                    photo_h = cs.get("photo_height")
            con.execute(
                f"INSERT OR REPLACE INTO card_sheets(id,{','.join(CARD_SHEET_FIELDS)},"
                "photo_id,photo_size_bytes,photo_width,photo_height,card_id,card_number,created_at) "
                f"VALUES(?,{','.join('?' * len(CARD_SHEET_FIELDS))},?,?,?,?,?,?,?)",
                (sid, *[csd[f] for f in CARD_SHEET_FIELDS],
                 photo_id, photo_size, photo_w, photo_h, cs.get("card_id"), str(cs.get("card_number", ""))[:40],
                 str(cs.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
            )
            for lst in cs.get("listings") or []:
                lsd = clean_card_listing(lst)
                con.execute(
                    "INSERT OR REPLACE INTO card_sheet_listings(id,sheet_id,platform,url,price,shipping,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (str(lst.get("id") or nid()), sid, lsd["platform"], lsd["url"], lsd["price"], lsd["shipping"],
                     str(lst.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
                )
        for io_ in data.get("import_orders") or []:
            oid = str(io_.get("id") or nid())
            iod = clean_import_order(io_)
            con.execute(
                f"INSERT OR REPLACE INTO import_orders(id,{','.join(IMPORT_ORDER_FIELDS)},"
                "status,fx_rate,fx_rate_at,received_duty_eur,received_vat_eur,received_carrier_fee_eur,"
                "received_debit_eur,received_intl_shipping_eur,received_total_eur,created_at) "
                f"VALUES(?,{','.join('?' * len(IMPORT_ORDER_FIELDS))},?,?,?,?,?,?,?,?,?,?)",
                (oid, *[iod[f] for f in IMPORT_ORDER_FIELDS],
                 io_.get("status") if io_.get("status") in ("brouillon", "commandee", "recue") else "brouillon",
                 io_.get("fx_rate"), io_.get("fx_rate_at"),
                 io_.get("received_duty_eur"), io_.get("received_vat_eur"), io_.get("received_carrier_fee_eur"),
                 io_.get("received_debit_eur"), io_.get("received_intl_shipping_eur"), io_.get("received_total_eur"),
                 str(io_.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
            )
            for i, ln in enumerate(io_.get("lines") or []):
                lnd = clean_order_line(ln)
                con.execute(
                    "INSERT OR REPLACE INTO import_order_lines(id,order_id,item_id,name,type,qty,"
                    "unit_currency,unit_price_jpy,unit_price_eur,resale_target_eur,resale_platform,sort_order,"
                    "card_id,resale_target_overridden) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(ln.get("id") or nid()), oid, lnd["item_id"], lnd["name"], lnd["type"], lnd["qty"],
                     lnd["unit_currency"], lnd["unit_price_jpy"], lnd["unit_price_eur"],
                     lnd["resale_target_eur"], lnd["resale_platform"],
                     int(ln.get("sort_order") if ln.get("sort_order") is not None else i),
                     ln.get("card_id"), int(bool(ln.get("resale_target_overridden")))),
                )
        for si in data.get("stock_items") or []:
            stid = str(si.get("id") or nid())
            sd = clean_stock_item(si)
            sd["card_id"] = si.get("card_id")
            sd["target_overridden"] = int(bool(si.get("target_overridden")))
            photo_id = photo_size = photo_w = photo_h = None
            src_photo_id = si.get("photo_id")
            if src_photo_id:
                files_for_stock = zip_stock_photos.get(stid, {})
                fname, thumb_name = f"{src_photo_id}.webp", f"{src_photo_id}.thumb.webp"
                if fname in files_for_stock:
                    d = STOCK_MEDIA / stid
                    d.mkdir(parents=True, exist_ok=True)
                    (d / fname).write_bytes(files_for_stock[fname])
                    if thumb_name in files_for_stock:
                        (d / thumb_name).write_bytes(files_for_stock[thumb_name])
                    photo_id = src_photo_id
                    photo_size = si.get("photo_size_bytes")
                    photo_w = si.get("photo_width")
                    photo_h = si.get("photo_height")
            con.execute(
                f"INSERT OR REPLACE INTO stock_items(id,{','.join(STOCK_FIELDS)},"
                "photo_id,photo_size_bytes,photo_width,photo_height,status,"
                "sale_price,sale_platform,sale_net,sale_net_manual,created_at) "
                f"VALUES(?,{','.join('?' * len(STOCK_FIELDS))},?,?,?,?,?,?,?,?,?,?)",
                (stid, *[sd[f] for f in STOCK_FIELDS],
                 photo_id, photo_size, photo_w, photo_h,
                 si.get("status") if si.get("status") in stock_mod.STATUSES else "achete",
                 si.get("sale_price"), si.get("sale_platform"),
                 si.get("sale_net"), int(bool(si.get("sale_net_manual"))),
                 str(si.get("created_at") or datetime.now().isoformat(timespec="seconds"))),
            )
            for ev in si.get("events") or []:
                con.execute(
                    "INSERT OR REPLACE INTO stock_events(id,stock_id,from_status,to_status,at,note) "
                    "VALUES(?,?,?,?,?,?)",
                    (str(ev.get("id") or nid()), stid, ev.get("from_status"), ev.get("to_status"),
                     str(ev.get("at") or datetime.now().isoformat(timespec="seconds")), str(ev.get("note", ""))[:500]),
                )
    if isinstance(data.get("settings"), dict):
        api_settings(data["settings"])
    if isinstance(data.get("deal_params"), dict):
        put_deal_params(data["deal_params"])
    if isinstance(data.get("card_deal_settings"), dict):
        put_card_settings(data["card_deal_settings"])
    return {"ok": True, "items": len(items), "deals": len(data.get("deals") or []),
            "card_sheets": len(data.get("card_sheets") or []),
            "import_orders": len(data.get("import_orders") or []),
            "stock_items": len(data.get("stock_items") or []),
            "cards": len(data.get("cards") or [])}


@app.get("/api/ping")
def api_ping():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static"), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
