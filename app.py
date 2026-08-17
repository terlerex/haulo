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

BASE = Path(__file__).parent
DB = Path(os.environ.get("DB_PATH") or (BASE / "portfolio.db"))
PASSWORD = os.environ.get("PORTFOLIO_PASSWORD", "").strip()
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "90"))
COOKIE = "pkmn_session"

MEDIA = media_mod.media_dir(DB)  # <dossier DB>/media, jamais /data en dur
DEAL_MEDIA = MEDIA / "_deals"     # sous-namespace dédié pour ne pas collisionner avec les item_id

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
}
# Sources qui prouvent une transaction réelle → alimentent le volume de ventes.
# vinted_sold en fait partie ; vinted_listing NON (annonce n'est pas une vente).
SALE_SOURCES = {"ebay", "cm_sold", "gcc", "vinted_sold"}
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
            """
        )
        migrate(con)


def migrate(con: sqlite3.Connection) -> None:
    """Ajoute les colonnes des versions suivantes sans toucher aux données."""
    add = {
        "items": {
            "status": "TEXT NOT NULL DEFAULT 'owned'",   # owned = possédé, watch = en veille
            "target_price": "REAL NOT NULL DEFAULT 0",   # prix d'achat visé sur un item en veille
        },
        "comps": {
            "sold_count": "INTEGER NOT NULL DEFAULT 1",  # nb de ventes que ce relevé représente
            # Port séparé du prix article. Règle stricte : l'estimation de valeur
            # se calcule sur `price` seul (mélanger port inclus / exclu fausserait
            # la moyenne). Le coût total = price + shipping est calculé côté build_state.
            "shipping": "REAL NOT NULL DEFAULT 0",
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
    for it in items:
        it["comps"] = by_item.get(it["id"], [])
        it["photos"] = photos_by_item.get(it["id"], [])
    return items


def build_state(snapshot: bool = True) -> dict:
    s = get_settings()
    items = load_items()
    for it in items:
        it["est"] = estimate(it, s)
        it["stats"] = analyse(it)
        it["value"] = (it["est"]["value"] or 0) * it["qty"]
        it["cost"] = it["buy_price"] * it["qty"]
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


@app.get("/api/export")
def api_export():
    st = build_state(snapshot=False)
    return {
        "items": st["items"], "snapshots": st["snapshots"], "settings": st["settings"],
        "deals": _deals_export_list(), "deal_params": get_deal_params(),
    }


@app.get("/api/export.zip")
def api_export_zip():
    """Export complet : data.json + tous les fichiers media (items + deals) dans un ZIP."""
    import io, zipfile
    st = build_state(snapshot=False)
    payload = {
        "items": st["items"], "snapshots": st["snapshots"], "settings": st["settings"],
        "deals": _deals_export_list(), "deal_params": get_deal_params(),
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
            con.execute("DELETE FROM items")
            con.execute("DELETE FROM snapshots")
            con.execute("DELETE FROM deal_media")
            con.execute("DELETE FROM deals")
        for it in items:
            iid = str(it.get("id") or nid())
            d = clean({**it, "set_name": it.get("set_name") or it.get("set", "")})
            con.execute(
                f"INSERT OR REPLACE INTO items(id,{','.join(FIELDS)},created_at) "
                f"VALUES(?,{','.join('?' * len(FIELDS))},?)",
                (iid, *[d[f] for f in FIELDS], datetime.now().isoformat(timespec="seconds")),
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
    if isinstance(data.get("settings"), dict):
        api_settings(data["settings"])
    if isinstance(data.get("deal_params"), dict):
        put_deal_params(data["deal_params"])
    return {"ok": True, "items": len(items), "deals": len(data.get("deals") or [])}


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
