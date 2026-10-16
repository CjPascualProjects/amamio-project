"""'About this page' notes shown at the top of each screen (for demos).

One entry per page (Flask endpoint):
    what  — what the page is for, in one or two sentences
    who   — the roles that use it
    flow  — where it sits in the flow: what comes before / what happens next
    form  — the client's paper form this page replaces or prints (optional)

Users switch the notes off in the topbar menu (sun / moon → Page notes).
Edit the wording here; nothing else needs to change.
"""

ADMINS = "Super Admin, Admin"

NOTES = {
    # --- Start ------------------------------------------------------------
    "auth.dashboard": {
        "title": "Home",
        "what": "Your starting point. It shows only the few jobs your role does, as big cards — a number on a card means something is waiting — and a short list of what needs your attention.",
        "who": "Everyone (each role sees its own cards)",
        "flow": "Tap a card to start a job. Every job is a short step-by-step form: one question per screen, then a check screen before saving.",
    },
    "qr.scan": {
        "title": "Scan a QR code",
        "what": "Scan the QR label on a box, honey container or packing run (or type its code) to see what it is, where it is now, and the one thing to do next.",
        "who": "Everyone on the floor",
        "flow": "RB- = receiving box · HC- = honey container · PK- = packing run · PR- = purchased item. A handheld scanner or phone camera both work.",
    },
    "notifications.index": {
        "title": "Notifications",
        "what": "Messages the system sends when work arrives for you — e.g. a delivery received at the Receiving Area, a box inspected, honey checked, parcels handed to the courier.",
        "who": "Everyone",
        "flow": "Click a notification to open the record it is about.",
    },

    # --- Module 1: receiving & inspection ------------------------------------
    "receiving.index": {
        "title": "Receiving Area — Module 1, part 1",
        "what": "Every delivery that arrives at the production site (lemon, ginger, bottles…). Open deliveries still have boxes waiting for inspection.",
        "who": "Receiving Team Head (recording) · " + ADMINS,
        "flow": "Receive a delivery → print a QR label per box → the production team is notified → each box is inspected & cleaned (part 2).",
    },
    "receiving.new": {
        "title": "Receive a delivery",
        "what": "Record one delivery: who delivered it, the PO / DR numbers, and what arrived — each item, how much is in each box (kg, pieces or units) and how many boxes.",
        "who": "Receiving Team Head",
        "flow": "Saving creates one QR label per box (code, item, quantity, lot, expiry, supplier) and notifies the production team. Nothing joins stock yet — that happens after inspection.",
        "form": "Raw Materials Receiving and Inspection Report (receiving columns)",
    },
    "receiving.batch": {
        "title": "One delivery",
        "what": "The boxes of one delivery and where each one stands: waiting for inspection, accepted, on hold or rejected — with the usable, can't-be-used and damaged totals.",
        "who": "Receiving Team Head · " + ADMINS,
        "flow": "Print the QR labels, then the boxes are inspected one by one. The delivery completes itself when every box has a decision.",
    },
    "receiving.labels": {
        "title": "QR labels",
        "what": "Printable labels, one per box. Each QR code carries the box code plus the item, quantity, lot, expiry, delivery number, date and supplier.",
        "who": "Receiving Team Head",
        "flow": "Stick one label on each box. Anyone who scans it sees the details and the next step.",
    },
    "receiving.add_boxes": {
        "title": "Add a box that was missed",
        "what": "Add another box to a delivery that is still open. It gets its own QR label.",
        "who": "Receiving Team Head",
        "flow": "After saving, its label is ready to print.",
    },
    "receiving.box": {
        "title": "One box",
        "what": "Everything about one box: what is in it, where it is now (Receiving → Storage → Production Area → Consumed), and its inspection result.",
        "who": "Receiving Team Head · Production Team Head · " + ADMINS,
        "flow": "The highlighted panel shows the next action — inspect it, decide a box on hold, or move it to the next area.",
    },
    "receiving.inspection": {
        "title": "Inspection & Cleaning — Module 1, part 2",
        "what": "Boxes that arrived and are waiting to be cleaned and checked, boxes on hold, and the most recent inspections.",
        "who": "Production Team Head · Receiving Team Head · " + ADMINS,
        "flow": "Open a box (or scan its label) to inspect it. You are notified whenever new boxes arrive.",
    },
    "receiving.inspect": {
        "title": "Inspect & clean a box",
        "what": "Clean the content, then split it into usable / can't be used / damaged, record the quality checks, and decide: Accepted, Rejected or Hold.",
        "who": "Production Team Head · Receiving Team Head",
        "flow": "Accepted: only the usable quantity joins stock and the box moves to the Storage Area; the rest goes to the damage report with its reason. Hold: nothing moves until a test, document or QA decision.",
        "form": "Raw Materials Receiving and Inspection Report (inspection columns)",
    },
    "receiving.report": {
        "title": "Receiving & Inspection Report",
        "what": "The client's paper report, filled in automatically from the deliveries and inspections in the chosen date range.",
        "who": "Receiving Team Head · Production Team Head · " + ADMINS,
        "flow": "Pick the dates and print. Prepared by / Checked by / Approved by are signed on paper.",
        "form": "Raw Materials Receiving and Inspection Report",
    },
    "receiving.damage": {
        "title": "Damage & losses",
        "what": "Everything that did not join stock — can't be used, damaged on receipt, damaged while packing — with the reason, where it happened and who recorded it.",
        "who": "Receiving & Production Team Heads · " + ADMINS,
        "flow": "Rows are added automatically by inspection and packing.",
    },

    # --- Module 2: honey -----------------------------------------------------
    "honey.index": {
        "title": "Honey Containers — Module 2",
        "what": "Every honey container, its QR code and its moisture / appearance result: PASS or FAILED.",
        "who": "Receiving Team Head (logging) · Production Team Head (checking) · " + ADMINS,
        "flow": "Log containers → print labels → check moisture & appearance → PASS honey goes to selling products, FAILED honey to the products that can still use it.",
    },
    "honey.new": {
        "title": "Log honey containers",
        "what": "Record honey that arrived: where it came from, the net weight per container and how many containers.",
        "who": "Receiving Team Head · Production Team Head",
        "flow": "Each container gets a QR label and the production team is notified to check it.",
    },
    "honey.qc": {
        "title": "Check a honey container",
        "what": "Enter the moisture reading and the appearance, then decide PASS or FAILED. The system suggests a result (above 20% moisture usually fails) but you decide.",
        "who": "Production Team Head",
        "flow": "PASS joins sellable honey stock. FAILED is never thrown away — it is kept as 'Honey for Processing' for other products.",
    },
    "honey.container": {
        "title": "One honey container",
        "what": "Its QC result and where its honey went, kilo by kilo.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Record which product the honey was used in. PASS honey can only go to PASS products, FAILED honey only to FAILED products. (The product lists are placeholders for now.)",
    },
    "honey.labels": {
        "title": "Honey QR labels",
        "what": "Printable labels for honey containers — code, weight, batch and source.",
        "who": "Receiving Team Head · Production Team Head",
        "flow": "Stick one on each container before it is checked.",
    },

    # --- Production records ---------------------------------------------------
    "production.index": {
        "title": "Batch Records",
        "what": "Every production batch, from dispensing and weighing to the QA's final decision.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Start a batch → sign off dispensing & weighing → tick off each procedure step → record yield and APPROVED / DISAPPROVED.",
        "form": "Batch Manufacturing Record",
    },
    "production.start": {
        "title": "Start a batch",
        "what": "Choose the product and batch size. The ingredients are filled in from the recipe × batch size, and the procedure steps from the product's usual process — both can be edited.",
        "who": "Production Team Head",
        "flow": "After saving, the batch page guides you one step at a time.",
        "form": "Batch Manufacturing Record (page 1)",
    },
    "production.batch": {
        "title": "One batch",
        "what": "The batch's progress and its one next step: dispensing, the current procedure step, or yield & QA.",
        "who": "Production Team Head",
        "flow": "When the QA approves, the finished goods are added to stock and the dispensed ingredients are taken out — exactly once.",
        "form": "Batch Manufacturing Record",
    },
    "production.dispensing": {
        "title": "Dispensing & weighing",
        "what": "Confirm who weighed out each ingredient and who checked it.",
        "who": "Production Team Head",
        "flow": "Next: the procedure steps.",
        "form": "Batch Manufacturing Record — Dispensing and Weighing",
    },
    "production.finish": {
        "title": "Yield & QA",
        "what": "Record the end time, the actual yield, the test dates and the QA's final disposition: APPROVED or DISAPPROVED.",
        "who": "Production Team Head · QA",
        "flow": "APPROVED adds the yield to finished-goods stock. DISAPPROVED still uses up the ingredients but adds nothing.",
        "form": "Batch Manufacturing Record (page 2)",
    },
    "production.batch_print": {
        "title": "Batch Manufacturing Record (print)",
        "what": "The client's paper BMR, filled in from this batch.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Print and file with the batch.",
        "form": "Batch Manufacturing Record",
    },
    "production.daily_report": {
        "title": "Daily Production Report",
        "what": "For each product and size: the balance brought forward, what came IN (produced, returned) and went OUT (packed, sold), and the running balance — by week or by day.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Built automatically from every stock movement. Pick a month and print.",
        "form": "Daily Production Report",
    },
    "production.retention": {
        "title": "Retention Samples",
        "what": "Samples kept from each batch, until their disposal date.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Keep a sample after a batch → dispose of it when it expires (samples due are flagged).",
        "form": "Retention Record",
    },
    "production.retention_new": {
        "title": "Keep a retention sample",
        "what": "Record a sample kept from a batch: product, dates, quantity, who inspected and approved it.",
        "who": "Production Team Head",
        "flow": "It appears on the Retention Record until it is disposed of.",
        "form": "Retention Record",
    },
    "production.retention_dispose": {
        "title": "Dispose of a sample",
        "what": "Record the disposal date and remarks for a retention sample.",
        "who": "Production Team Head",
        "flow": "The sample moves to Disposed.",
        "form": "Retention Record",
    },
    "production.retention_print": {
        "title": "Retention Record (print)",
        "what": "The client's paper Retention Record for the chosen dates.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Print and sign.",
        "form": "Retention Record",
    },
    "catalog.index": {
        "title": "Products & Recipes",
        "what": "The finished products (from the Daily Production Report) and the recipe — materials per unit — for each one.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Recipes fill in a batch's ingredients automatically.",
    },
    "catalog.materials": {
        "title": "Materials",
        "what": "Raw materials and supplies with their unit, how they are counted, stock and reorder level.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Stock normally changes through receiving, supplies in/out and production. Correcting a stock figure here is logged as an adjustment, with who and when.",
    },
    "catalog.product_bom": {
        "title": "Recipe",
        "what": "How much of each material one unit of this product needs.",
        "who": "Production Team Head · " + ADMINS,
        "flow": "Used to fill in batch records and production requests.",
    },
    "inventory.index": {
        "title": "Stock on Hand",
        "what": "Current stock of every finished product and material, with low-stock flags.",
        "who": "Everyone (view only)",
        "flow": "Open the movements history to see every IN and OUT behind a number.",
    },
    "inventory.transactions": {
        "title": "Stock movements",
        "what": "The ledger: every change to stock, with its type (received, produced, packed, sold, adjusted…), reference, user and time.",
        "who": "Everyone (view only)",
        "flow": "Nothing changes stock without a line here.",
    },

    # --- Module 4: packing ----------------------------------------------------
    "packing.index": {
        "title": "Packing & Dispatch — Module 4",
        "what": "How many items were packed, disbursed, and delivered to the logistics / courier — per channel, for today, this week, this month or all time.",
        "who": "Packing Team Head · Packing Team Members · " + ADMINS,
        "flow": "Record packing → the run is packed (stock goes out) → disburse it, or hand it to the courier.",
    },
    "packing.new": {
        "title": "Record packing",
        "what": "Record one packing run: the channel (VIP, Shopee, TikTok, Lazada, Walk-in), who packed it, the products and quantities, and any damaged while packing.",
        "who": "Packing Team Head · Packing Team Members",
        "flow": "Saving marks the run packed and takes the items out of finished-goods stock. Next: send it out.",
    },
    "packing.detail": {
        "title": "One packing run",
        "what": "What was packed, by whom, and where it went.",
        "who": "Packing Team Head · Packing Team Members · " + ADMINS,
        "flow": "The highlighted panel shows the next step. Only the packing head or an admin can cancel a run.",
    },
    "packing.dispatch": {
        "title": "Disburse or hand to courier",
        "what": "Record where the packed parcels went: disbursed straight to the customer / VIP / walk-in / another team, or delivered to the logistics / courier with the tracking number.",
        "who": "Packing Team Head · Packing Team Members",
        "flow": "This completes the run; the packing head is notified.",
    },
    "packing.history": {
        "title": "All packing runs",
        "what": "The full record of every packing run, filterable by channel and status, plus totals per packer.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Open a run to see its details.",
    },
    "packing.slip": {
        "title": "Packing slip",
        "what": "A printable slip for the parcels: products, quantities, QR code, and lines to sign.",
        "who": "Packing Team",
        "flow": "Print and send with the parcels.",
    },

    # --- Module 5: sales -------------------------------------------------------
    "platforms.index": {
        "title": "Sales Reports — Module 5",
        "what": "What sold, on which platform, and when — from the files exported from Shopee, TikTok, Lazada, Shopify and others. Switch between daily, weekly, monthly and yearly.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Upload a sales file → the reports update. Cancelled, returned and platform fee/tax lines are not counted as sales. 'Download for Excel' exports the numbers.",
    },
    "platforms.upload": {
        "title": "Upload sales file",
        "what": "Pick the platform and choose the file exactly as the platform exported it (Excel or CSV).",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Next you see a preview before anything is saved.",
    },
    "platforms.preview": {
        "title": "Check before saving",
        "what": "What this file will add: new lines, lines already uploaded, the order dates, totals, and the first lines as they will be saved. The system recognises the platform by the file's columns.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Uploading a newer export of the same orders never counts them twice — it updates their status and amounts.",
    },
    "platforms.upload_detail": {
        "title": "One upload",
        "what": "What one uploaded file added to the sales records.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Removing an upload removes the sales lines it added.",
    },
    "platforms.template_list": {
        "title": "Column templates (advanced)",
        "what": "How each platform's export columns map onto the system's fields. A new marketplace is a new template here, not a code change.",
        "who": ADMINS,
        "flow": "Shopee, TikTok, Lazada and Shopify are built in.",
    },
    "orders.index": {
        "title": "Sales Orders",
        "what": "Orders taken directly from customers (e.g. VIP buyers), with payment and delivery status.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "New order → confirm (stock goes out) → record payments → delivery.",
    },
    "orders.new": {
        "title": "New sales order",
        "what": "Create an order for a customer: products, quantities and prices.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Confirming the order takes the items out of stock.",
    },
    "orders.detail": {
        "title": "One sales order",
        "what": "The order, its payments, delivery and any returns.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Confirm → pay → deliver.",
    },
    "sales.index": {
        "title": "Stock Release",
        "what": "Requests from packing for finished goods, approved by an admin and fulfilled by production.",
        "who": "Packing Team Head · Production Team Head · " + ADMINS,
        "flow": "Request → approve → fulfil.",
    },
    "sales.new": {
        "title": "Request stock",
        "what": "Ask for finished goods to be released for a channel.",
        "who": "Packing Team Head",
        "flow": "An admin approves it, then production fulfils it.",
    },
    "deliveries.index": {
        "title": "Deliveries",
        "what": "Deliveries of sales orders: scheduled, in transit, delivered or returned.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Update the status as the delivery moves.",
    },
    "customers.index": {
        "title": "Customers",
        "what": "The customers who buy directly (VIP, walk-in) and their order history.",
        "who": "Packing Team Head · " + ADMINS,
        "flow": "Used when creating sales orders.",
    },

    # --- Module 3: equipment & supplies ------------------------------------------
    "assets.index": {
        "title": "Equipment & Assets — Module 3",
        "what": "Every item on the Inventory of Assets (AFP-001 …), how many are on site, how many are out, its condition, and maintenance falling due.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Record IN / OUT whenever equipment leaves or comes back. Open an item for its maintenance log.",
        "form": "Inventory of Assets",
    },
    "assets.move": {
        "title": "Record equipment IN / OUT",
        "what": "Record equipment going out (borrowed, sent for repair, lent, disposed) or coming in (returned, back from repair, newly purchased) — with who, where and when it is expected back.",
        "who": "Assets Maintenance Head",
        "flow": "Every movement is logged; admins are notified when equipment goes out.",
    },
    "assets.detail": {
        "title": "One equipment item",
        "what": "Its details (serial, model, manufacturer, location), how many are out, its movements and its maintenance history.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Record IN / OUT, log maintenance, or print its Equipment Maintenance Log.",
        "form": "Equipment Maintenance Log (header)",
    },
    "assets.new": {
        "title": "Add equipment",
        "what": "Add an item to the asset register. It gets the next AFP number.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "It appears on the Inventory of Assets.",
        "form": "Inventory of Assets",
    },
    "assets.edit": {
        "title": "Edit equipment",
        "what": "Correct an item's details.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Quantities change through IN / OUT, not here.",
    },
    "assets.maintenance": {
        "title": "Log maintenance",
        "what": "Record service done on equipment: date, time, what was done, by whom, cost, downtime and the next maintenance date.",
        "who": "Assets Maintenance Head",
        "flow": "The next date becomes a reminder on the home page.",
        "form": "Equipment Maintenance Log",
    },
    "assets.movements": {
        "title": "Every equipment IN / OUT",
        "what": "The full history of equipment going out and coming back.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Newest first.",
    },
    "assets.inventory_print": {
        "title": "Inventory of Assets (print)",
        "what": "The client's paper asset register, grouped by category.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Print for audits.",
        "form": "Inventory of Assets",
    },
    "assets.maintenance_print": {
        "title": "Equipment Maintenance Log (print)",
        "what": "The client's paper maintenance log for one item.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Print and keep with the equipment.",
        "form": "Equipment Maintenance Log",
    },
    "supplies.index": {
        "title": "Supplies In / Out — Module 3",
        "what": "Raw materials, jars / bottles / packaging, production (cleaning) supplies and office supplies — what is on hand and what is low.",
        "who": "Assets Maintenance Head · Receiving Team Head · " + ADMINS,
        "flow": "Record every IN and OUT. At month end, count what is physically there.",
    },
    "supplies.move": {
        "title": "Record supplies IN / OUT",
        "what": "Record supplies taken in or issued out: how much, why, to or from whom, and a reference.",
        "who": "Assets Maintenance Head · Receiving Team Head",
        "flow": "Stock updates at once; an OUT can never exceed what is on hand. Admins are notified when an item runs low.",
    },
    "supplies.item": {
        "title": "One supply item",
        "what": "Its stock, reorder level and every IN / OUT.",
        "who": "Assets Maintenance Head · Receiving Team Head · " + ADMINS,
        "flow": "Record an IN or OUT from here.",
    },
    "supplies.movements": {
        "title": "Every supplies IN / OUT",
        "what": "The full history of supplies taken in and issued out.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Newest first.",
    },
    "supplies.count": {
        "title": "Month-end count",
        "what": "Enter the physical count of each item in a category for the month.",
        "who": "Assets Maintenance Head",
        "flow": "Differences from the system show as variance; for the current month you can adjust stock to the count.",
        "form": "Month End Report (physical inventory column)",
    },
    "supplies.report": {
        "title": "Month-End Report",
        "what": "Per category and month: opening, IN, OUT, closing, the physical count and the variance.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Print for the month-end file.",
        "form": "Month End Report (Raw Materials / Packaging / Production Supplies / Office Supplies)",
    },

    # --- Facility ------------------------------------------------------------------
    "facility.sanitation": {
        "title": "Cleaning & Sanitation",
        "what": "The before- and after-production cleaning check of each area: Locker Room, Storage, Washing, Production and Finished Products.",
        "who": "Assets Maintenance Head · Production Team Head · " + ADMINS,
        "flow": "Record each check → areas that need cleaning or repair stay open until marked done.",
        "form": "General Cleaning & Sanitation Record",
    },
    "facility.sanitation_new": {
        "title": "Record cleaning",
        "what": "Check each area one at a time: its current status and, if needed, the action to undertake.",
        "who": "Assets Maintenance Head · Production Team Head",
        "flow": "Areas needing repair notify the admins and the assets head.",
        "form": "General Cleaning & Sanitation Record",
    },
    "facility.sanitation_record": {
        "title": "One cleaning check",
        "what": "The result for each area, and any action still open.",
        "who": "Assets Maintenance Head · Production Team Head",
        "flow": "Mark an action done once it has been undertaken.",
        "form": "General Cleaning & Sanitation Record",
    },
    "facility.sanitation_print": {
        "title": "Cleaning & Sanitation Record (print)",
        "what": "The client's paper record for the chosen dates.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Print and file.",
        "form": "General Cleaning & Sanitation Record",
    },
    "facility.pest": {
        "title": "Pest Control",
        "what": "The monthly pest inspection of every area. The strip of months shows at a glance if a month was missed.",
        "who": "Assets Maintenance Head · Production Team Head · " + ADMINS,
        "flow": "Record this month's inspection → pest activity notifies the admins.",
        "form": "Pest Control Monitoring Record (QMS-PCMR)",
    },
    "facility.pest_new": {
        "title": "Record pest inspection",
        "what": "For each area: was pest activity seen, what was observed, and the corrective action taken.",
        "who": "Assets Maintenance Head · Production Team Head",
        "flow": "The name of the person monitoring acts as the signature.",
        "form": "Pest Control Monitoring Record (QMS-PCMR)",
    },
    "facility.pest_record": {
        "title": "One pest inspection",
        "what": "The month's findings for each area.",
        "who": "Assets Maintenance Head · Production Team Head",
        "flow": "Print it from the Pest Control page.",
        "form": "Pest Control Monitoring Record (QMS-PCMR)",
    },
    "facility.pest_print": {
        "title": "Pest Control Monitoring Record (print)",
        "what": "The client's paper record (QMS-PCMR, Rev. 01) for the chosen months.",
        "who": "Assets Maintenance Head · " + ADMINS,
        "flow": "Print and sign.",
        "form": "Pest Control Monitoring Record (QMS-PCMR)",
    },
    "suppliers.index": {
        "title": "Supplier Directory",
        "what": "Every supplier — raw materials, production, packing and office — with TIN, items and where to buy.",
        "who": "Receiving, Production & Assets Heads · " + ADMINS,
        "flow": "Suppliers are picked when receiving a delivery.",
        "form": "Supplier Directory",
    },
    "suppliers.new": {
        "title": "Add supplier",
        "what": "Add a supplier: category, items supplied, TIN and contact.",
        "who": "Receiving, Production & Assets Heads · " + ADMINS,
        "flow": "It appears in the directory and when receiving deliveries.",
        "form": "Supplier Directory",
    },
    "suppliers.detail": {
        "title": "One supplier",
        "what": "The supplier's details.",
        "who": "Receiving, Production & Assets Heads · " + ADMINS,
        "flow": "Edit to correct details.",
    },
    "suppliers.edit": {
        "title": "Edit supplier",
        "what": "Correct a supplier's details.",
        "who": "Receiving, Production & Assets Heads · " + ADMINS,
        "flow": "Changes show everywhere the supplier is used.",
    },
    "suppliers.print_directory": {
        "title": "Supplier Directory (print)",
        "what": "The client's paper directory, grouped by category.",
        "who": "Receiving, Production & Assets Heads · " + ADMINS,
        "flow": "Print for the office.",
        "form": "Supplier Directory",
    },

    # --- Management -----------------------------------------------------------------
    "requests.index": {
        "title": "Requests",
        "what": "Requests to the admin to buy materials, supplies or equipment — each with a reason, urgency and needed-by date.",
        "who": "Team Heads (their own) · " + ADMINS + " (all)",
        "flow": "Request → admin approves → items arrive and are received by QR.",
    },
    "requests.new_production": {
        "title": "Request materials for production",
        "what": "Ask for the materials a production run is short of, worked out from the recipe.",
        "who": "Production Team Head",
        "flow": "A reason is required. The admin is notified.",
    },
    "requests.new_material": {
        "title": "Request supplies or equipment",
        "what": "Ask for supplies or equipment, with a reason and urgency.",
        "who": "Team Heads",
        "flow": "A reason is required. The admin is notified.",
    },
    "requests.detail": {
        "title": "One request",
        "what": "The request, the admin's decision, and what has been received so far.",
        "who": "The requester · " + ADMINS,
        "flow": "Approved items get QR codes to receive them by scanning.",
    },
    "approvals.index": {
        "title": "Approvals",
        "what": "Purchase and stock-release requests waiting for an admin's decision.",
        "who": ADMINS,
        "flow": "Open one to approve, revise quantities or reject.",
    },
    "approvals.decide": {
        "title": "Decide a request",
        "what": "Approve, revise or reject each item, with remarks.",
        "who": ADMINS,
        "flow": "The requester is notified; approved items get QR codes.",
    },
    "qr.print_codes": {
        "title": "Purchase QR codes",
        "what": "QR codes for approved purchase items, so they can be received by scanning.",
        "who": ADMINS + " · Team Heads",
        "flow": "Scanning one on arrival adds the item to stock (once).",
    },
    "reports.index": {
        "title": "Reports",
        "what": "One page of reports across the business: stock, receiving and damage, honey QC, packing, platform sales, maintenance and AI recommendations.",
        "who": ADMINS,
        "flow": "Use the links at the top to jump to a section.",
    },
    "analytics.index": {
        "title": "Analytics",
        "what": "Charts of demand, production and stock movement over time.",
        "who": ADMINS,
        "flow": "See Forecast for the next weeks' expected demand.",
    },
    "analytics.forecast": {
        "title": "Forecast",
        "what": "Expected demand per product for the coming weeks, with a likely range, worked out offline from past demand.",
        "who": ADMINS,
        "flow": "Use it to plan batches and purchase requests.",
    },
    "auth.users": {
        "title": "Users",
        "what": "Everyone who can sign in, their role, and whether they are active.",
        "who": ADMINS,
        "flow": "The role decides which pages a person sees.",
    },
    "migration.index": {
        "title": "MySQL Export",
        "what": "Download the whole database as MySQL files (schema + data), ready for a MySQL server.",
        "who": "Super Admin",
        "flow": "Run the two files on the server, in order.",
    },
}


def for_endpoint(endpoint):
    return NOTES.get(endpoint or "")
