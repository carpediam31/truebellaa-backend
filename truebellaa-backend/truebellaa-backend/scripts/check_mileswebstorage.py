"""
MilesWeb storage connection checker.

Run this after putting FTP_USER / FTP_PASSWORD in .env:

    cd backend/truebellaa-backend/truebellaa-backend
    .\\venv\\Scripts\\Activate.ps1
    python scripts/check_mileswebstorage.py

It does the whole round trip and tells you exactly what to put in .env:
  1. connects + logs in (retries with FTPS if plain FTP is refused)
  2. shows where the login lands and what's in there
  3. locates/creates the target folder
  4. uploads a real test PNG
  5. fetches the public URL over HTTPS to prove the web can see it
  6. deletes the test file again

Nothing here writes to your database, and the test file is removed at the
end — it's safe to run as many times as you like.
"""
import base64
import io
import os
import sys
from ftplib import FTP, FTP_TLS, all_errors

# Make "app" importable when run as "python scripts/check_mileswebstorage.py".
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TEST_NAME = "_truebellaa_storage_check.png"

OK, BAD, INFO = "[ OK ]", "[FAIL]", "      "


def _probe(url: str, host_header: str | None = None,
           insecure: bool = False, indent: bool = False) -> bool:
    """GET `url` and report whether it returned exactly our test PNG."""
    pad = "  " if indent else ""
    headers = {"Host": host_header} if host_header else {}
    try:
        resp = httpx.get(url, headers=headers, timeout=20,
                         follow_redirects=True, verify=not insecure)
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} {pad}{type(exc).__name__}: {str(exc)[:70]}")
        return False

    ctype = resp.headers.get("content-type", "?").split(";")[0]
    if resp.status_code == 200 and resp.content == PNG:
        print(f"{OK} {pad}HTTP 200, {len(resp.content)} bytes, {ctype} — bytes match")
        return True
    if resp.status_code == 200:
        # A 200 that isn't our file means something else answered: a parking
        # page, a SPA catch-all, or a CMS 404-with-200.
        print(f"{BAD} {pad}HTTP 200 but served {len(resp.content)}b of {ctype}, "
              f"not our image — something else is answering this URL.")
        return False
    print(f"{BAD} {pad}HTTP {resp.status_code} ({ctype})")
    return False


def main() -> int:
    print("=" * 68)
    print(" MilesWeb storage check")
    print("=" * 68)

    if not settings.FTP_USER or not settings.FTP_PASSWORD:
        print(f"{BAD} FTP_USER / FTP_PASSWORD are still empty in .env")
        print(f"{INFO} Fill them in (mPanel -> Advanced -> FTP accounts -> Manage),")
        print(f"{INFO} then run this again. Until then uploads stay in local DEMO mode.")
        return 1

    print(f"{INFO} host : {settings.FTP_HOST}:{settings.FTP_PORT}")
    print(f"{INFO} user : {settings.FTP_USER}")
    print(f"{INFO} tls  : {settings.FTP_USE_TLS}")
    print()

    # ---- 1. connect + login (fall back to FTPS automatically) -----------
    # Try whatever .env says first, then the other mode, so a wrong
    # FTP_USE_TLS reports the right answer instead of just failing.
    ftp, used_tls = None, settings.FTP_USE_TLS
    for attempt_tls in (settings.FTP_USE_TLS, not settings.FTP_USE_TLS):
        cls = FTP_TLS if attempt_tls else FTP
        candidate = cls()
        try:
            candidate.connect(settings.FTP_HOST, settings.FTP_PORT, timeout=30)
            candidate.login(settings.FTP_USER, settings.FTP_PASSWORD)
            if attempt_tls:
                candidate.prot_p()
            ftp, used_tls = candidate, attempt_tls
            break
        except all_errors as exc:
            label = "FTPS" if attempt_tls else "plain FTP"
            print(f"{INFO} {label} login failed: {exc}")
            try:
                candidate.close()
            except all_errors:
                pass

    if ftp is None:
        print(f"{BAD} Could not log in with either plain FTP or FTPS.")
        print(f"{INFO} Double-check the username and the password you just set.")
        return 1

    print(f"{OK} logged in ({'FTPS' if used_tls else 'plain FTP'})")
    if used_tls != settings.FTP_USE_TLS:
        print(f"{INFO} >>> set FTP_USE_TLS={str(used_tls).lower()} in .env")

    try:
        # ---- 2. where did we land, and what's here? ---------------------
        home = ftp.pwd()
        print(f"{OK} login directory: {home}")
        try:
            entries = ftp.nlst()
        except all_errors:
            entries = []
        visible = [e for e in entries if e not in (".", "..")]
        print(f"{INFO} contents: {', '.join(visible[:12]) if visible else '(empty)'}")

        # ---- 3. target folder -------------------------------------------
        target = settings.FTP_BASE_DIR
        try:
            ftp.cwd(target)
            print(f"{OK} entered FTP_BASE_DIR: {target}")
        except all_errors as exc:
            print(f"{INFO} '{target}' not reachable directly ({exc})")
            # Try to find an existing Images folder near the login dir.
            guess = next((e for e in visible if e.strip("/").lower() == "images"), None)
            if guess:
                ftp.cwd(home)
                ftp.cwd(guess)
                target = ftp.pwd()
                print(f"{OK} found an Images folder instead: {target}")
                print(f"{INFO} >>> set FTP_BASE_DIR={target} in .env")
            else:
                ftp.cwd(home)
                try:
                    ftp.mkd("Images")
                    ftp.cwd("Images")
                    target = ftp.pwd()
                    print(f"{OK} created a new Images folder: {target}")
                    print(f"{INFO} >>> set FTP_BASE_DIR={target} in .env")
                except all_errors as exc2:
                    print(f"{BAD} Couldn't reach or create an images folder: {exc2}")
                    print(f"{INFO} Use mPanel's File Manager to check the path, or set")
                    print(f"{INFO} FTP_BASE_DIR to a folder this FTP user owns.")
                    return 1

        upload_dir = ftp.pwd()

        # ---- 4. upload ---------------------------------------------------
        try:
            ftp.storbinary(f"STOR {TEST_NAME}", io.BytesIO(PNG))
            print(f"{OK} uploaded {TEST_NAME} ({len(PNG)} bytes) to {upload_dir}")
        except all_errors as exc:
            print(f"{BAD} Upload refused: {exc}")
            print(f"{INFO} The FTP user can read {upload_dir} but not write to it.")
            return 1

        listed = TEST_NAME in [e.split("/")[-1] for e in ftp.nlst()]
        print(f"{OK if listed else BAD} file {'is' if listed else 'is NOT'} listed on the server")

        # ---- 5. is it actually on the web? ------------------------------
        public_url = f"{settings.FTP_PUBLIC_BASE_URL.rstrip('/')}/{TEST_NAME}"
        print()
        print(f"{INFO} checking public URL: {public_url}")
        web_ok = _probe(public_url)

        # The domain's DNS may not point at the hosting box yet (a parked
        # domain, a pending migration). In that case the URL above tests the
        # wrong server entirely, so also ask the hosting box DIRECTLY, with a
        # Host header, bypassing DNS. That separates "the storage path is
        # wrong" from "the DNS isn't pointed yet" — very different fixes.
        direct_ok = False
        if not web_ok:
            host = httpx.URL(public_url).host
            path = httpx.URL(public_url).path
            print()
            print(f"{INFO} DNS may not point here yet — asking {settings.FTP_HOST} directly")
            print(f"{INFO} (Host: {host}, certificate check off, DNS bypassed)")
            for scheme in ("https", "http"):
                direct = f"{scheme}://{settings.FTP_HOST}{path}"
                if _probe(direct, host_header=host, insecure=True, indent=True):
                    direct_ok = True
                    print(f"{OK} the FOLDER IS web-served by the hosting box.")
                    print(f"{INFO} Only DNS for '{host}' is pointing elsewhere.")
                    break

        # ---- 6. clean up -------------------------------------------------
        try:
            ftp.delete(TEST_NAME)
            print()
            print(f"{OK} removed the test file")
        except all_errors as exc:
            print(f"{INFO} couldn't delete the test file ({exc}) — remove "
                  f"{TEST_NAME} by hand from mPanel's File Manager.")

        print()
        print("=" * 68)
        if web_ok:
            print(" READY. Restart uvicorn and uploads go to MilesWeb")
            print(" (storage_provider = 'mileswebstorage' instead of 'local').")
        elif direct_ok:
            host = httpx.URL(public_url).host
            print(" STORAGE IS FINE — this is a DNS problem, not a code problem.")
            print()
            print(f" Files upload correctly and the hosting box serves them, but")
            print(f" '{host}' resolves somewhere other than {settings.FTP_HOST},")
            print(" so the public internet can't see them yet. Fix by pointing an")
            print(f" A record at {settings.FTP_HOST} — either the domain itself, or")
            print(" a dedicated subdomain (e.g. images.yourdomain.com) if you don't")
            print(" want to move the main site yet. Then update FTP_PUBLIC_BASE_URL")
            print(" and re-run this check.")
        else:
            print(" FTP upload works; the file is NOT reachable over the web.")
            print(" The folder is most likely outside the site's web root.")
            print(" In mPanel's File Manager, find the folder the website serves")
            print(" from, point FTP_BASE_DIR at a subfolder of THAT, and re-run.")
        print("=" * 68)
        return 0 if web_ok else 1

    finally:
        try:
            ftp.quit()
        except all_errors:
            ftp.close()


if __name__ == "__main__":
    sys.exit(main())
