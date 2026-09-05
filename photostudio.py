"""
Studio photo : détourage déterministe (OpenCV classique, pas de segmentation
par modèle) d'une carte ou d'un slab PSA, puis composition sur un fond
(aplat uni / palette dérivée / continuité floutée) sur un canevas carré.

Aucune reconnaissance de contenu : tout dérive des pixels de la photo elle-
même (contours, couleurs dominantes). Module pur — pas d'accès DB, pas de
lecture/écriture disque en dehors des fonctions explicitement nommées ainsi.
Les images circulent en RGBA (numpy uint8, H×W×4) entre les fonctions ; la
conversion depuis/vers BGR d'OpenCV se fait uniquement aux frontières
(décodage/encodage).
"""

from __future__ import annotations

import io

import numpy as np
import cv2

# --- Constantes métier ---
CARD_ASPECT = 63 / 88          # carte nue, largeur/hauteur (~0.716)
SLAB_ASPECT = 0.62             # boîtier PSA, approximatif (varie selon le modèle de slab)
ASPECT_TOLERANCE = 0.22        # tolérance relative large : une carte de travers vue en
                                # perspective peut sembler bien plus large ou étroite
WORK_MAX_DIM = 1500            # image de travail pour la détection (mémoire bornée)
WARP_LONG_SIDE = 1800          # résolution du redressement : assez grande pour le label
                                # PSA (jamais un second rééchantillonnage destructeur après),
                                # bornée pour ne pas exploser la mémoire sur une grosse photo
CANVAS_SIZE = 1600
CONFIDENCE_REVIEW_THRESHOLD = 0.55   # sous ce seuil : rattrapage manuel poussé en tête de file
CONTRAST_MIN_DELTA = 0.25            # écart de luminance mini fond/sujet (palette, continuité)

BG_COLORS = {"noir": (10, 10, 10), "blanc": (245, 245, 245), "gris": (120, 120, 120)}


# ------------------------------------------------------------- utilitaires

def _resize_max(img: np.ndarray, max_dim: int) -> tuple[np.ndarray, float]:
    """Redimensionne pour que le plus grand côté fasse au plus max_dim.
    Renvoie (image redimensionnée, facteur d'échelle appliqué)."""
    h, w = img.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale >= 1.0:
        return img, 1.0
    return cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA), scale


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Ordonne 4 points en [haut-gauche, haut-droit, bas-droit, bas-gauche],
    peu importe l'ordre d'entrée — indispensable avant getPerspectiveTransform."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    return np.array([
        pts[np.argmin(s)],   # haut-gauche : x+y minimal
        pts[np.argmin(d)],   # haut-droit : x-y minimal
        pts[np.argmax(s)],   # bas-droit : x+y maximal
        pts[np.argmax(d)],   # bas-gauche : x-y maximal
    ], dtype=np.float32)


def _quad_aspect(quad: np.ndarray) -> float:
    """Rapport largeur/hauteur d'un quadrilatère ordonné, moyenné sur les
    deux paires de côtés opposés (plus robuste qu'un seul côté sur une
    photo légèrement en perspective)."""
    tl, tr, br, bl = quad
    w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    h = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    return w / h if h > 1e-6 else 0.0


def _rectangularity(quad: np.ndarray) -> float:
    """1.0 si les 4 angles sont parfaitement droits, décroît sinon. Un
    quadrilatère très en biais (pas juste une carte tournée, mais un contour
    parasite) est ainsi pénalisé même si son aspect ratio tombe juste."""
    angles = []
    for i in range(4):
        p0, p1, p2 = quad[i - 1], quad[i], quad[(i + 1) % 4]
        v1, v2 = p0 - p1, p2 - p1
        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6)
        angles.append(abs(90 - np.degrees(np.arccos(np.clip(cos_a, -1, 1)))))
    return max(0.0, 1.0 - (sum(angles) / 4) / 45)


def _score_candidate(quad: np.ndarray, img_area: float, expected_aspect: float) -> float:
    area = cv2.contourArea(quad.astype(np.float32))
    area_ratio = area / img_area if img_area else 0.0
    if not (0.08 <= area_ratio <= 0.97):
        return 0.0
    aspect = _quad_aspect(quad)
    aspect_alt = 1 / aspect if aspect > 1e-6 else 0.0  # la carte peut être détectée dans l'autre sens
    aspect_err = min(abs(aspect - expected_aspect), abs(aspect_alt - expected_aspect)) / expected_aspect
    aspect_score = max(0.0, 1.0 - aspect_err / ASPECT_TOLERANCE)
    rect_score = _rectangularity(quad)
    area_score = min(1.0, area_ratio / 0.5)  # une carte bien cadrée occupe une bonne partie du cadre
    return float(round(0.5 * aspect_score + 0.3 * rect_score + 0.2 * area_score, 4))


def _candidates_from_mask(mask: np.ndarray) -> list[np.ndarray]:
    """Cherche des quadrilatères plausibles dans un masque binaire (peu
    importe comment il a été obtenu : Canny, seuillage adaptatif, reflets)."""
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(cnt, True)
        if peri < 40:
            continue
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) == 4:
            out.append(_order_corners(approx))
        else:
            # Pas un quadrilatère net (coins arrondis, contour bruité) :
            # le rectangle englobant tourné reste une approximation utile,
            # que l'éditeur manuel pourra affiner si le score est faible.
            rect = cv2.minAreaRect(cnt)
            out.append(_order_corners(cv2.boxPoints(rect)))
    return out


def _method_canny(gray: np.ndarray) -> list[np.ndarray]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    return _candidates_from_mask(edges)


def _method_adaptive(gray: np.ndarray) -> list[np.ndarray]:
    """Fond sombre / faible contraste : un seuil global (Canny) confond le
    sujet et le fond. Le seuillage adaptatif compare chaque pixel à son
    voisinage plutôt qu'à un seuil global, ce qui sépare quand même un
    boîtier sombre d'un fond sombre s'il y a la moindre texture locale."""
    th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 51, -5)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return _candidates_from_mask(th)


def _method_specular(bgr: np.ndarray) -> list[np.ndarray]:
    """Plan de travail noir/réfléchissant : le plastique du boîtier renvoie
    des reflets caractéristiques (zones très claires, peu saturées) que le
    fond sombre ne produit pas. On les isole puis on referme le masque pour
    approximer le contour du boîtier plutôt que celui, illisible, du fond."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    thresh_val = np.percentile(v, 92)
    mask = (v >= max(thresh_val, 140)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    return _candidates_from_mask(mask)


def _intersect(p1: np.ndarray, d1: np.ndarray, p2: np.ndarray, d2: np.ndarray) -> np.ndarray | None:
    """Intersection de deux droites (point + direction). None si parallèles."""
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-6:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / denom
    return p1 + t * d1


def _refine_quad(gray: np.ndarray, quad: np.ndarray, search_range: int = 70, samples: int = 24) -> tuple[np.ndarray, float]:
    """Un quadrilatère issu d'approxPolyDP/minAreaRect peut être à quelques
    % du vrai bord (dilatation morphologique, epsilon d'approximation) —
    invisible sur le score mais visible en liseré de fond après redressement.
    Affine chaque côté en cherchant, perpendiculairement, le plus fort
    gradient local le long du côté, puis ajuste une droite dessus ; les 4
    droites sont intersectées pour obtenir des coins nets. Retombe sur le
    coin d'origine si un côté n'offre pas assez de points fiables (fond trop
    uniforme, contraste insuffisant, ou — cas du label PSA — un second bord
    franc parallèle tout proche qui brouille l'ajustement).

    Renvoie (quad_affiné, fit_ratio) — fit_ratio = fraction des 4 coins
    effectivement recalculés, à faire retomber la confiance quand un ou
    plusieurs bords n'ont pas pu être affinés plutôt que de rester aveugle
    à un coin resté approximatif malgré un score par ailleurs correct."""
    h, w = gray.shape
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)

    lines: list[tuple[np.ndarray, np.ndarray] | None] = []
    for i in range(4):
        p0, p1 = quad[i], quad[(i + 1) % 4]
        edge_vec = p1 - p0
        edge_len = float(np.linalg.norm(edge_vec))
        if edge_len < 10:
            lines.append(None)
            continue
        edge_dir = edge_vec / edge_len
        normal = np.array([-edge_dir[1], edge_dir[0]])
        pts = []
        for t in np.linspace(0.15, 0.85, samples):
            base = p0 + edge_vec * t
            best_s, best_val = 0, -1.0
            for s in range(-search_range, search_range + 1):
                x, y = base + normal * s
                xi, yi = int(round(x)), int(round(y))
                if 0 <= xi < w and 0 <= yi < h and mag[yi, xi] > best_val:
                    best_val, best_s = mag[yi, xi], s
            if best_val > 12:
                pts.append(base + normal * best_s)
        if len(pts) < 6:
            lines.append(None)
            continue
        vx, vy, x0, y0 = cv2.fitLine(np.array(pts, dtype=np.float32), cv2.DIST_L2, 0, 0.01, 0.01).flatten()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))

    refined = quad.copy()
    n_refined = 0
    for i in range(4):
        line_a, line_b = lines[i - 1], lines[i]  # côté entrant / sortant du coin i
        if line_a is not None and line_b is not None:
            pt = _intersect(line_a[0], line_a[1], line_b[0], line_b[1])
            if pt is not None and np.linalg.norm(pt - quad[i]) < search_range * 2.5:
                refined[i] = pt  # ignore une intersection aberrante (quasi-parallèles)
                n_refined += 1
    return refined, n_refined / 4


def detect_quad(bgr: np.ndarray, kind: str) -> dict:
    """Détecte le quadrilatère le plus plausible (carte ou boîtier slab).

    Renvoie {quad: 4x2 float32 en coordonnées de `bgr` (résolution native,
    pas celle du travail interne), confidence: float 0..1, method: str}.
    N'échoue jamais : renvoie le meilleur candidat trouvé (score bas inclus)
    plutôt qu'une exception — c'est à l'appelant de décider, via le seuil de
    confiance, d'envoyer la photo en rattrapage manuel."""
    expected_aspect = SLAB_ASPECT if kind == "slab" else CARD_ASPECT
    work, scale = _resize_max(bgr, WORK_MAX_DIM)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    img_area = work.shape[0] * work.shape[1]

    best_quad, best_score, best_method = None, -1.0, "none"
    for method_name, candidates in (
        ("canny", _method_canny(gray)),
        ("adaptive", _method_adaptive(gray)),
        ("specular", _method_specular(work)),
    ):
        for quad in candidates:
            score = _score_candidate(quad, img_area, expected_aspect)
            if score > best_score:
                best_quad, best_score, best_method = quad, score, method_name

    if best_quad is None:
        # Rien du tout : un rectangle centré à 80% du cadre, point de départ
        # neutre pour l'éditeur manuel plutôt qu'un échec sec.
        h, w = work.shape[:2]
        mx, my = w * 0.1, h * 0.1
        best_quad = np.array([[mx, my], [w - mx, my], [w - mx, h - my], [mx, h - my]], dtype=np.float32)
        best_score, best_method = 0.0, "fallback"
    else:
        # Score correct mais coins parfois à quelques % du vrai bord : sans
        # ce raffinement, un liseré de fond reste visible après redressement
        # même sur une détection jugée fiable.
        best_quad, fit_ratio = _refine_quad(gray, best_quad)
        best_score = _score_candidate(best_quad, img_area, expected_aspect)
        # Un coin resté approximatif (bord non affiné) ne se voit pas
        # toujours dans le score géométrique (aspect/rectangularité moyennés
        # sur les 4 côtés) mais reste visible à l'image — pénalise la
        # confiance en proportion plutôt que de rester aveugle à ce risque.
        best_score *= 0.5 + 0.5 * fit_ratio

    return {"quad": (best_quad / scale).tolist(), "confidence": float(max(0.0, best_score)), "method": best_method}


# --------------------------------------------------------------- redressement

def warp_subject(bgr: np.ndarray, quad: list[list[float]], kind: str) -> np.ndarray:
    """Redresse la zone `quad` de l'image PLEINE RÉSOLUTION vers un
    rectangle RGBA de ratio exact (carte ou slab), bords légèrement adoucis.

    Toujours appelé sur l'image d'origine (pas la copie de travail réduite)
    pour que le futur recadrage du label PSA n'ait jamais besoin d'agrandir
    un rendu déjà réduit."""
    aspect = SLAB_ASPECT if kind == "slab" else CARD_ASPECT
    quad_arr = _order_corners(np.array(quad, dtype=np.float32))
    target_w = WARP_LONG_SIDE if aspect >= 1 else int(WARP_LONG_SIDE * aspect)
    target_h = int(target_w / aspect)
    dst = np.array([[0, 0], [target_w, 0], [target_w, target_h], [0, target_h]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(quad_arr, dst)
    warped = cv2.warpPerspective(bgr, m, (target_w, target_h), flags=cv2.INTER_LANCZOS4,
                                  borderMode=cv2.BORDER_REPLICATE)

    # Alpha adouci : opaque à l'intérieur, dégradé sur ~4 px au bord — un
    # détourage franc au pixel près a un aspect "découpé aux ciseaux".
    alpha = np.full((target_h, target_w), 255, dtype=np.uint8)
    feather = max(2, round(min(target_w, target_h) * 0.004))
    alpha = cv2.rectangle(np.zeros_like(alpha), (0, 0), (target_w - 1, target_h - 1), 255, -1)
    alpha = cv2.GaussianBlur(alpha, (feather * 2 + 1, feather * 2 + 1), 0)

    rgba = cv2.cvtColor(warped, cv2.COLOR_BGR2RGBA)
    rgba[:, :, 3] = alpha
    return rgba


def crop_label(subject_rgba: np.ndarray) -> np.ndarray:
    """Bande haute d'un slab redressé (numéro de certification PSA) — un
    recadrage simple sur `subject_rgba` qui est déjà à pleine résolution de
    travail (cf. warp_subject), jamais un agrandissement après coup."""
    h = subject_rgba.shape[0]
    band_h = round(h * 0.22)
    return subject_rgba[:band_h, :, :].copy()


# ------------------------------------------------------------------ luminance

def _mean_luminance(rgb: np.ndarray, alpha: np.ndarray | None = None) -> float:
    """Luminance perçue moyenne (coefficients Rec. 709, mêmes que le calcul
    de contraste des badges côté frontend), normalisée 0..1."""
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    if alpha is not None:
        mask = alpha > 10
        if not mask.any():
            return 0.5
        return float(lum[mask].mean() / 255)
    return float(lum.mean() / 255)


# ---------------------------------------------------------------- composition

def _paste_centered(canvas: np.ndarray, subject_rgba: np.ndarray, margin_frac: float,
                     shadow: bool, vignette: bool) -> None:
    """Redimensionne le sujet pour tenir dans `canvas` moins une marge, colle
    au centre par alpha-compositing, ombre portée et vignettage optionnels.
    Modifie `canvas` en place (RGB uint8)."""
    ch, cw = canvas.shape[:2]
    max_w, max_h = cw * (1 - margin_frac), ch * (1 - margin_frac)
    sh, sw = subject_rgba.shape[:2]
    scale = min(max_w / sw, max_h / sh)
    new_w, new_h = max(1, round(sw * scale)), max(1, round(sh * scale))
    subj = cv2.resize(subject_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA)
    x0, y0 = (cw - new_w) // 2, (ch - new_h) // 2

    if shadow:
        shadow_layer = np.zeros((ch, cw), dtype=np.uint8)
        pad = max(4, round(min(new_w, new_h) * 0.03))
        cv2.rectangle(shadow_layer, (x0 + pad, y0 + pad + 6), (x0 + new_w + pad, y0 + new_h + pad + 6), 90, -1)
        shadow_layer = cv2.GaussianBlur(shadow_layer, (0, 0), sigmaX=max(6, pad))
        canvas[:] = (canvas * (1 - (shadow_layer[:, :, None] / 255) * 0.35)).astype(np.uint8)

    alpha = subj[:, :, 3:4].astype(np.float32) / 255
    region = canvas[y0:y0 + new_h, x0:x0 + new_w]
    canvas[y0:y0 + new_h, x0:x0 + new_w] = (subj[:, :, :3] * alpha + region * (1 - alpha)).astype(np.uint8)

    if vignette:
        yy, xx = np.mgrid[0:ch, 0:cw]
        dist = np.sqrt((xx - cw / 2) ** 2 + (yy - ch / 2) ** 2) / (np.sqrt(cw ** 2 + ch ** 2) / 2)
        vig = 1 - 0.22 * np.clip((dist - 0.55) / 0.45, 0, 1)
        canvas[:] = (canvas * vig[:, :, None]).astype(np.uint8)


def compose_flat(subject_rgba: np.ndarray, color_name: str, shadow: bool = False) -> dict:
    """Mode par défaut : aplat rigoureusement uniforme. Ne modifie JAMAIS la
    couleur choisie — signale seulement un avertissement si le contraste
    avec le sujet est insuffisant, avec une alternative suggérée."""
    color = BG_COLORS.get(color_name, BG_COLORS["noir"])
    canvas = np.full((CANVAS_SIZE, CANVAS_SIZE, 3), color[::-1], dtype=np.uint8)  # stocké en RGB
    _paste_centered(canvas, subject_rgba, margin_frac=0.14, shadow=shadow, vignette=False)

    subj_lum = _mean_luminance(subject_rgba[:, :, :3], subject_rgba[:, :, 3])
    bg_lum = sum(color) / (3 * 255)
    warnings = []
    if abs(subj_lum - bg_lum) < CONTRAST_MIN_DELTA:
        alt_order = sorted((c for c in BG_COLORS if c != color_name),
                            key=lambda c: -abs(subj_lum - sum(BG_COLORS[c]) / (3 * 255)))
        warnings.append(f"Contraste faible entre le sujet et le fond {color_name} — "
                         f"essaie plutôt {alt_order[0]}.")
    return {"canvas": canvas, "warnings": warnings}


def compose_palette(subject_rgba: np.ndarray, shadow: bool = True, vignette: bool = True) -> dict:
    """Dégradé radial à partir des couleurs dominantes du sujet, bordure et
    fond du boîtier exclus (sinon tout tire vers le blanc/noir de la marge)."""
    h, w = subject_rgba.shape[:2]
    inset_y, inset_x = round(h * 0.18), round(w * 0.18)
    core = subject_rgba[inset_y:h - inset_y, inset_x:w - inset_x]
    pixels = core[:, :, :3][core[:, :, 3] > 200].reshape(-1, 3).astype(np.float32)
    if len(pixels) < 10:
        pixels = subject_rgba[:, :, :3].reshape(-1, 3).astype(np.float32)

    k = min(3, max(1, len(np.unique(pixels.astype(np.uint8), axis=0))))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)
    colors = centers[order].astype(np.uint8)
    if len(colors) < 2:
        colors = np.vstack([colors, np.clip(colors.astype(int) - 40, 0, 255).astype(np.uint8)])

    yy, xx = np.mgrid[0:CANVAS_SIZE, 0:CANVAS_SIZE].astype(np.float32)
    dist = np.sqrt((xx - CANVAS_SIZE / 2) ** 2 + (yy - CANVAS_SIZE / 2) ** 2)
    dist /= dist.max()
    canvas = (colors[0][None, None, :].astype(np.float32) * (1 - dist[:, :, None])
              + colors[1][None, None, :].astype(np.float32) * dist[:, :, None])
    canvas = canvas.astype(np.uint8)

    canvas = _apply_contrast_rule(canvas, subject_rgba)
    _paste_centered(canvas, subject_rgba, margin_frac=0.16, shadow=shadow, vignette=vignette)
    return {"canvas": canvas, "warnings": []}


def compose_continuity(subject_rgba: np.ndarray, shadow: bool = True, vignette: bool = True) -> dict:
    """Le fond prolonge visuellement la carte : sujet agrandi, flouté,
    désaturé, assombri — sur lequel le sujet net est reposé par-dessus."""
    sh, sw = subject_rgba.shape[:2]
    scale = max(CANVAS_SIZE / sw, CANVAS_SIZE / sh) * 1.35
    big = cv2.resize(subject_rgba[:, :, :3], (round(sw * scale), round(sh * scale)), interpolation=cv2.INTER_AREA)
    x0 = (big.shape[1] - CANVAS_SIZE) // 2
    y0 = (big.shape[0] - CANVAS_SIZE) // 2
    canvas = big[y0:y0 + CANVAS_SIZE, x0:x0 + CANVAS_SIZE].copy()

    k = max(31, (round(CANVAS_SIZE / 1600 * 70) // 2) * 2 + 1)
    canvas = cv2.GaussianBlur(canvas, (k, k), 0)
    hsv = cv2.cvtColor(canvas, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[:, :, 1] *= 0.55
    hsv[:, :, 2] *= 0.72
    canvas = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2RGB)

    canvas = _apply_contrast_rule(canvas, subject_rgba)
    _paste_centered(canvas, subject_rgba, margin_frac=0.16, shadow=shadow, vignette=vignette)
    return {"canvas": canvas, "warnings": []}


def _apply_contrast_rule(canvas: np.ndarray, subject_rgba: np.ndarray) -> np.ndarray:
    """Décale la luminance du fond d'au moins CONTRAST_MIN_DELTA, dans la
    direction opposée à celle du sujet — jamais utilisé en mode aplat, où la
    couleur choisie est fixe par définition."""
    subj_lum = _mean_luminance(subject_rgba[:, :, :3], subject_rgba[:, :, 3])
    bg_lum = _mean_luminance(canvas)
    delta = subj_lum - bg_lum
    if abs(delta) >= CONTRAST_MIN_DELTA:
        return canvas
    target_bg_lum = subj_lum - CONTRAST_MIN_DELTA if subj_lum >= 0.5 else subj_lum + CONTRAST_MIN_DELTA
    target_bg_lum = float(np.clip(target_bg_lum, 0.03, 0.97))
    factor = target_bg_lum / max(bg_lum, 0.02)
    return np.clip(canvas.astype(np.float32) * factor, 0, 255).astype(np.uint8)


COMPOSERS = {"aplat": compose_flat, "palette": compose_palette, "continuite": compose_continuity}

RAW_MAX_DIM = 3000  # borne la mémoire d'une photo brute avant même le redimensionnement de travail


def decode_upload(raw: bytes) -> np.ndarray:
    """Décode un envoi brut (JPEG/PNG/HEIC/WebP) en image BGR pour OpenCV.
    Passe par Pillow (+ pillow-heif, déjà utilisé par media.py) : cv2 seul ne
    sait pas lire le HEIC, très courant sur les photos prises à l'iPhone."""
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(raw))
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]
    scale = min(1.0, RAW_MAX_DIM / max(h, w))
    if scale < 1.0:
        arr = cv2.resize(arr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def encode_outputs(canvas_rgb: np.ndarray) -> dict:
    """JPEG q90 + WebP à partir d'un canevas RGB — les deux formats de
    sortie demandés, un seul rendu calculé."""
    bgr = cv2.cvtColor(canvas_rgb, cv2.COLOR_RGB2BGR)
    ok_jpg, jpg_buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    ok_webp, webp_buf = cv2.imencode(".webp", bgr, [cv2.IMWRITE_WEBP_QUALITY, 90])
    if not (ok_jpg and ok_webp):
        raise ValueError("échec de l'encodage de sortie")
    return {"jpg": jpg_buf.tobytes(), "webp": webp_buf.tobytes()}
