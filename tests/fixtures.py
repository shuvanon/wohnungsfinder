"""
tests/fixtures.py — Shared test data.

All test listing dicts live here so individual test files stay focused
on behaviour rather than data construction.
"""

# A clean listing that should pass hard filters and score HIGH
GOOD_LISTING = {
    "url":        "https://www.degewo.de/de/properties/W3110-57004-0141-0102.html",
    "title":      "Singlewohnung mit Balkon!",
    "address":    "Siegfriedstraße 21A, 10365, Lichtenberg",
    "district":   "Lichtenberg",
    "rooms":      2.0,
    "size_m2":    51.03,
    "cold_rent":  469.27,
    "total_rent": 574.39,
    "wbs":        "nicht erforderlich",
    "available":  "12.03.2026",
    "posted":     "12.03.2026",
    "floor":      "1 von 4",
    "year_built": 1930,
    "features":   ["Balkon", "Badewanne"],
    "raw_text":   "Singlewohnung mit Balkon Lichtenberg nicht erforderlich Balkon Badewanne",
}

# Seniors-only listing — blocked by keyword
SENIOR_LISTING = {
    "url":        "https://www.wbm.de/angebote/51-3010/1/71",
    "title":      "1-Zimmer-Wohnung Wohnen ab 55 Jahren WBS erforderlich",
    "address":    "Singerstraße 83, 10243, Friedrichshain-Kreuzberg",
    "district":   "Friedrichshain-Kreuzberg",
    "rooms":      1.0,
    "size_m2":    25.60,
    "cold_rent":  244.82,
    "total_rent": 537.82,
    "wbs":        "erforderlich",
    "available":  "12.03.2026",
    "posted":     "12.03.2026",
    "floor":      "5",
    "year_built": 1966,
    "features":   ["Balkon", "Aufzug", "Dusche"],
    "raw_text":   "Wohnen ab 55 Jahren WBS erforderlich Friedrichshain Aufzug Dusche",
}

# Too expensive — blocked by max rent
EXPENSIVE_LISTING = {
    "url":        "https://www.howoge.de/wohnungen-gewerbe/wohnungssuche/detail/1771-14596-13.html",
    "title":      "Neubauwohnung mit 2 Balkonen",
    "address":    "Wittenberger Straße 40, 12689, Marzahn-Hellersdorf",
    "district":   "Marzahn-Hellersdorf",
    "rooms":      3.0,
    "size_m2":    90.0,
    "cold_rent":  1305.0,
    "total_rent": 1485.0,
    "wbs":        "nicht erforderlich",
    "available":  "16.04.2026",
    "posted":     "12.03.2026",
    "floor":      "5 von 6",
    "year_built": 2024,
    "features":   ["Balkon", "Aufzug", "Barrierefrei", "Badewanne"],
    "raw_text":   "Neubauwohnung Marzahn-Hellersdorf nicht erforderlich Aufzug Fußbodenheizung",
}

# WBS required listing
WBS_LISTING = {
    "url":        "https://www.gewobag.de/fuer-mietinteressentinnen/mietangebote/0100-01206-0503-0139",
    "title":      "Wohnen in Tegel Süd mit Wohnberechtigungsschein",
    "address":    "Wickeder Straße 6B, 13507, Reinickendorf",
    "district":   "Reinickendorf",
    "rooms":      2.0,
    "size_m2":    55.31,
    "cold_rent":  540.88,
    "total_rent": 711.88,
    "wbs":        "erforderlich",
    "available":  "01.03.2026",
    "posted":     "12.03.2026",
    "floor":      "1 von 4",
    "year_built": 1959,
    "features":   ["Balkon"],
    "raw_text":   "Wohnen Tegel Süd Reinickendorf WBS erforderlich Balkon Gasheizung",
}

# High-scoring listing: no WBS + cheap + preferred district + balcony + elevator + new build
HIGH_SCORE_LISTING = {
    "url":        "https://www.gesobau.de/mietangebote/example-high",
    "title":      "Moderne 3-Zimmer in Pankow",
    "address":    "Beispielstraße 1, 13086, Pankow",
    "district":   "Pankow",
    "rooms":      3.0,
    "size_m2":    78.0,
    "cold_rent":  650.0,
    "total_rent": 820.0,
    "wbs":        "nicht erforderlich",
    "available":  "01.05.2026",
    "posted":     "13.03.2026",
    "floor":      "3 von 6",
    "year_built": 2010,
    "features":   ["Balkon", "Aufzug"],
    "raw_text":   "Moderne Wohnung Pankow nicht erforderlich Balkon Aufzug Fernwärme",
}

# Listing whose address has only a postcode — no district name
POSTCODE_ONLY_LISTING = {
    "url":     "https://www.gewobag.de/fuer-mietinteressentinnen/mietangebote/1000-00274-0101-0005",
    "title":   "Singlewohnung im Kiez",
    "address": "Lychener Straße 61, 10437",   # no district text — must resolve via postcode
    "district": "",
    "rooms":      1.0,
    "size_m2":    33.31,
    "cold_rent":  458.74,
    "total_rent": 558.74,
    "wbs":        "nicht erforderlich",
    "available":  "01.04.2026",
    "posted":     "12.03.2026",
    "floor":      "2 von 5",
    "year_built": 1903,
    "features":   ["Keller"],
    "raw_text":   "Singlewohnung im Kiez 10437 nicht erforderlich Keller Gasheizung",
}

# Listing with unknown postcode — should log a warning and return ""
UNKNOWN_POSTCODE_LISTING = {
    "url":     "https://www.example.de/unknown",
    "title":   "Mystery apartment",
    "address": "Unbekannte Straße 1, 99999",
    "district": "",
    "rooms": 2.0, "size_m2": 50.0, "cold_rent": 600.0, "total_rent": 750.0,
    "wbs": "nicht erforderlich", "year_built": 2000,
    "features": [], "raw_text": "Unbekannte Straße 99999 nicht erforderlich",
}
