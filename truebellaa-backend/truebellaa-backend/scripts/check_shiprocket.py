"""
Shiprocket connection checker.

Run this after putting SHIPROCKET_PASSWORD in .env:

    cd backend/truebellaa-backend/truebellaa-backend
    .\\venv\\Scripts\\Activate.ps1
    python scripts/check_shiprocket.py

READ-ONLY by design: it logs in, lists your pickup addresses and asks which
couriers serve a route. It does NOT create an order, book a courier or spend
money. Nothing here can produce a real shipment.

What it tells you:
  1. whether the API user credentials work
  2. whether SHIPROCKET_PICKUP_LOCATION matches a real, verified, ACTIVE
     pickup address — the single most common reason shipments fail
  3. whether couriers are available for a sample delivery pincode
  4. your wallet balance, since a zero balance blocks live bookings
"""
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402

OK, BAD, INFO, WARN = "[ OK ]", "[FAIL]", "      ", "[WARN]"


def main() -> int:
    print("=" * 70)
    print(" Shiprocket connection check  (read-only — books nothing)")
    print("=" * 70)

    if not settings.SHIPROCKET_PASSWORD:
        print(f"{BAD} SHIPROCKET_PASSWORD is empty in .env")
        print(f"{INFO} Shiprocket -> Settings -> Additional Settings -> API Users.")
        print(f"{INFO} Use the API user's password, NOT your phone/OTP dashboard login.")
        print(f"{INFO} Until then shipping stays in DEMO mode (fake AWBs) — which")
        print(f"{INFO} is fine for a demo; the whole order flow still works.")
        return 1

    base = settings.SHIPROCKET_BASE_URL.rstrip("/")
    print(f"{INFO} base url : {base}")
    print(f"{INFO} api user : {settings.SHIPROCKET_EMAIL}")
    print(f"{INFO} pickup   : {settings.SHIPROCKET_PICKUP_LOCATION!r}")
    print()

    # ---- 1. login -----------------------------------------------------
    try:
        r = httpx.post(f"{base}/auth/login", timeout=30, json={
            "email": settings.SHIPROCKET_EMAIL,
            "password": settings.SHIPROCKET_PASSWORD,
        })
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} Could not reach {base}: {type(exc).__name__}: {exc}")
        print(f"{INFO} If you switched to sandbox, check SHIPROCKET_BASE_URL.")
        return 1

    if r.status_code != 200 or not r.json().get("token"):
        print(f"{BAD} Login failed (HTTP {r.status_code}): {str(r.text)[:200]}")
        print(f"{INFO} Common causes:")
        print(f"{INFO}   * using the dashboard login instead of an API user")
        print(f"{INFO}   * the API user is toggled Inactive")
        print(f"{INFO}   * sandbox credentials against the live URL (or vice versa)")
        return 1

    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"{OK} logged in — token received (valid ~10 days)")

    # ---- 2. pickup addresses -----------------------------------------
    try:
        pr = httpx.get(f"{base}/settings/company/pickup", headers=headers, timeout=30)
        data = pr.json() if pr.status_code == 200 else {}
        addresses = (data.get("data") or {}).get("shipping_address") or []
    except Exception as exc:  # noqa: BLE001
        addresses = []
        print(f"{WARN} could not list pickup addresses: {exc}")

    if addresses:
        print(f"{OK} {len(addresses)} pickup address(es) on the account:")
        wanted = settings.SHIPROCKET_PICKUP_LOCATION.strip().lower()
        match = None
        for a in addresses:
            nick = str(a.get("pickup_location", ""))
            city = a.get("city", "?")
            # Report the raw status rather than guessing what it means.
            # Shiprocket documents 1 = active; anything else is worth a look,
            # and treating "is_primary" as proof of active was wrong.
            st = a.get("status")
            state = "active" if st in (1, "1", True) else f"status={st} (not 1)"
            flag = "  <-- configured" if nick.strip().lower() == wanted else ""
            print(f"{INFO}   {nick!r:<22} {city:<14} {state}{flag}")
            if nick.strip().lower() == wanted:
                match = a

        if match is not None and match.get("status") not in (1, "1", True):
            print(f"{WARN} '{match.get('pickup_location')}' reports status="
                  f"{match.get('status')}, not 1 (active).")
            print(f"{INFO} In Settings -> Company -> Pick Up Address the Status toggle")
            print(f"{INFO} appears OFF. Rate checks still work, but booking a real")
            print(f"{INFO} shipment may be refused. Turn the toggle ON to be safe.")

        if match is None:
            print(f"{BAD} SHIPROCKET_PICKUP_LOCATION={settings.SHIPROCKET_PICKUP_LOCATION!r} "
                  f"matches none of them.")
            print(f"{INFO} Copy one of the nicknames above into .env exactly.")
            return 1
        print(f"{OK} pickup location matches a real address")

    # ---- 3. courier serviceability (read-only) ------------------------
    pin = None
    if addresses:
        for a in addresses:
            if str(a.get("pickup_location", "")).strip().lower() == \
                    settings.SHIPROCKET_PICKUP_LOCATION.strip().lower():
                pin = a.get("pin_code") or a.get("pin")
                break
    pickup_pin, drop_pin = str(pin or "282007"), "400001"
    try:
        sr = httpx.get(f"{base}/courier/serviceability/", headers=headers, timeout=30,
                       params={"pickup_postcode": pickup_pin, "delivery_postcode": drop_pin,
                               "cod": 0, "weight": 0.5})
        couriers = ((sr.json().get("data") or {}).get("available_courier_companies") or []
                    ) if sr.status_code == 200 else []
        if couriers:
            cheapest = min(couriers, key=lambda c: float(c.get("rate") or 9e9))
            print(f"{OK} {len(couriers)} courier(s) serve {pickup_pin} -> {drop_pin}; "
                  f"cheapest {cheapest.get('courier_name')} at Rs{cheapest.get('rate')}")
        else:
            print(f"{WARN} no couriers returned for {pickup_pin} -> {drop_pin} "
                  f"(HTTP {sr.status_code}). Often means KYC or the pickup address "
                  f"is still pending approval.")
    except Exception as exc:  # noqa: BLE001
        print(f"{WARN} serviceability check failed: {exc}")

    # ---- 4. wallet ----------------------------------------------------
    try:
        wr = httpx.get(f"{base}/account/details/wallet-balance", headers=headers, timeout=20)
        if wr.status_code == 200:
            bal = (wr.json().get("data") or {}).get("balance_amount")
            if bal is not None:
                print(f"{OK if float(bal) > 0 else WARN} wallet balance: Rs{bal}"
                      + ("" if float(bal) > 0 else "  <-- live bookings need credit"))
    except Exception:  # noqa: BLE001
        pass

    print()
    print("=" * 70)
    print(" READY. Restart uvicorn and shipping switches from DEMO to live.")
    print(" Shipments are only created when someone clicks Ship on a PAID")
    print(" order — nothing books itself.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
