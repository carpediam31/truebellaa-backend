"""
Switch existing product images between proxy and direct delivery.

The files on MilesWeb never move — only the URL stored in product_images.url
changes, so this is instant and safe to run either direction.

    # preview (changes nothing)
    python scripts/rewrite_image_urls.py

    # apply, using whatever MEDIA_DELIVERY says in .env
    python scripts/rewrite_image_urls.py --apply

Typical use: once the domain's DNS points at the hosting box, set
MEDIA_DELIVERY=direct in .env and run this with --apply. Every image then
loads straight from the web server instead of through this API.
"""
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings          # noqa: E402
from app.core.database import WriteSession     # noqa: E402
from app.integrations import mileswebstorage_client  # noqa: E402
from app.models.catalog import ProductImage    # noqa: E402


def main() -> int:
    apply = "--apply" in sys.argv
    db = WriteSession()

    # storage_path is only set by an actual upload through this app, so it —
    # not storage_provider — is what distinguishes files we put on MilesWeb
    # from pre-existing rows (e.g. seed data pointing at the frontend's own
    # /images/products/*.jpg assets, which must never be rewritten).
    rows = db.execute(
        select(ProductImage).where(
            ProductImage.storage_provider == "mileswebstorage",
            ProductImage.storage_path.isnot(None),
        )
    ).scalars().all()

    if not rows:
        print("No MilesWeb-uploaded images in the database yet — nothing to do.")
        print("(Rows without a storage_path are left alone; they aren't ours.)")
        return 0

    print(f"MEDIA_DELIVERY = {settings.MEDIA_DELIVERY}")
    print(f"{len(rows)} MilesWeb image(s) found.\n")

    changed = 0
    for img in rows:
        # storage_path is the authoritative remote location; derive the
        # filename from it rather than trying to parse the old URL.
        name = img.storage_path.rsplit("/", 1)[-1]
        wanted = mileswebstorage_client.public_url_for(name)
        if img.url == wanted:
            continue
        print(f"  id={img.id}")
        print(f"    from: {img.url}")
        print(f"    to  : {wanted}")
        if apply:
            img.url = wanted
        changed += 1

    if not changed:
        print("Every URL already matches the current MEDIA_DELIVERY setting.")
        return 0

    if apply:
        db.commit()
        print(f"\nUpdated {changed} image URL(s).")
    else:
        print(f"\n{changed} image URL(s) would change. Re-run with --apply to write them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
