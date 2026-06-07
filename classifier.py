# -*- coding: utf-8 -*-
"""
Keyword-based classification for tax-development news items.

Two jobs:
  1. is_relevant() -> drop obvious noise (must mention tax + a rate/law context).
  2. classify_status() -> ENACTED / PROPOSAL / UPDATE, in multiple languages.

No external API needed. Heuristics are intentionally conservative: an item is
only marked ENACTED when there is an explicit "adopted / in force / signed"
signal and the proposal signal does not clearly dominate.
"""

import re

# ---- Status keywords (lowercase, multilingual) --------------------------------

ENACTED_TERMS = [
    # English
    "enacted", "adopted", "approved", "passed into law", "signed into law",
    "entered into force", "enters into force", "entry into force", "in force",
    "came into force", "comes into force", "gazetted", "published in the official",
    "official gazette", "royal assent", "ratified", "promulgated", "voted into law",
    "parliament approved", "parliament passed", "approved by parliament",
    "now law", "becomes law", "took effect", "takes effect", "effective from",
    # Dutch (NL)
    "aangenomen", "in werking getreden", "treedt in werking", "vastgesteld",
    "gepubliceerd in het staatsblad", "staatsblad", "bekrachtigd",
    "wet aangenomen", "eerste kamer", "door de senaat aangenomen",
    # German (LU)
    "verabschiedet", "in kraft getreten", "tritt in kraft", "beschlossen",
    "verkündet", "gesetz verabschiedet",
    # French (LU)
    "adopté", "entré en vigueur", "entre en vigueur", "promulgué",
    "voté définitivement", "loi adoptée",
    # Danish (DK)
    "vedtaget", "trådt i kraft", "træder i kraft", "lov vedtaget", "folketinget vedtog",
    # Finnish (FI)
    "hyväksytty", "tuli voimaan", "tulee voimaan", "säädetty", "eduskunta hyväksyi",
    "laki hyväksytty",
    # Norwegian (NO)
    "vedtatt", "trer i kraft", "trådt i kraft", "stortinget vedtok", "lov vedtatt",
    # Swedish (SE)
    "antagen", "antagit", "trätt i kraft", "träder i kraft", "riksdagen antog",
    "lag antagen", "beslutat",
]

PROPOSAL_TERMS = [
    # English
    "proposal", "proposed", "proposes", "draft", "draft law", "draft bill",
    "bill", "plans to", "plan to", "considering", "consultation", "white paper",
    "green paper", "would reduce", "would increase", "set to", "expected to",
    "could cut", "may raise", "to be introduced", "under discussion",
    "negotiations", "not yet", "aims to", "intends to",
    # Dutch
    "voorstel", "wetsvoorstel", "concept", "consultatie", "voornemen",
    "van plan", "wil verlagen", "wil verhogen", "prinsjesdag", "miljoenennota",
    "tweede kamer behandelt",
    # German
    "gesetzentwurf", "entwurf", "vorschlag", "geplant", "plant",
    # French
    "projet de loi", "proposition", "envisage", "prévoit", "projet",
    # Danish
    "lovforslag", "forslag", "udkast", "planlægger",
    # Finnish
    "ehdotus", "esitys", "luonnos", "lakiesitys", "suunnittelee",
    # Norwegian
    "forslag", "lovforslag", "utkast", "planlegger", "foreslår",
    # Swedish
    "förslag", "lagförslag", "utkast", "planerar", "föreslår",
]

# ---- Relevance keywords -------------------------------------------------------

TAX_TERMS = [
    "tax", "vat", "cit", "levy", "duty",
    "belasting", "btw", "vennootschapsbelasting",
    "steuer", "mehrwertsteuer", "umsatzsteuer",
    "impôt", "tva", "fiscal",
    "skat", "moms", "selskabsskat",
    "vero", "arvonlisävero", "yhteisövero",
    "skatt", "merverdiavgift", "avgift", "bolagsskatt", "selskapsskatt",
]

RATE_OR_LAW_TERMS = [
    "rate", "percent", "%", "directive", "law", "act", "bill", "reform",
    "tarief", "wet", "richtlijn", "percentage",
    "satz", "gesetz", "richtlinie",
    "taux", "loi", "directive",
    "sats", "lov", "ændring",
    "kanta", "verokanta", "laki", "muutos",
    "endring", "antagen", "förslag",
]


# Used to keep the broad (non-country-tagged) feed European-only.
EUROPE_TERMS = [
    "eu ", "e.u.", "europe", "european", "brussels", "ecofin", "european commission",
    "european union", "vida", "pillar two", "atad", "befit",
    "netherlands", "dutch", "nederland", "holland",
    "luxembourg", "luxemburg",
    "denmark", "danish", "danmark",
    "finland", "finnish", "suomi",
    "norway", "norwegian", "norge", "norsk",
    "sweden", "swedish", "sverige", "svensk",
    "germany", "german", "france", "french", "belgium", "belgian", "ireland", "irish",
    "italy", "italian", "spain", "spanish", "portugal", "portuguese", "austria",
    "austrian", "poland", "polish", "czech", "hungary", "hungarian", "greece", "greek",
    "romania", "romanian", "switzerland", "swiss", "estonia", "estonian", "latvia",
    "latvian", "lithuania", "lithuanian", "slovakia", "slovak", "slovenia", "slovenian",
    "croatia", "croatian", "bulgaria", "bulgarian", "iceland", "icelandic",
    "united kingdom", "britain", "british", "uk ",
]


def _norm(text):
    return (text or "").lower()


def _contains_any(text, terms):
    for t in terms:
        if t in text:
            return t
    return None


def is_relevant(title, summary, strict=False):
    """Light noise filter.

    Targeted Google-News queries are already topic+country specific, so we only
    require a tax term (strict=False). For broad feeds (e.g. Tax Foundation) we
    also require a rate/law context word (strict=True) to cut unrelated items.
    """
    text = _norm(title) + " " + _norm(summary)
    if not _contains_any(text, TAX_TERMS):
        return False
    if strict and not _contains_any(text, RATE_OR_LAW_TERMS):
        return False
    return True


def mentions_europe(title, summary):
    text = _norm(title) + " " + _norm(summary)
    return _contains_any(text, EUROPE_TERMS) is not None


def classify_status(title, summary):
    """Return (status, evidence) where status in {ENACTED, PROPOSAL, UPDATE}."""
    text = _norm(title) + " " + _norm(summary)

    enacted_hit = _contains_any(text, ENACTED_TERMS)
    proposal_hit = _contains_any(text, PROPOSAL_TERMS)

    # Count how strong each signal is (number of distinct matches).
    enacted_score = sum(1 for t in ENACTED_TERMS if t in text)
    proposal_score = sum(1 for t in PROPOSAL_TERMS if t in text)

    if enacted_hit and enacted_score >= proposal_score:
        return "ENACTED", enacted_hit
    if proposal_hit:
        return "PROPOSAL", proposal_hit
    if enacted_hit:
        return "ENACTED", enacted_hit
    return "UPDATE", None


STATUS_ICON = {
    "ENACTED": "🔴 ENACTED",
    "PROPOSAL": "🟡 PROPOSAL",
    "UPDATE": "🔵 UPDATE",
}
