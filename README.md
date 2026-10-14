# Amamio Farm Products — Sales & Inventory Management System

A monitoring system for the full Amamio flow — **receiving → quality check →
production → packing → sales → reporting** — built so that at any moment you
can say where a given batch of stock is, who handled it, and when.

Built with **Flask** + **JSON-file storage** (one file per table under
`data/`). No database server and no internet are required; the AI layer is
pure Python heuristics, so it runs completely offline. The JSON store is
declared as a real relational schema and exports to MySQL with one command —
see [Moving to MySQL](#moving-to-mysql).

## Quick start

```bash
pip install -r requirements.txt
python run.py
```

Then open <http://localhost:5000> and sign in with a demo account.

### Demo logins (username / password)

| Role | Login | What they do |
|------|-------|--------------|
| Super Admin | `superadmin` / `super123` | Everything, plus roles and the MySQL export |
| Admin | `admin` / `admin123` | Approvals, oversight, reports |
| Production Team Head | `production` / `prod123` | Receiving, recipes, honey QC, production |
| Packing Team Head | `packing` / `pack123` | Packing per channel, platforms, shipping |
| Assets & Maintenance Team Head | `assets` / `assets123` | Equipment, supplies, maintenance |

Demo data is seeded on first run. Delete the `data/` folder to reset.

---

## The monitored flow

### 1. Receiving area — by crate, by weight or by piece

A delivery is opened as a **receiving batch**. Each cage box in it is logged
and gets **its own QR code**, printed from the batch screen.

Each item declares how it is counted — ginger by the kilo, lemon by the
piece, drums by the unit — and the receiving screen uses that when the
checker counts a box. For every box the checker records the **good** and the
**damaged** quantity separately:

* only the **good** quantity joins raw-material stock;
* the **damaged** quantity goes to its own ledger with a mandatory reason, so
  spoilage can be reported per box, per item and per supplier.

A box then moves along the floor — Receiving Area → Storage → Production
Floor → Consumed — so its current location is always known. A batch cannot be
closed while any box is still uncounted.

### 2. Honey production — container QC on moisture and appearance

Honey is monitored **by container**, each with its own QR code. Every
container is checked on **moisture content** and **appearance**, and the
result is **Pass** or **Failed** — nothing else:

* **Pass** → joins sellable honey stock (`For Selling`);
* **Failed** → routed to other products (`For Other Products`), never
  discarded, and the admins are notified.

The system suggests a result from the readings (the pass limit is 20%
moisture) but the checker always confirms it. A decided container cannot be
re-checked.

### 3. Packing area — one run per channel

Nothing ships without a packing run against one of the five channels:
**VIP, Shopee, TikTok, Lazada, Walk-in**. A run records the packer, the date,
the products and quantities, any damage spotted while packing, the courier
and the tracking number, and moves In Progress → Packed → Handed Over.

Stock is released once and only once: a run tied to an internal sales order
does not move stock (confirming that order already did), while a standalone
platform or walk-in run releases the finished goods itself when it is marked
packed.

### 4. Requests to the admin — always with a reason

Any team head can ask the admin to buy something, and **a reason is
mandatory** on every request — out of stock, below reorder level, upcoming
batch, spoilage replacement, and so on, or free text. Requests also carry an
urgency and a needed-by date, and the approver sees all of it before
deciding. Approved items mint a QR token so the goods can be received by
scan.

### 5. Sales platforms — a generic import template

Rather than a parser per marketplace, the system keeps a **template**: a
saved mapping from the fields it stores onto whatever that platform calls its
columns. Drop an export into the `sales-platform/` folder (or upload it),
pick the template, check the preview, import.

Shopee, Lazada and TikTok Shop templates ship ready to use. Adding a new
marketplace is a mapping, not a code change. Re-importing an updated export
is safe — rows already imported are detected and skipped.

Dates are normalised from any common spelling (`04 Oct 2026 18:58`,
`2026-10-10 00:13`, `2026/10/09`) and money is parsed through whatever
commas and currency text the platform uses.

### 6. Assets & maintenance

Equipment and cleaning supplies with their service history: what was done,
when, by whom, what it cost, the downtime, and when the next service falls
due. Anything falling due in the next 14 days surfaces on the dashboard.

---

## Roles

Access is per *module* and declared once in `security.py` (`PERMISSIONS`),
which drives both the sidebar and the route guards.

| Module | Super Admin | Admin | Production | Packing | Assets |
|---|:--:|:--:|:--:|:--:|:--:|
| Dashboard, Inventory, Requests, Notifications | ✅ | ✅ | ✅ | ✅ | ✅ |
| Receiving, Honey QC, Production, Recipes | ✅ | ✅ | ✅ | — | — |
| Packing, Sales platforms, Orders, Deliveries | ✅ | ✅ | — | ✅ | — |
| Assets & maintenance | ✅ | ✅ | — | — | ✅ |
| Approvals, Reports, Analytics, Users | ✅ | ✅ | — | — | — |
| MySQL export | ✅ | — | — | — | — |

The last active Super Admin cannot be disabled or demoted, and only a Super
Admin can grant or remove Super Admin access.

---

## QR codes

Four kinds of code circulate, told apart by their prefix, and **all of them
are scanned on the same screen** (QR Scanner):

| Prefix | Points at |
|---|---|
| `RB-<n>` | a receiving cage box / crate |
| `HC-<n>` | a honey container |
| `PK-<n>` | a packing run |
| `PR-<a>-<b>` | an approved purchase-request item |

Scanning resolves the code, shows what it is and its current state, and links
straight to the record. Printable label sheets come from the receiving batch
screen and from Honey QC.

---

## Dates

Every transaction is stamped: receiving batches and boxes, QC checks,
packing runs and hand-overs, requests and decisions, maintenance, imports,
stock movements and adjustments. The inventory ledger records every movement
with its type (`received`, `qc_passed`, `consumed`, `produced`, `packed`,
`sold`, `returned`, `adjusted`), reference and user.

---

## Moving to MySQL

`db.SCHEMA` declares every collection as a real table — columns, SQL types,
primary and foreign keys — and marks which embedded lists (an order's items,
a run's packed products) become their own child tables. `mysql_export.py`
renders that declaration:

```bash
python mysql_export.py          # writes export/schema.sql + export/data.sql
```

or, as the Super Admin, download both from the **MySQL Export** screen. Then:

```bash
mysql -u root -p -e "CREATE DATABASE amamio_ims CHARACTER SET utf8mb4"
mysql -u root -p amamio_ims < schema.sql
mysql -u root -p amamio_ims < data.sql
```

The result is a normalised database with foreign keys and indexes, not a JSON
blob dump — 32 tables, created parents-first so the keys resolve on import.

---

## Where things live

| Area | Files |
|---|---|
| Receiving area | `receiving.py`, `templates/receiving/` |
| Honey QC | `honey.py`, `templates/honey/` |
| Packing | `packing.py`, `templates/packing/` |
| Sales platforms | `platforms.py`, `platform_service.py`, `xlsx.py` |
| Assets & maintenance | `assets.py`, `templates/assets/` |
| Requests & approvals | `requests_bp.py`, `approvals.py` |
| Production & recipes | `production.py`, `catalog.py` |
| Orders, payments, delivery | `orders.py`, `deliveries.py`, `customers.py` |
| Reports & analytics | `reports.py`, `analytics_bp.py`, `ai.py` |
| Users & access | `auth.py`, `security.py` |
| Storage & migration | `db.py`, `mysql_export.py`, `migration.py` |
| Business rules | `services.py` — all stock maths lives here, once |

`xlsx.py` is a dependency-free `.xlsx` reader built on the standard library,
so importing marketplace exports needs no pandas or openpyxl install.

## AI features (offline heuristics — `ai.py`)

1. **Demand forecasting** — weekly demand per product with 95% bands.
2. **Reorder recommendations** — projects consumption through the recipes.
3. **Production planning** — suggested build quantities from forecasts.
4. **Stockout & overstock prediction**.
5. **Sales trend analysis** — fast- vs. slow-moving products.
6. **Anomaly detection** — unusual adjustments or large movements.
7. **Assistant** — natural-language Q&A over live data.

## Testing

```bash
python smoke_test.py
```

Covers logins and role guards for all five roles, receiving with a damage
split, honey Pass/Failed routing, packing stock release, QR receive
idempotency, the mandatory request reason, production, orders and payment,
QR resolution and the MySQL export. It runs against a temp folder and never
touches `data/`.
