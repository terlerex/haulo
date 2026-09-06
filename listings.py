"""
Générateur d'annonces (titre + description) pour la revente sur Vinted/eBay.

Moteur de gabarits à variables, déterministe — pas d'IA générative, pas
d'invention de données. Toute valeur affichée vient d'un champ que
l'utilisateur a rempli (référentiel de cartes ou exemplaire en stock).

Module pur : pas d'accès DB. Reçoit un dict de valeurs déjà résolues
(`ctx`) et les réglages, renvoie le texte prêt à copier.
"""

from __future__ import annotations

import re

# --- Variables disponibles (affichées à l'utilisateur dans les réglages) ---
TITLE_VARS = ["nom_fr", "nom_alt", "grade", "type_carte", "numero", "set", "langue"]
DESC_VARS = ["nom_fr", "nom_alt", "set", "numero", "langue", "grade",
             "cert", "organisme", "annee_gradation", "delai_expedition"]

_GRADE_ORG_PREFIX_RE = re.compile(r"^\s*(PSA|BGS|CGC|SGC|ACE|AGS)\s*", re.IGNORECASE)


def extract_grade_number(raw_grade: str) -> str:
    """Le champ `grade` de cette app stocke historiquement la note ENTIÈRE,
    organisme inclus ("PSA 10") — mais {organisme} est déjà une variable
    séparée du générateur, et le gabarit de titre préfixe lui-même "PSA"
    avant {grade}. Sans ce nettoyage, un titre afficherait "PSA PSA 10".
    Retire un préfixe d'organisme connu s'il y en a un ; sinon renvoie la
    valeur telle quelle (ex. une note textuelle comme "Gem Mint")."""
    if not raw_grade:
        return ""
    return _GRADE_ORG_PREFIX_RE.sub("", raw_grade).strip()

DEFAULT_TITLE_TEMPLATE = "Carte Pokémon PSA {grade} {nom_fr} {type_carte} {numero} {set} {langue}"

DEFAULT_DESCRIPTION_TEMPLATES = {
    "detaille": (
        "{nom_fr} {nom_alt} — PSA {grade}\n"
        "{set} · {numero} · Version {langue}\n"
        "\n"
        "• Certification {organisme}, note {grade}\n"
        "• N° {cert} — vérifiable sur psacard.com avant achat\n"
        "• Photos de l'exemplaire exact que vous recevrez\n"
        "\n"
        "Expédition {delai_expedition}. Boîtier en pochette, papier bulle, doubles protections. "
        "Une question, une photo en plus ? Écrivez-moi. D'autres cartes gradées dans mon dressing. "
        "Réductions sur les lots.\n"
        "\n"
        "Pokémon, PSA {grade}, {nom_fr}, {set}, {numero}, carte gradée, slab, TCG, collection"
    ),
    "court": (
        "{nom_fr} {nom_alt} — PSA {grade}\n"
        "{set} · {numero} · Version {langue}\n"
        "\n"
        "Certifiée {organisme}, note {grade}.\n"
        "N° {cert} — vérifiable sur psacard.com.\n"
        "\n"
        "Expédition {delai_expedition}. Question ? Écrivez-moi — autres cartes gradées dans mon dressing.\n"
        "\n"
        "Pokémon, PSA {grade}, {nom_fr}, {set}, {numero}"
    ),
    "chaleureux": (
        "{nom_fr} {nom_alt} en PSA {grade}\n"
        "\n"
        "Un bel article à ajouter à votre vitrine : {set}, {numero}, version {langue}.\n"
        "\n"
        "Certifiée {organisme}, gradée en {annee_gradation}.\n"
        "Numéro {cert} en main — vérifiable sur psacard.com à tout moment.\n"
        "\n"
        "Expédition {delai_expedition}, boîtier calé avec soin (pochette, papier bulle, doubles protections).\n"
        "\n"
        "Des questions sur cet article ou un autre ? Je réponds toujours. D'autres pièces à découvrir dans mon dressing.\n"
        "\n"
        "Pokémon, PSA {grade}, {nom_fr}, {set}, {numero}"
    ),
}

DESCRIPTION_STYLES = ["detaille", "court", "chaleureux"]
STYLE_LABELS = {"detaille": "Détaillé", "court": "Court", "chaleureux": "Chaleureux"}
PLATFORMS = ["vinted", "ebay"]
PLATFORM_LABELS = {"vinted": "Vinted", "ebay": "eBay"}

DEFAULT_LISTING_SETTINGS = {
    "title_template": DEFAULT_TITLE_TEMPLATE,
    "description_templates": dict(DEFAULT_DESCRIPTION_TEMPLATES),
    "platforms": {"vinted": {"title_limit": 75}, "ebay": {"title_limit": 80}},
    "default_platform": "vinted",
    "default_style": "detaille",
    "emojis_enabled": True,
    "delai_expedition": "sous 2 jours ouvrés",
}


def merge_listing_settings(stored: dict | None) -> dict:
    """Fusionne avec les valeurs par défaut — un réglage jamais modifié reste
    au défaut même après l'ajout d'un nouveau champ (additif, comme le reste
    de l'app)."""
    s = {**DEFAULT_LISTING_SETTINGS, **(stored or {})}
    s["description_templates"] = {**DEFAULT_DESCRIPTION_TEMPLATES, **(stored or {}).get("description_templates", {})}
    s["platforms"] = {
        p: {**DEFAULT_LISTING_SETTINGS["platforms"][p], **(stored or {}).get("platforms", {}).get(p, {})}
        for p in PLATFORMS
    }
    return s


# --------------------------------------------------------- détection d'URL

_URL_RE = re.compile(r"(https?://|www\.|\[[^\]]*\]\([^)]*\))", re.IGNORECASE)


def contains_url(text: str) -> bool:
    """Un lien externe (schéma http(s), www., ou syntaxe de lien) — jamais
    une simple mention de nom de domaine en texte brut comme "psacard.com",
    qui n'est cliquable nulle part sur ces plateformes."""
    return bool(_URL_RE.search(text or ""))


# ------------------------------------------------------------- rendu texte

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "️"
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Retire les émojis puis nettoie les espaces qu'ils laissent — un seul
    gabarit à éditer, le réglage ne fait qu'un filtrage à l'affichage."""
    out = _EMOJI_RE.sub("", text)
    out = re.sub(r"[ \t]+", " ", out)
    out = "\n".join(line.strip() for line in out.split("\n"))
    return out


def render_title(template: str, ctx: dict) -> str:
    """Remplace chaque variable, puis nettoie les espaces multiples que
    laisserait une variable vide (pas de "trou" au milieu du titre)."""
    text = template
    for key, value in ctx.items():
        text = text.replace("{" + key + "}", str(value) if value else "")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


_LINE_VAR_RE = re.compile(r"\{(\w+)\}")


# Variables décoratives : accolées à une autre (nom_alt à nom_fr), jamais la
# raison d'être de la ligne. Vides, elles s'effacent proprement (comme le
# titre) SANS faire tomber toute la ligne — seul {cert}, {organisme}, etc.
# (les variables "de fond" d'une ligne) déclenchent sa suppression complète.
_SOFT_VARS = {"nom_alt"}


def render_description(template: str, ctx: dict) -> str:
    """Rend le gabarit ligne par ligne : une ligne qui contient au moins une
    variable "de fond" (hors variables décoratives, cf. _SOFT_VARS) est
    conservée seulement si TOUTES ces variables ont une valeur non vide —
    sinon elle disparaît intégralement (jamais un trou, jamais un
    {placeholder} visible). Une ligne sans variable, ou dont les seules
    variables sont décoratives, est toujours conservée (la décorative vide
    s'efface simplement, espaces excédentaires nettoyés). Les lignes vides
    consécutives issues d'une ligne supprimée sont ensuite réduites à une
    seule."""
    out_lines = []
    for line in template.split("\n"):
        vars_in_line = _LINE_VAR_RE.findall(line)
        required_vars = [v for v in vars_in_line if v not in _SOFT_VARS]
        if required_vars and any(not ctx.get(v) for v in required_vars):
            continue
        rendered = line
        for key, value in ctx.items():
            rendered = rendered.replace("{" + key + "}", str(value) if value else "")
        rendered = re.sub(r"[ \t]{2,}", " ", rendered).strip()
        out_lines.append(rendered)
    # Réduit les doubles sauts de ligne créés par une ligne supprimée,
    # sans jamais coller deux paragraphes qui doivent rester séparés.
    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def build_listing(ctx: dict, settings: dict, platform: str, style: str) -> dict:
    """Construit titre + description. `ctx` doit contenir toutes les clés de
    TITLE_VARS/DESC_VARS (chaîne vide si inconnue) — jamais None, pour que
    les comparaisons `not ctx.get(v)` traitent uniformément "vide" et
    "absent". Bloque (blocked=True) si le gabarit contient une URL."""
    settings = merge_listing_settings(settings)
    platform = platform if platform in PLATFORMS else settings["default_platform"]
    style = style if style in DESCRIPTION_STYLES else settings["default_style"]
    title_tpl = settings["title_template"]
    desc_tpl = settings["description_templates"].get(style, DEFAULT_DESCRIPTION_TEMPLATES[style])

    if contains_url(title_tpl) or contains_url(desc_tpl):
        return {
            "blocked": True,
            "block_reason": "Le gabarit contient un lien (http/https/www.) — interdit sur Vinted et eBay, "
                             "ça expose l'annonce à un retrait pour vente hors plateforme. "
                             "Corrige le gabarit dans les réglages avant de régénérer.",
        }

    # delai_expedition est un réglage global (l'utilisateur le fixe une fois),
    # pas une donnée de carte — injecté ici plutôt que laissé à la charge de
    # chaque appelant, qui l'oublierait sans quoi (ligne d'expédition qui
    # disparaît silencieusement, cf. la règle "variable vide -> ligne retirée").
    full_ctx = {**{k: "" for k in set(TITLE_VARS) | set(DESC_VARS)},
                "delai_expedition": settings.get("delai_expedition", ""), **ctx}
    title = render_title(title_tpl, full_ctx)
    description = render_description(desc_tpl, full_ctx)
    if not settings["emojis_enabled"]:
        title = strip_emojis(title)
        description = strip_emojis(description)

    limit = settings["platforms"].get(platform, {}).get("title_limit", 80)
    warnings = []
    if not full_ctx.get("cert"):
        warnings.append("Numéro de certification manquant — c'est ce qui rassure le plus l'acheteur, pense à le renseigner.")
    if len(title) > limit:
        warnings.append(f"Titre trop long pour {PLATFORM_LABELS.get(platform, platform)} : "
                         f"{len(title)}/{limit} caractères.")

    return {
        "blocked": False,
        "title": title, "description": description,
        "platform": platform, "style": style,
        "title_length": len(title), "title_limit": limit,
        "warnings": warnings,
    }
