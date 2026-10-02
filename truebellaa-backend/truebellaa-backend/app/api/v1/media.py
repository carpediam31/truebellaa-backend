"""
Media proxy — serves product images that live on MilesWeb storage.

Why this exists: images are uploaded to MilesWeb over FTP, but the browser
can only load them straight from the hosting box once the domain's DNS
points there. Until then this endpoint bridges the gap — the browser asks
this API, the API fetches the file from MilesWeb and streams it back.

Once DNS is pointed at the hosting box, set MEDIA_DELIVERY=direct in .env
and new uploads get the fast direct URL instead. Nothing needs re-uploading;
`scripts/rewrite_image_urls.py` converts the existing rows.

Responses are cached on disk, so each image costs one FTP round trip ever,
not one per page view.
"""
import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.config import settings
from app.integrations import mileswebstorage_client

router = APIRouter(prefix="/media", tags=["media"])

# Accepts both shapes we store: ULID names from admin-panel uploads
# ("01M3XZ…png") and slug names for the site's own assets
# ("eagle-statement-pendant-alt.jpg").
#
# This doubles as the path-traversal guard. The name part allows only
# letters, digits, hyphen and underscore — no "/" and no "." — so "..",
# "../../wp-config.php" and any absolute path simply cannot match, and
# nothing can escape FTP_BASE_DIR.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,90}\.(jpg|jpeg|png|webp|gif)$")

_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
}


def _cache_path(name: str) -> str:
    return os.path.join(settings.MEDIA_CACHE_DIR, name)


@router.get("/products/{filename}")
def get_product_image(filename: str):
    if not _NAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="Not found")

    ext = filename.rsplit(".", 1)[1].lower()
    media_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    # Filenames are unique per upload, so a cached copy can never go stale.
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}

    cached = _cache_path(filename)
    if os.path.exists(cached):
        with open(cached, "rb") as fh:
            return Response(content=fh.read(), media_type=media_type, headers=headers)

    try:
        data = mileswebstorage_client.download_image(filename)
    except mileswebstorage_client.StorageUploadError as exc:
        # Missing file and unreachable storage are both "can't serve it", but
        # the message matters a lot when debugging, so keep it in the detail.
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        os.makedirs(settings.MEDIA_CACHE_DIR, exist_ok=True)
        tmp = f"{cached}.part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, cached)  # atomic: never serve a half-written file
    except OSError:
        pass  # caching is an optimisation, not a requirement

    return Response(content=data, media_type=media_type, headers=headers)
