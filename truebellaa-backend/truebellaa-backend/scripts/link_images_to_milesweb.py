"""
Point existing product_images rows at the copies now living on MilesWeb.

Matches each row by the filename already in its url (e.g.
"/images/products/box-chain-necklace.jpg" -> "box-chain-necklace.jpg"),
confirms that file really is on MilesWeb, then records the storage
metadata and rewrites the url for the current MEDIA_DELIVERY mode.

    python scripts/link_images_to_milesweb.py            # preview
    python scripts/link_images_to_milesweb.py --apply    # write

Safe to re-run; rows already pointing at MilesWeb are left alone.
"""
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ftplib import all_errors                              # noqa: E402
from app.core.config import settings                       # noqa: E402
from app.core.database import WriteSession                 # noqa: E402
from app.integrations import mileswebstorage_client as mws  # noqa: E402
from app.models.catalog import ProductImage                # noqa: E402


def main() -> int:
    apply = "--apply" in sys.argv
    db = WriteSession()

    ftp = mws._connect()
    try:
        ftp.cwd(settings.FTP_BASE_DIR)
        remote = {}
        for name in (e.split("/")[-1] for e in ftp.nlst()):
            if name in (".", ".."):
                continue
            try:
                remote[name] = ftp.size(name)
            except all_errors:
                remote[name] = None
    finally:
        try:
            ftp.quit()
        except all_errors:
            ftp.close()

    print(f"{len(remote)} file(s) on MilesWeb at {settings.FTP_BASE_DIR}")
    print(f"MEDIA_DELIVERY = {settings.MEDIA_DELIVERY}\n")

    rows = db.execute(select(ProductImage)).scalars().all()
    linked, skipped, missing = 0, 0, []

    for img in rows:
        name = (img.url or "").rsplit("/", 1)[-1]
        if img.storage_path and img.storage_provider == "mileswebstorage":
            skipped += 1
            continue
        if name not in remote:
            missing.append(name)
            continue

        ext = name.rsplit(".", 1)[-1].lower()
        new_url = mws.public_url_for(name)
        print(f"  {name}")
        print(f"    url -> {new_url}")
        print(f"    {remote[name]} bytes, .{ext}")
        if apply:
            img.url = new_url
            img.storage_path = f"{settings.FTP_BASE_DIR.rstrip('/')}/{name}"
            img.storage_provider = "mileswebstorage"
            img.file_size_bytes = remote[name]
            img.file_extension = ext
            if not img.original_filename:
                img.original_filename = name
        linked += 1

    print()
    if missing:
        print(f"NOT on MilesWeb, left untouched ({len(missing)}): {sorted(set(missing))}")
    if skipped:
        print(f"Already linked, skipped: {skipped}")

    if apply and linked:
        db.commit()
        print(f"Linked {linked} image row(s) to MilesWeb.")
    elif linked:
        print(f"{linked} row(s) would be linked. Re-run with --apply to write.")
    else:
        print("Nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
