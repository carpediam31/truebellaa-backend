"""
MilesWeb file storage integration (product image uploads).

MilesWeb (mPanel) shared hosting doesn't offer an S3-style storage API — the
file manager you see in mPanel just sits on top of plain FTP. So, mirroring
the LIVE/DEMO pattern used for Razorpay/Shiprocket elsewhere in this app:

  * LIVE  — when FTP_* credentials are set in .env, we connect with ftplib
            (or FTP_TLS if FTP_USE_TLS=true) and STOR the file straight into
            the "Images" folder shown in mPanel's File Manager. The public
            URL is built from FTP_PUBLIC_BASE_URL (the domain that folder is
            served under).
  * DEMO  — otherwise, the file is written to a local "uploads/products"
            folder and served by this API itself (see app.main's StaticFiles
            mount), so image upload works end-to-end before MilesWeb
            credentials exist.

Either way the caller gets back the same shape, so app/api/v1/admin/products.py
never needs to know which mode is active.
"""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from ftplib import FTP, FTP_TLS, all_errors, error_perm
from io import BytesIO

from app.core.config import settings
from app.core.ids import new_ulid

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}


@dataclass
class UploadedImage:
    url: str                # public URL to store on product_images.url
    storage_path: str       # where it actually lives (remote FTP path or local path)
    storage_provider: str   # "mileswebstorage" | "local"
    file_extension: str
    file_size_bytes: int


class UnsupportedImageType(ValueError):
    pass


class StorageUploadError(RuntimeError):
    """The file was fine, but the storage backend refused/failed the write."""
    pass


def public_url_for(remote_name: str) -> str:
    """
    The URL to store on product_images.url for a file now on MilesWeb.

    "direct" points the browser at the hosting box's own web server — fastest,
    but only works once the domain's DNS resolves there. "proxy" points at
    this API instead, which streams the bytes back from MilesWeb (see
    app/api/v1/media.py), so images display with no DNS work at all.
    """
    if settings.MEDIA_DELIVERY == "direct":
        return f"{settings.FTP_PUBLIC_BASE_URL.rstrip('/')}/{remote_name}"
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/media/products/{remote_name}"


# First bytes that really identify an image file. The uploader controls the
# filename and the Content-Type header, so neither can be trusted — only the
# bytes can. Without this, "shell.php" renamed to "shell.jpg" lands in the
# web root.
_MAGIC = (
    (b"\xff\xd8\xff", "jpg"),               # JPEG
    (b"\x89PNG\r\n\x1a\n", "png"),          # PNG
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def _sniff_image_type(data: bytes) -> str | None:
    """Return a canonical extension from the file's magic bytes, or None."""
    for sig, kind in _MAGIC:
        if data.startswith(sig):
            return kind
    # WEBP is "RIFF....WEBP"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _safe_extension(filename: str, content_type: str | None) -> str:
    ext = (os.path.splitext(filename or "")[1] or "").lstrip(".").lower()
    if not ext and content_type:
        guessed = mimetypes.guess_extension(content_type) or ""
        ext = guessed.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedImageType(
            f"'{ext or 'unknown'}' isn't a supported image type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def _unique_filename(ext: str) -> str:
    # ULID prefix keeps names unique/sortable and avoids leaking the
    # original filename (and any special characters in it) onto the CDN URL.
    return f"{new_ulid()}.{ext}"


def _upload_ftp(data: bytes, remote_name: str) -> str:
    """
    STOR the file into FTP_BASE_DIR. Any ftplib/socket failure is re-raised
    as StorageUploadError with the MilesWeb server's own message attached —
    wrong password, missing folder and "no such directory" all look identical
    from the admin panel otherwise.
    """
    ftp_cls = FTP_TLS if settings.FTP_USE_TLS else FTP
    ftp = ftp_cls()
    try:
        ftp.connect(settings.FTP_HOST, settings.FTP_PORT, timeout=30)
        ftp.login(settings.FTP_USER, settings.FTP_PASSWORD)
        if settings.FTP_USE_TLS:
            ftp.prot_p()
    except all_errors as exc:
        raise StorageUploadError(
            f"Couldn't connect to MilesWeb storage at {settings.FTP_HOST}:{settings.FTP_PORT} "
            f"— {exc}. Check FTP_HOST / FTP_USER / FTP_PASSWORD in .env."
        ) from exc

    try:
        _ensure_remote_dir(ftp, settings.FTP_BASE_DIR)
        ftp.cwd(settings.FTP_BASE_DIR)
        ftp.storbinary(f"STOR {remote_name}", BytesIO(data))
    except all_errors as exc:
        raise StorageUploadError(
            f"Upload to '{settings.FTP_BASE_DIR}' on MilesWeb failed — {exc}. "
            f"Check that FTP_BASE_DIR exists and the FTP user can write to it."
        ) from exc
    finally:
        try:
            ftp.quit()
        except all_errors:
            ftp.close()

    base = settings.FTP_BASE_DIR.rstrip("/")
    return f"{base}/{remote_name}"


def _ensure_remote_dir(ftp: FTP, path: str) -> None:
    """
    mkdir -p equivalent — MilesWeb's FTP has no such helper.

    Honours whether FTP_BASE_DIR is absolute ("/Images" — resolved from the
    FTP root, which on a chrooted shared-hosting account IS the home dir) or
    relative ("Images" — resolved from wherever the login lands). Getting
    this wrong is the difference between writing into the web root and
    getting a bare "550 permission denied", so don't silently absolutise.
    """
    parts = [p for p in path.split("/") if p]
    if not parts:
        return
    cur = "" if path.startswith("/") else "."
    for part in parts:
        cur = f"{cur}/{part}"
        try:
            ftp.mkd(cur)
        except error_perm:
            pass  # already exists, or we lack mkdir rights but it's there


def _connect() -> FTP:
    """Open an authenticated FTP/FTPS session, or raise StorageUploadError."""
    ftp_cls = FTP_TLS if settings.FTP_USE_TLS else FTP
    ftp = ftp_cls()
    try:
        ftp.connect(settings.FTP_HOST, settings.FTP_PORT, timeout=30)
        ftp.login(settings.FTP_USER, settings.FTP_PASSWORD)
        if settings.FTP_USE_TLS:
            ftp.prot_p()
        return ftp
    except all_errors as exc:
        try:
            ftp.close()
        except all_errors:
            pass
        raise StorageUploadError(
            f"Couldn't connect to MilesWeb storage at {settings.FTP_HOST}:{settings.FTP_PORT} "
            f"— {exc}. Check FTP_HOST / FTP_USER / FTP_PASSWORD in .env."
        ) from exc


def download_image(remote_name: str) -> bytes:
    """
    Fetch one previously-uploaded file back off MilesWeb.

    Used by the media proxy (app/api/v1/media.py) so images display even
    while the domain's DNS still points somewhere other than the hosting
    box — the browser asks this API, and this API asks MilesWeb.
    """
    ftp = _connect()
    buf = BytesIO()
    try:
        ftp.cwd(settings.FTP_BASE_DIR)
        ftp.retrbinary(f"RETR {remote_name}", buf.write)
    except all_errors as exc:
        raise StorageUploadError(
            f"Couldn't read '{remote_name}' from {settings.FTP_BASE_DIR} — {exc}"
        ) from exc
    finally:
        try:
            ftp.quit()
        except all_errors:
            ftp.close()
    return buf.getvalue()


def _upload_local(data: bytes, filename: str) -> tuple[str, str]:
    os.makedirs(settings.LOCAL_UPLOAD_DIR, exist_ok=True)
    path = os.path.join(settings.LOCAL_UPLOAD_DIR, filename)
    with open(path, "wb") as fh:
        fh.write(data)
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.LOCAL_UPLOAD_PUBLIC_BASE_URL}/{filename}"
    return url, path


def upload_image(data: bytes, filename: str, content_type: str | None = None) -> UploadedImage:
    """Validate + store one product image. Raises UnsupportedImageType or ValueError."""
    ext = _safe_extension(filename, content_type)
    size = len(data)

    # The extension said "image" — now confirm the BYTES agree. This is what
    # stops a script renamed to .jpg being written into the web root.
    sniffed = _sniff_image_type(data)
    if sniffed is None:
        raise UnsupportedImageType(
            f"'{filename}' is not a real image — its contents don't match any supported "
            f"format ({', '.join(sorted(ALLOWED_EXTENSIONS))}). Renaming a file isn't enough."
        )
    # Trust the bytes over the name: a real PNG called ".jpg" is stored as .png.
    if sniffed != ext and not (sniffed == "jpg" and ext in ("jpg", "jpeg")):
        ext = sniffed
    max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
    if size == 0:
        raise ValueError("Uploaded file is empty")
    if size > max_bytes:
        raise ValueError(f"Image is {size / (1024 * 1024):.1f}MB — max allowed is {settings.MAX_IMAGE_SIZE_MB}MB")

    remote_name = _unique_filename(ext)

    if settings.ftp_live:
        remote_path = _upload_ftp(data, remote_name)
        return UploadedImage(url=public_url_for(remote_name), storage_path=remote_path,
                             storage_provider="mileswebstorage",
                             file_extension=ext, file_size_bytes=size)

    url, local_path = _upload_local(data, remote_name)
    return UploadedImage(url=url, storage_path=local_path, storage_provider="local",
                         file_extension=ext, file_size_bytes=size)
