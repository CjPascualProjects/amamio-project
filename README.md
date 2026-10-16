# Amamio Farm Products — Inventory & Sales System

Follows every product through the production site, from the **receiving
area** through **inspection & cleaning**, **production**, **packing** and
**dispatch**, through to **sales on each platform**. At any moment it can say
how many items or kilos there are, how many were damaged or unusable, where
they are, and who handled them.

Built with **Flask** and **JSON-file storage** (one file per table under
`data/`). It needs no database server and no internet. The storage is
declared as a real relational schema and exports to MySQL with one command;
see [Moving to MySQL](#moving-to-mysql).

## Quick start

```bash
pip install -r requirements.txt
python run.py
```

Open <http://localhost:5000> and sign in with a demo account. Demo data is
created on first run. To start over, delete the `data/` folder.

### Demo logins (username / password)

| Role | Login | Does |
|------|-------|------|
| Super Admin | `superadmin` / `super123` | Everything, plus users, roles and the MySQL export |
| Admin | `admin` / `admin123` | Approvals, reports, oversight of every module |
| Receiving Team Head | `receiving` / `recv123` | Records deliveries, prints QR labels, logs honey containers |
| Production Team Head | `production` / `prod123` | Inspection & cleaning, honey QC, batch records, cleaning checks |
| Packing Team Head | `packing` / `pack123` | Packing & dispatch, sales uploads and reports |
| Packing Team Member | `packer1` / `member123` (also `packer2`) | Records packing, disbursement and courier hand-over |
| Assets Maintenance Head | `assets` / `assets123` | Equipment and supplies in/out, maintenance, sanitation, pest control |

**Change these passwords before real use** (Users → Reset password).

---

## How the screens work: one thing at a time

* **Home** shows only what *your* role does, as a few large task cards, each
  with a count when something is waiting, plus a short "Waiting for you"
  list.
* **Every transaction is a step-by-step flow.** Each screen asks one
  question, with *Back* and *Next*, and you check everything on a final
  screen before saving. A mistake is caught on the step where it happens.
* **Every record has its own page.** It shows where the record is in the
  flow and the *one* next action (e.g. "Inspect this box", "Disburse or hand
  to the courier").
* **Paper forms print as they look on paper.** Each of the client's paper
  forms has a printable copy, filled in from the system.
* The sidebar only lists what your role can open.
* **"About this page" notes (for demos):** every page opens with a short
  note on what it is for, who uses it, how it fits the flow, and which paper
  form it replaces. Fold a note with its arrow (remembered per page), or hide
  them all with *Hide these notes on every page*. Turn them back on from the
  sun / moon menu → *Page notes*. The wording lives in `page_notes.py`, and
  `smoke_test.py` fails if a page has no note.
* **Light or dark:** the sun / moon button in the top bar switches between
  *Light*, *Dark* and *Match my device*. The choice is saved per user, so it
  follows you to any computer or phone. Both themes come from the same
  colour tokens in `static/css/style.css` (`:root` for dark,
  `:root[data-theme="light"]` for light). Chart colours were checked for
  colour-blind separation on each theme's card colour.

---

## Module 1: Receiving area, then inspection & cleaning

**Part 1: receiving** (Receiving Team Head, *Receiving Area → Receive a
delivery*). The steps are: who delivered it → delivery documents (PO / DR
no.) → what arrived (each item, how much is in each box, how many boxes,
plus optional lot no., expiry, packaging condition and temperature) → check
and save.

* Items are counted the way they arrive: ginger by the kilo, lemon by the
  piece, bottles by the unit.
* Each box gets a **QR label**. The QR code carries the box code, item,
  quantity, lot, expiry, delivery reference, date and supplier, so anyone
  who scans it sees the details even without the system.
* Saving **notifies the production team** that boxes are waiting at the
  Receiving Area.
* Nothing joins stock yet.

**Part 2: inspection & cleaning** (*Inspection & Cleaning*, or scan the
box). The steps are: is this the right box? → clean the content → count what
you found → why (only asked when something was lost) → quality checks →
decision → check and save.

* *Count what you found* splits the box into **usable**, **can't be used**
  and **damaged**, with a live tally against the label.
* *Quality checks* are visual / organoleptic, COA / documents and sampling /
  test.
* The decision is **Accepted**, **Rejected** or **Hold**:
  * **Accepted:** only the *usable* quantity joins stock and the box moves to
    the Storage Area. "Can't be used" and "damaged" go to the damage ledger
    with their reasons.
  * **Rejected:** nothing joins stock.
  * **Hold:** pending a test, document or QA decision. Nothing moves until
    someone decides Accept or Reject on the box's page.

Each box keeps its location (Receiving → Storage → Production Area →
Consumed). **Receiving Area → Inspection report** prints the client's *Raw
Materials Receiving and Inspection Report* for any date range.

## Module 2: Honey

The steps are: *Log honey containers* (source, weight, number of containers)
→ print a QR label per container → *Check* (moisture % → appearance → PASS
or FAILED, with a suggestion from the 20% moisture guide; the checker
decides).

* **PASS** honey joins sellable honey stock.
* **FAILED** honey is never discarded. It is kept as *Honey for Processing*.
* Each container is then sent to products **by the kilo**, and PASS honey can
  only go to PASS products (likewise FAILED). The container shows what is
  left.

> The two product lists are **placeholders**: `HONEY_PASS_PRODUCTS` and
> `HONEY_FAIL_PRODUCTS` in `services.py`. Replace them with the client's real
> lists; nothing else needs to change.

## Module 3: Equipment & supplies, every IN and OUT

* **Equipment & Assets** is the client's *Inventory of Assets* (AFP-001 …,
  grouped by category). *Record IN / OUT* covers equipment borrowed, sent for
  repair, lent, disposed, returned, back from repair, or newly purchased.
  Each piece of equipment has its own maintenance log (the *Equipment
  Maintenance Log* form), and a printable register.
* **Supplies In / Out** covers raw materials, jars / bottles / packaging,
  production (cleaning) supplies and office supplies. Every IN and OUT records
  who, why and a reference, and moves stock through the ledger.
* **Month-end count** records the physical count per category. **Month-end
  report** prints the client's *Month End Report*: opening, IN, OUT, system
  closing, physical count and variance.

## Module 4: Packing & dispatch

The packing team (head and members) records each run with *Record packing*:
channel (VIP / Shopee / TikTok / Lazada / Walk-in) → who packed it → products
and quantities (plus any damaged while packing) → check and save. Saving
marks the run **packed** and takes the items out of finished-goods stock.

Each packed run then goes out in one of two ways:

* **Disbursed:** handed straight to the customer, VIP buyer, walk-in or
  another team (with who received it).
* **Delivered to logistics / courier:** courier, rider, tracking number and
  parcel count.

The *Packing & Dispatch* page totals **packed / disbursed / delivered to the
courier**, per channel, for today, this week, this month or all time. Only
the packing head or an admin can cancel a run.

## Module 5: Sales uploads & reports

**Upload sales file:** pick the platform → choose the exported file (Excel
or CSV) → **check the preview**, which shows how many lines are new, how
many were already uploaded, the order date range, and the first lines as
they will be saved → save.

* Built in: **Shopee** (orders export), **TikTok Shop** (settlement order
  details), **Lazada** (orders export) and **Shopify** (orders CSV). Any
  other marketplace is a column mapping, set up under *Uploads → Column
  templates*, not a code change.
* The system recognises a file by its columns and warns if the wrong
  platform was picked.
* **Re-uploading** a newer export of the same orders adds nothing twice and
  **updates** order statuses and amounts that changed.
* Orders are grouped as *Completed, In progress, Cancelled, Returned* or
  *Adjustment*. Only the first two count as sales. TikTok tax and fee lines
  are adjustments.
* Listing titles are matched to the catalog by keyword and size (e.g. "Honey
  Lemon Ginger Concentrate 300ml" becomes *Honey Lemon Ginger Concentrate
  300 mL*).

**Sales Reports** has one filter row (date range · daily / weekly / monthly /
yearly · platform) and five tabs:

| Tab | Shows |
|---|---|
| Overview | Net sales, orders, items sold, average order, cancelled/returned, a chart per period by platform, sales by platform, best-selling products |
| By period | The same numbers as a table, one row per day / week / month / year |
| Products | Every product sold, items and net sales, which platforms |
| Orders | Status breakdown, where buyers are, every line (search and filter) |
| Uploads | Every file uploaded; removing an upload removes its sales |

*Download for Excel* exports the period table as a CSV file.

> **Customer data stays out of git.** Marketplace exports (`sales-platform/`)
> and the sales imported from them (`data/platform_sales.json`,
> `data/platform_imports.json`) contain real buyer names, addresses and phone
> numbers, so `.gitignore` keeps them off GitHub. They live only on the
> computer running the system.

## The client's paper forms in the system

| Paper form | Where |
|---|---|
| Raw Materials Receiving and Inspection Report | Receiving Area → Inspection report |
| Batch Manufacturing Record | Production → Batch Records (dispensing & weighing, procedure, yield, QA disposition; an approved batch adds finished goods and uses up the dispensed materials) |
| Daily Production Report | Production → Daily Production Report (IN / OUT / BAL per product, by week or by day) |
| Retention Record | Production → Retention Samples |
| Inventory of Assets | Equipment & Assets → print |
| Equipment Maintenance Log | Equipment & Assets → an equipment item → maintenance log |
| Month End Report (raw, packaging, cleaning, office) | Supplies In / Out → Month-end report |
| General Cleaning & Sanitation Record | Cleaning & Sanitation (pre- and post-production, one area per step) |
| Pest Control Monitoring Record (QMS-PCMR) | Pest Control (monthly; skipped months are flagged) |
| Supplier Directory | Supplier Directory (by Raw / Production / Packing / Office) |

The demo data comes from these forms: the product list of the Daily
Production Report, the supplies on the month-end reports, the AFP asset
register and the supplier directory (`seed_catalog.py`). Prices, stock
levels and reorder levels are demo figures.

---

## QR codes

| Prefix | Points at |
|---|---|
| `RB-<n>` | a receiving box / crate |
| `HC-<n>` | a honey container |
| `PK-<n>` | a packing run |
| `PR-<a>-<b>` | an approved purchase-request item |

*Scan a QR code* takes a handheld scanner, typed input or (in Chrome on
Android) the phone camera. It finds the code anywhere in the scanned text,
shows what it is and where it is, and offers the next action as one
button.

## Notifications

The next team is told when work arrives: deliveries received (production),
inspections done (receiving), honey checked, packing runs sent out (packing
head), sales uploaded, sanitation repairs needed and pest activity (assets
head), and low supplies. Admins receive all of them.

---

## Roles

Access is per *module* and is declared once in `security.py`
(`PERMISSIONS`). The same declaration drives both the sidebar and the route
guards.

| Module | Super/Admin | Receiving | Production | Packing head | Packing member | Assets |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Home, QR scanner, stock on hand, notifications | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Receiving Area | ✅ | ✅ | — | — | — | — |
| Inspection & Cleaning, Honey | ✅ | ✅ | ✅ | — | — | — |
| Batch records, daily report, retention, recipes | ✅ | — | ✅ | — | — | — |
| Packing & Dispatch | ✅ | — | — | ✅ | ✅ | — |
| Sales uploads & reports, orders, deliveries | ✅ | — | — | ✅ | — | — |
| Equipment & Assets | ✅ | — | — | — | — | ✅ |
| Supplies In / Out | ✅ | ✅ | — | — | — | ✅ |
| Cleaning & Sanitation, Pest Control | ✅ | — | ✅ | — | — | ✅ |
| Supplier Directory | ✅ | ✅ | ✅ | — | — | ✅ |
| Requests | ✅ | ✅ | ✅ | ✅ | — | ✅ |
| Approvals, Reports, Analytics, Users | ✅ | — | — | — | — | — |
| MySQL export | Super Admin only | | | | | |

---

## Moving to MySQL

`db.SCHEMA` declares every collection as a table, with columns, SQL types,
and primary and foreign keys. Embedded lists (a run's items, a batch
record's dispensing lines, a sanitation record's areas) become child tables.

```bash
python mysql_export.py          # writes export/schema.sql + export/data.sql
mysql -u root -p -e "CREATE DATABASE amamio_ims CHARACTER SET utf8mb4"
mysql -u root -p amamio_ims < export/schema.sql
mysql -u root -p amamio_ims < export/data.sql
```

The Super Admin can also download both files from the **MySQL Export**
screen.

## Where things live

| Area | Files |
|---|---|
| Home screen | `home.py`, `templates/dashboard.html` |
| Module 1 — receiving, inspection | `receiving.py`, `templates/receiving/` |
| Module 2 — honey | `honey.py`, `templates/honey/` |
| Module 3 — equipment, supplies | `assets.py`, `supplies.py`, `assets_service.py`, `templates/assets/`, `templates/supplies/` |
| Module 4 — packing & dispatch | `packing.py`, `templates/packing/` |
| Module 5 — sales uploads & reports | `platforms.py`, `platform_service.py`, `charts.py`, `xlsx.py` |
| Production records | `production.py`, `production_service.py`, `templates/production/` |
| Sanitation, pest control | `facility.py`, `facility_service.py`, `templates/facility/` |
| Supplier directory | `suppliers.py`, `templates/suppliers/` |
| Business rules (stock, receiving, honey, packing) | `services.py`: all stock changes go through `adjust_stock` |
| Step-by-step flows, shared UI | `static/js/app.js` (wizard, tooltips), `static/css/flow.css` |
| Printable paper forms | `templates/_paper.html` |
| Users & access | `auth.py`, `security.py` |
| Storage & migration | `db.py`, `mysql_export.py` |
| Demo data | `seed.py`, `seed_catalog.py` |

`xlsx.py` reads `.xlsx` and `.csv` with the standard library only, so
importing marketplace exports needs no pandas or openpyxl.

## Testing

```bash
python smoke_test.py
```

The smoke test runs against a throwaway folder and never touches `data/`.
It covers:

* every login and the role guards;
* receiving → inspection with usable / can't use / damaged, Hold and its
  decision, and QR label contents;
* honey PASS/FAILED routing and allocation by kg;
* packing → disbursed or handed to the courier;
* sales upload, preview and re-upload, the Shopee per-line amount, TikTok
  adjustments, a Shopify CSV, and the CSV export;
* approvals and QR receive, orders and payment;
* the MySQL export.
