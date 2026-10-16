"""Amamio's master data, transcribed from the client's paper forms.

* PRODUCTS      — the Daily Production Report (product families and sizes)
* MATERIALS     — the four month-end reports (raw materials; jars, bottles &
                  packaging; production / cleaning supplies; office supplies)
* ASSETS        — the Inventory of Assets (AFP-001 …)
* SUPPLIERS     — the Supplier Directory (office / production / packing)

Kept apart from ``seed.py`` so the lists are easy to correct.  Prices, stock
levels and reorder levels are demo figures, not the client's numbers.
"""

# --- Finished products (Daily Production Report) ---------------------------
# (group, family, [(variant, unit, sku, price), ...])
PRODUCTS = [
    ("Honey Products", "Pure Honey", [
        ("100 mL", "bottle", "PH-100", 189.0),
        ("250 mL", "bottle", "PH-250", 399.0),
        ("500 mL", "bottle", "PH-500", 699.0),
        ("1 Liter", "bottle", "PH-1L", 1104.0),
        ("3.7 Liter", "gallon", "PH-3.7L", 3900.0),
        ("1 container", "container", "PH-CTR", 0.0),
    ]),
    ("Honey Products", "RFH with Comb", [
        ("250 mL", "jar", "RFH-250", 499.0),
        ("500 mL", "jar", "RFH-500", 899.0),
    ]),
    ("Honey Products", "Honey Lemon Ginger Concentrate", [
        ("300 mL", "bottle", "HLGC-300", 487.0),
        ("1 Liter", "bottle", "HLGC-1L", 1350.0),
    ]),
    ("Honey Products", "Honey Calamansi Concentrate", [
        ("300 mL", "bottle", "HCC-300", 450.0),
        ("1 Liter", "bottle", "HCC-1L", 1250.0),
    ]),
    ("Honey Products", "Honey Infused Turmeric Ginger", [
        ("300 mL", "bottle", "HITG-300", 420.0),
        ("1 Liter", "bottle", "HITG-1L", 1180.0),
    ]),
    ("Honey Products", "Honey Infused Ginger", [
        ("300 mL", "bottle", "HIG-300", 399.0),
        ("1 Liter", "bottle", "HIG-1L", 1120.0),
    ]),
    ("Honey Products", "Honey Vinegar", [
        ("250 mL", "bottle", "HV-250", 260.0),
    ]),
    ("Cacao Products", "Pure Tableya", [
        ("200 g", "pack", "TAB-200", 180.0),
        ("1 kg", "pack", "TAB-1K", 780.0),
    ]),
    ("Cacao Products", "Cacao Nibs", [
        ("100 g", "pouch", "NIB-100", 150.0),
        ("500 g", "pouch", "NIB-500", 650.0),
    ]),
    ("Cacao Products", "Cacao Powder", [
        ("100 g", "pouch", "CP-100", 140.0),
        ("500 g", "pouch", "CP-500", 600.0),
    ]),
    ("Coffee Products", "Pure Corn Coffee", [
        ("150 g", "pouch", "CC-150", 120.0),
        ("1 kg", "pouch", "CC-1K", 650.0),
    ]),
    ("Coffee Products", "Robusta Coffee", [
        ("125 g", "pouch", "RC-125", 160.0),
        ("1 kg", "pouch", "RC-1K", 980.0),
    ]),
    ("Powder", "Moringa Powder", [
        ("100 g", "pouch", "MP-100", 150.0),
        ("500 g", "pouch", "MP-500", 620.0),
        ("1 kg", "pouch", "MP-1K", 1150.0),
    ]),
    ("Powder", "Turmeric Powder", [
        ("100 g", "pouch", "TP-100", 140.0),
    ]),
    ("Powder", "Banana Chips", [
        ("100 g", "jar", "BC-100", 95.0),
    ]),
    ("Powder", "Uriel Liniment Oil", [
        ("60 mL", "bottle", "ULO-60", 120.0),
    ]),
    ("Others", "Calamansi Powder", [("", "pouch", "OTH-CALP", 150.0)]),
    ("Others", "Cacao Butter", [("", "jar", "OTH-CBTR", 350.0)]),
    ("Others", "Lip Moisturizer", [("", "tube", "OTH-LIP", 85.0)]),
    ("Others", "Lemon Powder", [("", "pouch", "OTH-LEMP", 150.0)]),
    ("Others", "Ginger Powder", [("", "pouch", "OTH-GINP", 150.0)]),
]


# --- Stocked materials (month-end reports) ----------------------------------
# (category, subcategory, name, unit, track_mode, stock, reorder, unit_cost)
MATERIALS = [
    # Raw materials
    ("raw", "Raw materials", "Raw Honey", "kg", "weight", 68.0, 25, 420.0),
    ("raw", "Raw materials", "Lemon", "pc", "piece", 640.0, 250, 12.0),
    ("raw", "Raw materials", "Ginger", "kg", "weight", 42.0, 20, 95.0),
    ("raw", "Raw materials", "Turmeric", "kg", "weight", 18.0, 10, 120.0),
    ("raw", "Raw materials", "Calamansi", "kg", "weight", 12.0, 8, 80.0),
    ("raw", "Raw materials", "Cacao Beans", "kg", "weight", 35.0, 15, 260.0),
    ("raw", "Raw materials", "Moringa", "kg", "weight", 9.0, 5, 150.0),
    ("raw", "Raw materials", "Honey Comb", "kg", "weight", 6.0, 3, 600.0),
    ("raw", "Raw materials", "Vinegar", "L", "unit", 20.0, 8, 90.0),
    ("raw", "Raw materials", "Liniment Oil", "L", "unit", 4.0, 2, 450.0),
    ("raw", "Raw materials", "Robusta Coffee", "kg", "weight", 22.0, 10, 330.0),
    ("raw", "Raw materials", "Banana Chips", "kg", "weight", 15.0, 6, 140.0),
    # Jars / bottles
    ("packaging", "Jars / Bottles", "Hexagonal Jar 100 mL", "pc", "piece", 320.0, 100, 9.0),
    ("packaging", "Jars / Bottles", "Square Jar 200 mL", "pc", "piece", 240.0, 100, 11.0),
    ("packaging", "Jars / Bottles", "Round Jar 240 mL", "pc", "piece", 180.0, 80, 11.0),
    ("packaging", "Jars / Bottles", "Hexagonal Jar 250 mL", "pc", "piece", 360.0, 120, 12.0),
    ("packaging", "Jars / Bottles", "Square Bottle 300 mL", "pc", "piece", 420.0, 150, 10.0),
    ("packaging", "Jars / Bottles", "Hexagonal Jar 500 mL", "pc", "piece", 150.0, 60, 16.0),
    ("packaging", "Jars / Bottles", "Round Bottle 1 Liter", "pc", "piece", 90.0, 40, 24.0),
    ("packaging", "Jars / Bottles", "Empty Gallon 3.7 Liter", "pc", "piece", 25.0, 10, 45.0),
    ("packaging", "Jars / Bottles", "Uriel Bottle 60 mL", "pc", "piece", 140.0, 50, 14.0),
    ("packaging", "Jars / Bottles", "Square Jar 150 g (C.C)", "pc", "piece", 110.0, 40, 12.0),
    ("packaging", "Jars / Bottles", "Banana Chips Jar 440 mL", "pc", "piece", 90.0, 40, 15.0),
    # Pouches
    ("packaging", "Pouches", "Matte Kraft Pouch (white) 13x21 cm", "pc", "piece", 500.0, 150, 6.0),
    ("packaging", "Pouches", "Matte Kraft Pouch (brown) 17x24 cm", "pc", "piece", 420.0, 150, 7.0),
    ("packaging", "Pouches", "Cacao Powder Pouch (black) 15x22 cm", "pc", "piece", 260.0, 100, 7.5),
    ("packaging", "Pouches", "Lip Balm Tube 5 mL", "pc", "piece", 200.0, 60, 8.0),
    ("packaging", "Pouches", "Cookie Pouch 5.5x8.5 cm", "pc", "piece", 600.0, 200, 1.5),
    # Cap seals
    ("packaging", "Cap Seals", "48 mm Seal (100 mL)", "pc", "piece", 400.0, 120, 0.8),
    ("packaging", "Cap Seals", "58 mm Seal (200 mL)", "pc", "piece", 300.0, 100, 0.9),
    ("packaging", "Cap Seals", "63 mm Seal (250 mL)", "pc", "piece", 420.0, 120, 1.0),
    ("packaging", "Cap Seals", "70 mm Seal (500 mL)", "pc", "piece", 180.0, 60, 1.1),
    ("packaging", "Cap Seals", "Lip Balm Seal", "pc", "piece", 220.0, 60, 0.6),
    ("packaging", "Cap Seals", "Uriel Seal 85 mL", "pc", "piece", 160.0, 50, 0.7),
    # Packing supplies
    ("packaging", "Packing Supplies", "Bubble Wrap", "roll", "unit", 6.0, 2, 380.0),
    ("packaging", "Packing Supplies", "Packaging Tape", "roll", "unit", 24.0, 8, 45.0),
    ("packaging", "Packing Supplies", "Stretch Film", "roll", "unit", 5.0, 2, 290.0),
    ("packaging", "Packing Supplies", "Fragile Tape", "roll", "unit", 10.0, 4, 60.0),
    ("packaging", "Packing Supplies", "Corrugated Box (HLGC)", "pc", "piece", 120.0, 40, 22.0),
    ("packaging", "Packing Supplies", "Small Box", "pc", "piece", 150.0, 50, 12.0),
    ("packaging", "Packing Supplies", "Medium Box", "pc", "piece", 90.0, 30, 18.0),
    ("packaging", "Packing Supplies", "Used Carton", "pc", "piece", 40.0, 0, 0.0),
    # Production / cleaning supplies
    ("cleaning", "Production Supplies", "Gloves", "box", "unit", 12.0, 4, 220.0),
    ("cleaning", "Production Supplies", "Tissue", "roll", "unit", 36.0, 12, 18.0),
    ("cleaning", "Production Supplies", "Face Mask", "box", "unit", 8.0, 3, 150.0),
    ("cleaning", "Production Supplies", "Dishwashing Liquid 3.78 L", "gal", "unit", 4.0, 2, 320.0),
    ("cleaning", "Production Supplies", "Handwashing Soap 3.78 L", "gal", "unit", 3.0, 2, 300.0),
    ("cleaning", "Production Supplies", "Detergent 3.78 L", "gal", "unit", 3.0, 2, 340.0),
    ("cleaning", "Production Supplies", "Multi-surface Cleaner", "bottle", "unit", 6.0, 2, 180.0),
    ("cleaning", "Production Supplies", "Sponge", "pc", "piece", 20.0, 8, 15.0),
    ("cleaning", "Production Supplies", "Zonrox (bleach)", "gal", "unit", 4.0, 2, 160.0),
    ("cleaning", "Production Supplies", "Steel Wool", "pc", "piece", 15.0, 5, 12.0),
    # Office supplies
    ("office", "Office Supplies", "A4 Bond Paper", "ream", "unit", 8.0, 3, 260.0),
    ("office", "Office Supplies", "Long Bond Paper", "ream", "unit", 5.0, 2, 290.0),
    ("office", "Office Supplies", "A3 Photo Sticker", "pack", "unit", 6.0, 2, 280.0),
    ("office", "Office Supplies", "Yassen Vinyl (Transparent)", "pack", "unit", 4.0, 2, 320.0),
    ("office", "Office Supplies", "Ballpen — Black", "pc", "piece", 24.0, 10, 10.0),
    ("office", "Office Supplies", "Ballpen — Red", "pc", "piece", 12.0, 5, 10.0),
    ("office", "Office Supplies", "Ballpen — Blue", "pc", "piece", 24.0, 10, 10.0),
    ("office", "Office Supplies", "Pilot Pen", "pc", "piece", 10.0, 4, 45.0),
    ("office", "Office Supplies", "Scissors", "pc", "piece", 4.0, 1, 65.0),
    ("office", "Office Supplies", "Stapler", "pc", "piece", 3.0, 1, 180.0),
    ("office", "Office Supplies", "Staple Wire (bala)", "box", "unit", 6.0, 2, 35.0),
    ("office", "Office Supplies", "Fastener", "box", "unit", 3.0, 1, 60.0),
    ("office", "Office Supplies", "Cutter", "pc", "piece", 4.0, 1, 55.0),
    ("office", "Office Supplies", "Cutter Blade", "pack", "unit", 5.0, 2, 40.0),
    ("office", "Office Supplies", "Certificate Holder", "pc", "piece", 10.0, 3, 35.0),
    ("office", "Office Supplies", "Ink 003 Cyan", "bottle", "unit", 2.0, 1, 380.0),
    ("office", "Office Supplies", "Ink 003 Black", "bottle", "unit", 3.0, 1, 380.0),
    ("office", "Office Supplies", "Ink 003 Yellow", "bottle", "unit", 2.0, 1, 380.0),
    ("office", "Office Supplies", "Ink 003 Magenta", "bottle", "unit", 2.0, 1, 380.0),
    ("office", "Office Supplies", "Folder (Long)", "pc", "piece", 30.0, 10, 8.0),
    ("office", "Office Supplies", "Thin Photo Top (manipis)", "pack", "unit", 3.0, 1, 220.0),
]


# --- Inventory of Assets ----------------------------------------------------
# (item_no, name, category, quantity, unit, condition, remarks)
ASSETS = [
    ("AFP-001", "Freezer", "Appliances", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-002", "Chiller", "Appliances", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-037", "Split Type Aircon", "Appliances", 1, "unit", "Serviceable",
     "Listed without an item no. or quantity on the paper register"),
    ("AFP-003", "Dehydrator 4 Doors", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-004", "Dehydrator 1 Door", "Machines", 3, "unit", "Serviceable", "Good condition"),
    ("AFP-005", "Gas Stove Oven", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-006", "Roaster", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-007", "Winnower", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-008", "Sterilizer", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-009", "Press Machine", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-010", "Cacao Grinder", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-011", "Ginger Grinder", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-012", "Lemon Juicer", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-013", "Calamansi Juicer", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-014", "Filling Machine", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-015", "Liquid Mixer", "Machines", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-016", "Melanger", "Machines", 3, "unit", "Serviceable", "Good condition"),
    ("AFP-017", "Automatic Sealer", "Pouch Sealer", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-018", "Manual Sealer", "Pouch Sealer", 3, "unit", "Serviceable", "Good condition"),
    ("AFP-019", "Manual Vacuum Sealer", "Vacuum Sealer", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-020", "Manual Stove", "Gas Stove", 2, "unit", "Serviceable", "Good condition"),
    ("AFP-021", "Gas Tank", "Gas Stove", 4, "unit", "Serviceable", "Good condition"),
    ("AFP-022", "Hand Dryer", "Electronic Appliances", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-023", "Heat Gun", "Electronic Appliances", 3, "unit", "Serviceable", "Good condition"),
    ("AFP-024", "3 Tub Sink", "Stainless Table / Sink", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-025", "2 Tub Sink", "Stainless Table / Sink", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-026", "Stainless Table", "Stainless Table / Sink", 8, "unit", "Serviceable", "Good condition"),
    ("AFP-027", "Refill Tank", "Tank", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-028", "Cooking Pot", "Stainless Pot (Caldero)", 3, "unit", "Serviceable", "Good condition"),
    ("AFP-029", "Pressure Washer", "Washer", 1, "unit", "Serviceable", "Good condition"),
    ("AFP-030", "Square Tub", "Plastic Tub", 2, "unit", "Serviceable", "Good condition"),
    ("AFP-031", "Round Tub", "Plastic Tub", 8, "unit", "Serviceable", "Good condition"),
    ("AFP-032", "Plastic Table", "Tables / Chairs", 4, "unit", "Serviceable", "Good condition"),
    ("AFP-033", "Plastic Chairs", "Tables / Chairs", 6, "unit", "Serviceable", "Good condition"),
    ("AFP-034", "Dry Rack White", "Storage Rack", 4, "unit", "Serviceable", "Good condition"),
    ("AFP-035", "Storage Rack", "Storage Rack", 7, "unit", "Serviceable", "Good condition"),
    ("AFP-036", "Storage Box (Big) Black", "Storage Box / Tray", 14, "unit", "Serviceable", "Good condition"),
]
ASSET_CATEGORIES = []
for _row in ASSETS:
    if _row[2] not in ASSET_CATEGORIES:
        ASSET_CATEGORIES.append(_row[2])


# --- Supplier Directory -----------------------------------------------------
# (name, tin, category, items, buy_from / contact)
SUPPLIERS = [
    ("Allen Mall", "", "Packing", "Jute cord rope 15 mm & 25 mm", "Shopee"),
    ("Akiro Store", "", "Packing", "Vacuum sealers 25x35 cm", ""),
    ("2 Dragons", "", "Office", "12.5 in x 164 ft phototop (glossy)", "Shopee"),
    ("Best Buy Equipment and Supplies", "005-171-447-000", "Production", "", ""),
    ("Born For You", "", "Packing", "Lip balm tube 5 mL", "Shopee"),
    ("Carol 201302", "", "Packing", "", ""),
    ("Cartels Box PH", "", "Packing", "Dark amber gel pump / mist spray 50 mL", ""),
    ("CBPH Packing Supplies", "", "Packing", "Packing tape / cling wrap / bubble wrap", ""),
    ("Clabel Store", "", "Packing", "Thermal label 25x15 mm / 1500 pcs", "Shopee"),
    ("Curated Plants - Daily Deals", "", "Packing", "1 L", ""),
    ("Darasin", "", "Packing", "Turmeric powder sticker", ""),
    ("Drakes Packaging Supplies", "", "Packing", "300 mL plastic jar", "Shopee"),
    ("Davao CVI", "", "Packing", "Bottles 100 / 200 / 240 / 280 / 500 mL", "0919-232-4051"),
    ("Easyhome 168", "", "Packing",
     "Brown matte pouch 18x25 cm; ginger pouch 11x18 cm; white matte pouch "
     "13x21 cm; clear goodie pouch (tableya) 5.5x8.5 cm", "Shopee"),
    ("Entrepouch", "", "Packing", "White matte pouch 13x21 cm", ""),
    ("ES Print Industries Inc", "", "Office", "Cutting machine", ""),
    ("Filpet, Incorporated", "000-117-868-00001", "Packing", "Bottles 300 mL / 1 L", "CDO"),
    ("Freya Box", "", "Packing", "Corrugated box small / medium / large", "Shopee"),
    ("Gomakearts", "", "Packing", "36 in kraft paper rolls", "0935-042-6624"),
    ("Hand and Full", "", "Packing", "Jars / bottles", "Shopee"),
    ("Inkrite", "", "Office", "Pigment ink", "Shopee"),
    ("Tintrepreneur Online Shop", "", "Packing", "Uriel plastic seal 85 mL", "Shopee"),
    ("Joystar Consumer Goods Trading", "", "Production", "", ""),
    ("JRE Gasul Center", "773-799-363-00000", "Production", "Gasul (LPG)", ""),
    ("Label House", "", "Packing", "Stickers (Davao)", ""),
    ("Marbros.Coop", "", "Production", "Face mask / sponge", "Shopee"),
    ("Megawise Industries", "", "Packing", "1 L / 3.7 L HDPE", "Shopee"),
    ("Nexpak Packaging PH", "", "Packing", "3.7 L HDPE", "Shopee"),
    ("Panda's Stationery Shop", "", "Office", "Cutting mat PVC (green) A3 300x450 mm", "Shopee"),
    ("PKJ Storage & Organizer Shop", "", "Packing", "Lip balm seal", "Shopee"),
    ("Red Three Online", "", "Packing", "Black matte pouch 15x22 cm", ""),
    ("Sanitary Care Products Asia", "004-640-600-00020", "Production",
     "Tissue / dishwashing / all-purpose cleaner", "Shopee"),
    ("Slow Live House", "", "Packing", "Seal cap liners (CC) 70 mm", "Shopee"),
    ("Smallshop", "", "Office", "Cutting mat transparent 12x12 in", "Shopee"),
    ("Sticker Online", "", "Office", "Yassen vinyl (transparent)", ""),
    ("Sungold Commercial", "010-048-909-001", "Packing", "Jars", "TikTok"),
    ("SY Homedeco", "", "Production", "Gloves", "Mae Leng 0950-466-6595"),
    ("Tengjia International Corp", "009-858-156-00000", "Packing", "Jars", "Shopee"),
    ("Tomm & Thea", "", "Production", "Dishwashing / detergent / all-purpose cleaner", ""),
    ("The Blue Pantry OPC", "649-351-209-00000", "Production", "", "Shopee"),
    ("The Home Patrol", "", "Packing", "Cookie jar 440 mL (banana chips)", "Shopee"),
    ("Waybill Online", "", "Packing", "Tape dispenser", "Shopee"),
    ("Yopsun", "", "Office",
     "Quaff 90 gsm A4; waterproof glossy / matte / transparent; A3 Quaff "
     "glossy photo sticker 135 gsm", ""),
]

# Raw-material sources used by the demo deliveries (not on the paper
# directory, which covers office / production / packing suppliers).
DEMO_RAW_SUPPLIERS = [
    ("Mindanao Forest Apiary", "Raw", "Raw forest honey by container", "0917-100-2001"),
    ("Highland Produce Traders", "Raw", "Ginger, turmeric, lemon, calamansi by crate", "0917-100-2002"),
    ("Agusan Cacao Growers", "Raw", "Fermented cacao beans", "0917-100-2003"),
]
