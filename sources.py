# -*- coding: utf-8 -*-
"""
Source definitions for the EU Tax Developments bot.

Every source produces RSS entries. We use two kinds:
  1. Google News RSS search queries (topic x country, in English + local language)
  2. A few stable official / specialist RSS feeds

Each source carries metadata (country, topic) so the rest of the pipeline can
label and prioritise items without re-guessing.
"""

from urllib.parse import quote_plus

# Priority countries get English + native-language coverage.
# locale = (hl, gl, ceid) for Google News native-language search.
PRIORITY = {
    "Netherlands": {
        "en_terms": "Netherlands",
        "locale": ("nl", "NL", "NL:nl"),
        "cit_local": "vennootschapsbelasting tarief",
        "vat_local": "btw-tarief wijziging",
    },
    "Luxembourg": {
        "en_terms": "Luxembourg",
        "locale": ("fr", "FR", "FR:fr"),
        "cit_local": "impôt sociétés Luxembourg taux",
        "vat_local": "TVA Luxembourg taux",
    },
    "Denmark": {
        "en_terms": "Denmark",
        "locale": ("da", "DK", "DK:da"),
        "cit_local": "selskabsskat sats",
        "vat_local": "moms sats ændring",
    },
    "Finland": {
        "en_terms": "Finland",
        "locale": ("fi", "FI", "FI:fi"),
        "cit_local": "yhteisövero verokanta",
        "vat_local": "arvonlisävero kanta muutos",
    },
    "Norway": {
        "en_terms": "Norway",
        "locale": ("no", "NO", "NO:no"),
        "cit_local": "selskapsskatt sats",
        "vat_local": "merverdiavgift sats endring",
    },
    "Sweden": {
        "en_terms": "Sweden",
        "locale": ("sv", "SE", "SE:sv"),
        "cit_local": "bolagsskatt sats",
        "vat_local": "moms sats ändring",
    },
}

# Rest of Europe (lower priority, English-only) when include_all_europe is on.
OTHER_EUROPE = [
    "Germany", "France", "Belgium", "Ireland", "Italy", "Spain", "Portugal",
    "Austria", "Poland", "Czech Republic", "Hungary", "Greece", "Romania",
    "Switzerland", "United Kingdom", "Estonia", "Latvia", "Lithuania",
    "Slovakia", "Slovenia", "Croatia", "Bulgaria", "Iceland",
]


def _gnews(query, locale=("en", "US", "US:en")):
    hl, gl, ceid = locale
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + f"&hl={hl}&gl={gl}&ceid={ceid}"
    )


def build_sources(config):
    """Return a list of dicts: {url, country, topic, priority}."""
    sources = []
    topics = set(config.get("topics", ["CIT", "VAT", "EU_DIRECTIVE"]))

    def add(url, country, topic, priority):
        sources.append({"url": url, "country": country, "topic": topic, "priority": priority})

    # --- Priority countries: English coverage ---
    for country, meta in PRIORITY.items():
        name = meta["en_terms"]
        if "CIT" in topics:
            add(_gnews(f'"corporate income tax" {name} rate'), country, "CIT", True)
        if "VAT" in topics:
            add(_gnews(f'VAT rate {name} change'), country, "VAT", True)

    # --- Priority countries: native-language coverage ---
    if config.get("include_local_language", True):
        for country, meta in PRIORITY.items():
            loc = meta["locale"]
            if "CIT" in topics:
                add(_gnews(meta["cit_local"], loc), country, "CIT", True)
            if "VAT" in topics:
                add(_gnews(meta["vat_local"], loc), country, "VAT", True)

    # --- EU-wide directives & rate harmonisation ---
    if "EU_DIRECTIVE" in topics:
        eu_queries = [
            "EU tax directive adopted",
            "EU VAT directive",
            '"VAT in the Digital Age" ViDA',
            "EU Pillar Two minimum tax directive",
            "ECOFIN tax agreement directive",
            "BEFIT EU corporate tax",
            "European Commission tax proposal directive",
        ]
        for q in eu_queries:
            add(_gnews(q), "EU", "EU_DIRECTIVE", True)

    # --- Rest of Europe (lower priority) ---
    if config.get("include_all_europe", True):
        for country in OTHER_EUROPE:
            if "CIT" in topics:
                add(_gnews(f'"corporate income tax" {country} rate'), country, "CIT", False)
            if "VAT" in topics:
                add(_gnews(f'VAT rate {country} change'), country, "VAT", False)

    # --- Stable specialist feeds (general European/global tax policy) ---
    add("https://taxfoundation.org/feed/", "EU", "GENERAL", True)

    return sources
