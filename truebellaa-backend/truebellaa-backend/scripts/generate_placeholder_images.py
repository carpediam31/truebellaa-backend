"""
Generate branded placeholder images for the storefront, then upload them
to MilesWeb.

These are NOT product photography — they're tasteful, correctly-sized
stand-ins so no slot on the site renders as a broken grey box. Every file
uses the exact filename the code/README expects, so dropping a real photo
in later is a straight overwrite: same name, same place, nothing to re-wire.

    python scripts/generate_placeholder_images.py            # write locally
    python scripts/generate_placeholder_images.py --upload   # + push to MilesWeb

Needs Pillow (generator only — the app itself doesn't import it):
    pip install Pillow
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This script lives at <repo>/backend/truebellaa-backend/truebellaa-backend/scripts/,
# so four levels up is <repo>, which holds the storefront in truebellaa-react/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
FRONTEND_IMAGES = os.path.join(_REPO, "truebellaa-react", "public", "images")
FRONTEND_PRODUCTS = os.path.join(FRONTEND_IMAGES, "products")

if not os.path.isdir(os.path.join(_REPO, "truebellaa-react", "public")):
    raise SystemExit(
        f"Can't find the storefront's public/ folder under {_REPO}.\n"
        "Fix FRONTEND_IMAGES in this script rather than letting it create "
        "a stray directory in the wrong place."
    )

# ---- palette, lifted from the live site's own CSS -------------------
INK = (20, 18, 15)
INK_SOFT = (33, 29, 23)
BONE = (240, 238, 233)
BONE_WARM = (246, 243, 237)
BONE_COOL = (235, 234, 232)
GOLD = (176, 141, 87)
SILVER = (168, 170, 173)
STEEL = (128, 134, 138)
MUTED = (118, 118, 118)

TONES = {"gold": GOLD, "silver": SILVER, "steel": STEEL}


def _font(size: int, bold: bool = False):
    """Prefer a serif face to match the site's Playfair headings."""
    for name in (("georgiab.ttf", "timesbd.ttf") if bold else ("georgia.ttf", "times.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _centered(d: ImageDraw.ImageDraw, y: int, text: str, font, fill, width: int):
    box = d.textbbox((0, 0), text, font=font)
    d.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)
    return box[3] - box[1]


def _tracked(d: ImageDraw.ImageDraw, y: int, text: str, font, fill, width: int, spacing: int = 4):
    """Letter-spaced caps — the site leans on these for labels."""
    chars = list(text)
    widths = [d.textbbox((0, 0), c, font=font)[2] - d.textbbox((0, 0), c, font=font)[0] for c in chars]
    total = sum(widths) + spacing * (len(chars) - 1)
    x = (width - total) / 2
    for c, w in zip(chars, widths):
        d.text((x, y), c, font=font, fill=fill)
        x += w + spacing


def _vgradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)],
               fill=(int(top[0] + (bottom[0] - top[0]) * t),
                     int(top[1] + (bottom[1] - top[1]) * t),
                     int(top[2] + (bottom[2] - top[2]) * t)))
    return img


# ---------------------------------------------------------------- motifs
def _chain(d, cx, cy, tone, scale=1.0, links=5):
    rx, ry = int(34 * scale), int(22 * scale)
    gap = int(44 * scale)
    start = cx - (links - 1) * gap // 2
    for i in range(links):
        x = start + i * gap
        d.ellipse([x - rx, cy - ry, x + rx, cy + ry], outline=tone, width=max(2, int(4 * scale)))


def _pendant(d, cx, cy, tone, shape, scale=1.0):
    w = max(2, int(3 * scale))
    top = cy - int(150 * scale)
    # the cord
    d.arc([cx - int(110 * scale), top, cx + int(110 * scale), top + int(190 * scale)],
          start=200, end=340, fill=tone, width=w)
    s = int(58 * scale)
    by = cy + int(40 * scale)
    if shape == "triangle":
        d.polygon([(cx, by - s), (cx - s, by + s // 2), (cx + s, by + s // 2)], outline=tone, width=w)
    elif shape == "circle":
        d.ellipse([cx - s, by - s, cx + s, by + s], outline=tone, width=w)
        d.ellipse([cx - s // 2, by - s // 2, cx + s // 2, by + s // 2], outline=tone, width=w)
    elif shape == "cross":
        t = s // 3
        d.rectangle([cx - t // 2, by - s, cx + t // 2, by + s], outline=tone, width=w)
        d.rectangle([cx - s, by - t // 2 - s // 4, cx + s, by + t // 2 - s // 4], outline=tone, width=w)
    elif shape == "tag":
        d.rounded_rectangle([cx - s // 2, by - s, cx + s // 2, by + s], radius=s // 4,
                            outline=tone, width=w)
        d.ellipse([cx - 5, by - s + 10, cx + 5, by - s + 20], outline=tone, width=w)
    elif shape == "bolt":
        d.polygon([(cx + s // 3, by - s), (cx - s // 2, by + s // 6),
                   (cx, by + s // 6), (cx - s // 3, by + s),
                   (cx + s // 2, by - s // 6), (cx, by - s // 6)], outline=tone, width=w)
    elif shape == "wing":
        for i in range(3):
            off = i * int(16 * scale)
            d.arc([cx - s - off, by - s // 2 + off, cx + s + off, by + s + off],
                  start=200, end=340, fill=tone, width=w)
    else:
        d.ellipse([cx - s, by - s, cx + s, by + s], outline=tone, width=w)


def _bracelet(d, cx, cy, tone, scale=1.0):
    w = max(2, int(4 * scale))
    d.ellipse([cx - int(130 * scale), cy - int(78 * scale),
               cx + int(130 * scale), cy + int(78 * scale)], outline=tone, width=w)
    d.ellipse([cx - int(104 * scale), cy - int(56 * scale),
               cx + int(104 * scale), cy + int(56 * scale)], outline=tone, width=max(1, w - 2))


MOTIFS = {"chain": _chain, "bracelet": _bracelet}


def _draw_motif(d, cx, cy, kind, tone, scale=1.0):
    if kind in MOTIFS:
        MOTIFS[kind](d, cx, cy, tone, scale)
    else:
        _pendant(d, cx, cy, tone, kind, scale)


# ------------------------------------------------------------ renderers
def product_tile(path, w, h, title, kind, tone_name, alt=False):
    bg = BONE_COOL if alt else BONE_WARM
    img = _vgradient((w, h), bg, tuple(max(0, c - 10) for c in bg))
    d = ImageDraw.Draw(img)
    tone = TONES[tone_name]

    d.rectangle([28, 28, w - 28, h - 28], outline=(222, 218, 210), width=1)
    # alt shot is framed differently so the hover-swap is visibly a change
    _draw_motif(d, w // 2, h // 2 - (10 if alt else 30), kind, tone, scale=w / 800 * (0.85 if alt else 1.0))

    _tracked(d, int(h * 0.74), title.upper()[:28], _font(max(13, w // 42)), (70, 66, 60), w, 3)
    _tracked(d, int(h * 0.80), ("ALT VIEW" if alt else tone_name.upper()), _font(max(10, w // 62)), tone, w, 5)
    _centered(d, h - 56, f"{w}x{h} placeholder", _font(max(10, w // 70)), (170, 166, 158), w)
    img.save(path, "JPEG", quality=88, optimize=True)
    return os.path.getsize(path)


def dark_tile(path, w, h, eyebrow, title=None, kind=None):
    """
    Dark backdrop for the hero and the video reels.

    `title` is deliberately optional: the site already overlays its own
    headline on the hero and the @handle on each reel, so baking that text
    into the image too would render it twice.
    """
    img = _vgradient((w, h), INK, INK_SOFT)
    d = ImageDraw.Draw(img)
    if kind:
        _draw_motif(d, w // 2, int(h * 0.44), kind, (92, 80, 60), scale=w / 800)
    d.line([(w // 2 - 28, int(h * 0.60)), (w // 2 + 28, int(h * 0.60))], fill=GOLD, width=2)
    _tracked(d, int(h * 0.64), eyebrow.upper(), _font(max(10, w // 90)), GOLD, w, 6)
    if title:
        _centered(d, int(h * 0.69), title, _font(max(20, w // 26)), (242, 240, 236), w)
    _centered(d, h - 48, f"{w}x{h} placeholder", _font(max(10, w // 110)), (120, 114, 102), w)
    img.save(path, "JPEG", quality=88, optimize=True)
    return os.path.getsize(path)


def light_tile(path, w, h, eyebrow, title, kind, tone_name="gold"):
    img = _vgradient((w, h), BONE_WARM, BONE)
    d = ImageDraw.Draw(img)
    d.rectangle([26, 26, w - 26, h - 26], outline=(220, 215, 206), width=1)
    _draw_motif(d, w // 2, int(h * 0.40), kind, TONES[tone_name], scale=w / 800)
    d.line([(w // 2 - 26, int(h * 0.58)), (w // 2 + 26, int(h * 0.58))], fill=TONES[tone_name], width=2)
    _tracked(d, int(h * 0.62), eyebrow.upper(), _font(max(10, w // 80)), MUTED, w, 5)
    _centered(d, int(h * 0.665), title, _font(max(18, w // 24)), (46, 42, 36), w)
    _centered(d, h - 52, f"{w}x{h} placeholder", _font(max(10, w // 90)), (170, 166, 158), w)
    img.save(path, "JPEG", quality=88, optimize=True)
    return os.path.getsize(path)


# --------------------------------------------------------------- catalog
# (filename, w, h, product title, motif, metal tone)
PRODUCTS = [
    ("eagle-statement-pendant",   "Eagle Statement Pendant",   "wing",     "silver"),
    ("herringbone-gold-chain",    "Herringbone Gold Chain",    "chain",    "gold"),
    ("faceted-bar-link-necklace", "Faceted Bar Link Necklace", "chain",    "gold"),
    ("triangle-onyx-pendant",     "Triangle Onyx Pendant",     "triangle", "silver"),
    ("cuban-link-bracelet",       "Cuban Link Bracelet",       "bracelet", "gold"),
    ("rope-steel-chain",          "Rope Steel Chain",          "chain",    "steel"),
    ("black-dog-tag-pendant",     "Black Dog Tag Pendant",     "tag",      "steel"),
    ("compass-medallion-pendant", "Compass Medallion Pendant", "circle",   "silver"),
    ("lightning-bolt-pendant",    "Lightning Bolt Pendant",    "bolt",     "silver"),
    ("cross-pave-pendant",        "Cross Pave Pendant",        "cross",    "silver"),
    ("twisted-bangle-bracelet",   "Twisted Bangle Bracelet",   "bracelet", "gold"),
    ("box-chain-necklace",        "Box Chain Necklace",        "chain",    "silver"),
]


def main() -> int:
    upload = "--upload" in sys.argv
    os.makedirs(FRONTEND_IMAGES, exist_ok=True)
    os.makedirs(FRONTEND_PRODUCTS, exist_ok=True)

    made: list[tuple[str, str, int, str]] = []   # (name, WxH, bytes, purpose)

    # ---- site images (9) ------------------------------------------
    # hero sits BEHIND white headline text, so it must stay dark.
    p = os.path.join(FRONTEND_IMAGES, "hero-banner.jpg")
    made.append(("hero-banner.jpg", "1600x1000",
                 dark_tile(p, 1600, 1000, "TrueBellaa", kind="chain"),
                 "Homepage hero background"))

    for slug, label, kind, tone in (("chains", "Chains", "chain", "gold"),
                                    ("pendants", "Pendants", "triangle", "silver"),
                                    ("bracelets", "Bracelets", "bracelet", "gold")):
        name = f"category-{slug}.jpg"
        p = os.path.join(FRONTEND_IMAGES, name)
        made.append((name, "800x1067",
                     light_tile(p, 800, 1067, "Shop by category", label, kind, tone),
                     f'"{label}" category card'))

    p = os.path.join(FRONTEND_IMAGES, "craft-story.jpg")
    made.append(("craft-story.jpg", "1000x1250",
                 light_tile(p, 1000, 1250, "The craft", "Made by hand", "circle", "gold"),
                 "Craft editorial section"))

    # The site overlays the @handle and a play button on these, so the image
    # itself stays a plain dark backdrop — only the reel number varies.
    for i, handle in enumerate(("@styled.by.aria", "@dailygold", "@layered.look", "@mens.edit"), start=1):
        name = f"reel-{i}.jpg"
        p = os.path.join(FRONTEND_IMAGES, name)
        made.append((name, "600x1067",
                     dark_tile(p, 600, 1067, f"Reel {i:02d}", kind=("chain" if i % 2 else "bracelet")),
                     f"Video reel {i} ({handle})"))

    # ---- product images (12 x 2) ----------------------------------
    for slug, title, kind, tone in PRODUCTS:
        for alt in (False, True):
            name = f"{slug}{'-alt' if alt else ''}.jpg"
            p = os.path.join(FRONTEND_PRODUCTS, name)
            made.append((name, "800x800",
                         product_tile(p, 800, 800, title, kind, tone, alt=alt),
                         f"{title}{' (hover/alt shot)' if alt else ''}"))

    # ---- report ----------------------------------------------------
    print(f"{'FILENAME':<34} {'SIZE':<11} {'BYTES':>8}   PURPOSE")
    print("-" * 100)
    for name, dims, size, purpose in made:
        print(f"{name:<34} {dims:<11} {size:>8}   {purpose}")
    total = sum(m[2] for m in made)
    print("-" * 100)
    print(f"{len(made)} images, {total/1024:.0f} KB total")
    print(f"\nwritten to: {FRONTEND_IMAGES}")

    if upload:
        from ftplib import all_errors
        from app.integrations import mileswebstorage_client as m
        from app.core.config import settings
        print(f"\nUploading {len(made)} file(s) to MilesWeb {settings.FTP_BASE_DIR} ...")
        ftp = m._connect()
        try:
            m._ensure_remote_dir(ftp, settings.FTP_BASE_DIR)
            ftp.cwd(settings.FTP_BASE_DIR)
            for name, _dims, _size, _purpose in made:
                src = os.path.join(FRONTEND_PRODUCTS if name.replace("-alt", "").rsplit(".", 1)[0]
                                   in {p[0] for p in PRODUCTS} else FRONTEND_IMAGES, name)
                with open(src, "rb") as fh:
                    ftp.storbinary(f"STOR {name}", fh)
                print(f"  uploaded {name}")
            remote = [e.split("/")[-1] for e in ftp.nlst()]
            missing = [n for n, *_ in made if n not in remote]
            print(f"\n{len(made) - len(missing)}/{len(made)} confirmed on MilesWeb"
                  + (f" | MISSING: {missing}" if missing else ""))
        except all_errors as exc:
            print(f"  upload failed: {exc}")
            return 1
        finally:
            try:
                ftp.quit()
            except all_errors:
                ftp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
