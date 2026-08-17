"""
Gestion des photos d'items.

Stockage : <dossier du DB_PATH>/media/<item_id>/<uuid>.webp (+ .thumb.webp)
On déduit le dossier de DB_PATH, jamais /data en dur.

Traitement à l'upload :
- lecture avec Pillow (HEIC/HEIF via pillow-heif)
- application de l'orientation EXIF (ImageOps.exif_transpose)
- strip TOTAL des métadonnées EXIF/GPS (aucune metadata écrite dans les WebP de sortie)
- réencodage WebP : original borné 1600 px grand côté (Q=82), vignette 400 px (Q=80)

Sécurité : les fichiers sont servis par des endpoints authentifiés côté app.py,
pas via un mount statique public.
"""

from __future__ import annotations

import io
import secrets
from pathlib import Path

from PIL import Image, ImageOps

# Enregistre le plugin HEIC/HEIF s'il est disponible. On tolère son absence
# pour ne pas casser l'app si l'installation a raté (rare mais possible).
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

# --- Constantes métier ---
MAX_BYTES = 10 * 1024 * 1024              # 10 Mo avant conversion
MAX_PHOTOS_PER_ITEM = 8
MAX_ORIG = 1600                           # grand côté de l'original WebP
MAX_THUMB = 400                           # grand côté de la vignette

# Mimetypes acceptés côté client. On vérifie le vrai contenu via Pillow ensuite,
# pas seulement le Content-Type déclaré.
ALLOWED_MIME = {
    "image/jpeg", "image/jpg", "image/pjpeg",
    "image/png",
    "image/webp",
    "image/heic", "image/heif",
}


def media_dir(db_path: Path) -> Path:
    """Répertoire de stockage des médias, à côté de la base."""
    return Path(db_path).parent / "media"


def _item_dir(root: Path, item_id: str) -> Path:
    """Vérifie que item_id ne contient rien de dangereux (path traversal)."""
    if not item_id or "/" in item_id or "\\" in item_id or ".." in item_id:
        raise ValueError("item_id invalide")
    return root / item_id


def _photo_id() -> str:
    return secrets.token_hex(8)


def _process(data: bytes) -> tuple[bytes, bytes, tuple[int, int]]:
    """Décode + oriente + strip EXIF + réencode en 2 WebP (original + vignette).

    Retourne (bytes_original, bytes_thumb, (width_original, height_original)).
    Lève ValueError si le contenu n'est pas une image valide.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise ValueError(f"image invalide : {e}") from e

    # Applique l'orientation EXIF puis on abandonne toutes les métadonnées.
    img = ImageOps.exif_transpose(img)

    # Convertit en RGB (WebP supporte RGBA mais on garde simple ; en RGBA si palette
    # transparente pour ne pas perdre l'alpha).
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")

    # Original : borné 1600 px grand côté
    orig = img.copy()
    orig.thumbnail((MAX_ORIG, MAX_ORIG), Image.LANCZOS)
    buf_orig = io.BytesIO()
    orig.save(buf_orig, format="WEBP", quality=82, method=6)

    # Vignette : borné 400 px grand côté
    thumb = img.copy()
    thumb.thumbnail((MAX_THUMB, MAX_THUMB), Image.LANCZOS)
    buf_thumb = io.BytesIO()
    thumb.save(buf_thumb, format="WEBP", quality=80, method=6)

    return buf_orig.getvalue(), buf_thumb.getvalue(), orig.size


def save_photo(root: Path, item_id: str, raw: bytes, declared_mime: str) -> dict:
    """Enregistre une nouvelle photo pour un item.

    Retourne un dict {id, filename, size_bytes, width, height}.
    Lève ValueError sur validation, tout est fait avant écriture disque.
    """
    if declared_mime.lower() not in ALLOWED_MIME:
        raise ValueError(f"type non accepté : {declared_mime}")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"fichier trop lourd (max {MAX_BYTES // (1024*1024)} Mo)")

    orig_bytes, thumb_bytes, (w, h) = _process(raw)

    pid = _photo_id()
    filename = f"{pid}.webp"
    d = _item_dir(root, item_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(orig_bytes)
    (d / f"{pid}.thumb.webp").write_bytes(thumb_bytes)

    return {
        "id": pid,
        "filename": filename,
        "size_bytes": len(orig_bytes),
        "width": w,
        "height": h,
    }


def photo_path(root: Path, item_id: str, photo_id: str, thumb: bool = False) -> Path | None:
    """Chemin filesystem d'une photo. Renvoie None si le fichier n'existe pas."""
    # Nettoie photo_id de la même manière que item_id.
    if not photo_id or "/" in photo_id or "\\" in photo_id or ".." in photo_id:
        return None
    d = _item_dir(root, item_id)
    p = d / (f"{photo_id}.thumb.webp" if thumb else f"{photo_id}.webp")
    return p if p.exists() else None


def delete_photo(root: Path, item_id: str, photo_id: str) -> None:
    """Supprime les deux variantes (original + vignette). Silencieux si absent."""
    if not photo_id or "/" in photo_id or "\\" in photo_id or ".." in photo_id:
        return
    d = _item_dir(root, item_id)
    for name in (f"{photo_id}.webp", f"{photo_id}.thumb.webp"):
        try:
            (d / name).unlink()
        except FileNotFoundError:
            pass


def delete_item_dir(root: Path, item_id: str) -> None:
    """Supprime tout le dossier d'un item (cas suppression de l'item entier)."""
    try:
        d = _item_dir(root, item_id)
    except ValueError:
        return
    if not d.exists():
        return
    for f in d.iterdir():
        try:
            f.unlink()
        except Exception:
            pass
    try:
        d.rmdir()
    except OSError:
        pass


def list_item_files(root: Path, item_id: str) -> list[Path]:
    """Retourne tous les fichiers de photos d'un item (original + vignette).
    Utilisé par l'export ZIP."""
    try:
        d = _item_dir(root, item_id)
    except ValueError:
        return []
    if not d.exists():
        return []
    return sorted(d.iterdir())
