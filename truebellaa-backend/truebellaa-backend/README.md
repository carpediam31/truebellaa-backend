# TrueBellaa — Backend (Phase 2)

A **multi-tenant jewellery-commerce API** built with **FastAPI + SQLAlchemy + MySQL**.
It sits directly on top of the Phase 1 database (the `database/` folder) and powers all four panels — Admin, Manager, Marketing/Sales, and the storefront Customer — plus Razorpay payments and Shiprocket delivery.

> Every flow in here has been **run and tested end-to-end against the real database**: staff login, product listing in Hindi, cart, checkout, Razorpay payment, Shiprocket shipment + tracking, an audited price change, RBAC blocking, and webhook idempotency all passed.

---

## 1. What this backend does (in one breath)

A shopper opens the storefront → the API serves products **in their language** → they add to a cart → check out → a **Razorpay** payment is created and verified → the order is saved → a Manager creates a **Shiprocket** shipment → tracking updates flow back → and **every action** (logins, price changes, shipping) is written to the **audit log** the Admin panel reads. All of it is scoped to a **tenant** (brand), so many brands can share one deployment safely.

---

## 2. The "JPA for Python" you asked for

You wanted Java's JPA idea — *write the backend once, change the database without rewriting code*. Here's the exact mapping used in this project:

| Java / JPA | Here (Python) | File |
|---|---|---|
| Hibernate / JPA | **SQLAlchemy ORM** — tables become Python classes | `app/models/` |
| `@Entity` | model classes | `app/models/*.py` |
| JPA Repository | **`BaseRepository`** with get/list/add/delete | `app/repositories/base.py` |
| `persistence.xml` / datasource | **two engines** (primary + replica) | `app/core/database.py` |
| Flyway / Liquibase | **the `database/` SQL files** (or Alembic later) | `../database/` |

Because SQLAlchemy writes the SQL for you, moving from MySQL to PostgreSQL later is basically a **connection-URL change**, not a rewrite.

---

## 3. Folder map

```
app/
  main.py                  FastAPI app + CORS + /health
  core/
    config.py              settings from .env (one typed object)
    database.py            primary/replica engines, sessions, set_audit_actor()
    security.py            bcrypt password hashing + JWT tokens
    ids.py                 ULID generator for public_id
    deps.py                the guards: tenant, staff auth, RBAC, customer, locale
    rbac_query.py          "what permissions does this staff user have?"
    i18n.py                locale resolution + translation fallback
  models/                  SQLAlchemy models (one file per table group)
  repositories/base.py     the generic JPA-style repository
  services/                business logic (auth, catalog, cart, order, payment, shipping, audit)
  integrations/            razorpay_client.py, shiprocket_client.py (with DEMO mode)
  schemas/api.py           request/response shapes (pydantic)
  api/v1/                  the endpoints (routers), incl. admin/ subfolder
requirements.txt  .env.example  run.sh
```

---

## 4. Setup & run (step by step)

**Prerequisite:** the Phase 1 database is loaded (run the `database/sql/*.sql` files on MySQL first).

```bash
# 1. Go into the backend folder
cd backend/truebellaa-backend

# 2. Create a virtual environment + install
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
#    then edit .env — set SECRET_KEY and your DATABASE_*_URL
#    (for local dev, point both primary & replica at the same MySQL)

# 4. Run
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** — an interactive, clickable API explorer (Swagger). Health check: **http://localhost:8000/health**.

> **Passwords:** the seed data uses placeholder password hashes. Before you can log in as staff, set a real one. Quickest way for testing:
> ```python
> from passlib.context import CryptContext
> print(CryptContext(schemes=["bcrypt"]).hash("YourPassword"))
> ```
> then `UPDATE users SET password_hash='<that hash>' WHERE email='admin@truebellaa.com';`

---

## 5. Two important request headers

Every storefront call tells the API **which brand** and **which language**:

| Header | Example | Meaning |
|---|---|---|
| `X-Tenant-Slug` | `truebellaa` | which brand's data to use (multi-tenancy). Defaults to `truebellaa`. |
| `X-Locale` | `hi` | language to render (`en`, `hi`, `ta`, `bn`, `mr`). Falls back to the brand default. |

Staff/customer calls also send `Authorization: Bearer <token>` from login.

---

## 6. Endpoint reference

### Storefront (public / customer)
| Method | Path | What |
|---|---|---|
| GET | `/api/v1/catalog/products` | list products (filters: `category`, `metal`, `in_stock`, `sort`) — localized |
| GET | `/api/v1/catalog/products/{slug}` | product detail with variants + options — localized |
| POST | `/api/v1/cart/items` | add a variant to the cart |
| GET | `/api/v1/cart` | view the cart |
| POST | `/api/v1/checkout` | create an order + start Razorpay payment |
| POST | `/api/v1/payments/verify` | verify the Razorpay payment → mark order paid |
| GET | `/api/v1/orders/{public_id}` | order summary |
| GET | `/api/v1/orders/{public_id}/tracking` | delivery tracking timeline |
| POST | `/api/v1/newsletter/subscribe` | newsletter signup |
| POST | `/api/v1/auth/customer/register` \| `/login` | shopper accounts |

### Webhooks (called by the providers, not the browser)
| Method | Path |
|---|---|
| POST | `/api/v1/payments/webhook/razorpay` |
| POST | `/api/v1/webhook/shiprocket` |

### Admin panels (staff, JWT + permission required)
| Method | Path | Permission |
|---|---|---|
| POST | `/api/v1/auth/staff/login` \| `/logout` \| `/refresh` \| `/me` | — |
| GET | `/api/v1/admin/variants` | `product.view` |
| PATCH | `/api/v1/admin/variants/{sku}/price` | `product.price_update` |
| GET | `/api/v1/admin/variants/{sku}/price-history` | `product.view` |
| GET | `/api/v1/admin/orders` | `order.view` |
| POST | `/api/v1/admin/orders/{public_id}/ship` | `shipment.create` |
| GET | `/api/v1/admin/activity` | `audit.view` |

The 4 panels are the same API with different permissions: Admin has all; Manager has catalogue/orders/shipping/refunds; Marketing/Sales has coupons/reviews/newsletter/customers. A staff member only ever gets what their role's permissions allow (enforced by the `require(...)` guard).

---

## 7. How the key flows work (matching the frontend)

**Checkout** accepts the *same fields your React checkout form already collects* (`email, phone, fname, lname, addr, city, pin, state`) plus the cart lines. It returns what the Razorpay widget needs:

```jsonc
POST /api/v1/checkout
{ "items": [{"sku": "TB-010-SI-20IN", "qty": 1}],
  "email": "...", "phone": "...", "fname": "...", "lname": "...",
  "addr": "...", "city": "...", "pin": "...", "state": "..." }
→ { "order_public_id": "...", "razorpay_order_id": "order_...",
    "razorpay_key_id": "...", "amount": 249.0, "demo_mode": true }
```

Then the browser opens Razorpay, and on success calls `/payments/verify` with the `razorpay_order_id`, `razorpay_payment_id`, and `signature`. The backend verifies the signature, marks the order **paid**, and converts the reserved stock into a sale.

**Demo mode:** if you haven't added Razorpay/Shiprocket keys to `.env`, both run in **demo mode** — payments auto-succeed and a fake tracking number is generated — so you can develop the whole flow before you have live accounts (exactly like your current frontend's demo mode). Add real keys to go live; no code change.

---

## 8. Multi-tenancy & security (how it stays safe)

* Every query is scoped by `tenant_id`; the guards resolve the tenant from `X-Tenant-Slug` (storefront) or the JWT (staff), so one brand can never read another's data.
* Passwords are **bcrypt-hashed**, never stored in plain text.
* JWT access tokens are short-lived; refresh tokens are tracked in `staff_sessions` and can be revoked on logout.
* Razorpay/Shiprocket **webhook signatures are verified**, and every webhook is stored once (idempotent) so a duplicate can't double-process.
* Price changes are attributed to the acting user: `get_staff_write_db` runs `SET @app_user_id = <id>` so the database's price-history trigger records **who** changed the price.

---

## 9. Going live (checklist)

1. Put a strong random `SECRET_KEY` in `.env` (`python -c "import secrets;print(secrets.token_hex(32))"`).
2. Add real `RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET` and `SHIPROCKET_EMAIL/PASSWORD`.
3. Point `DATABASE_PRIMARY_URL` at your primary MySQL and `DATABASE_REPLICA_URL` at a read replica (or the same server until you add a replica).
4. Register the two webhook URLs in the Razorpay and Shiprocket dashboards.
5. Set `DEBUG=false` and run behind a production server (e.g. `uvicorn` workers + a reverse proxy).

---

## 10. What's ready to extend next

The structure makes these drop-in additions (each is a new router/service, no redesign): coupon apply at checkout, reviews write API, wishlist endpoints, refunds (Razorpay), GST/tax lines, customer address book, and admin CRUD for products/users. The models and repositories for most of these already exist.

---

*Phase 2 backend for TrueBellaa. Built on the Phase 1 database, verified end-to-end.*
