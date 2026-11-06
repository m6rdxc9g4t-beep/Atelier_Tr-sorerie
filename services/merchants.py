"""Reconnaissance du commerçant derrière un libellé bancaire.

Les banques françaises entourent le nom du commerçant de bruit : type d'opération, date,
numéro de carte masqué, référence de mandat, ville… Ce module en extrait un nom lisible
(« Carrefour Market ») et une clé stable (« carrefour market ») qui sert à regrouper les
opérations d'un même commerçant, à appliquer les règles et à détecter les récurrences.

Il contient aussi un petit dictionnaire de commerçants français courants, avec leur catégorie
par défaut : c'est la troisième étape du classement en cascade, après les règles de
l'utilisateur et son historique. Aucun appel réseau.
"""
from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------- nettoyage

# Mots ajoutés par les banques, sans rapport avec le commerçant
_BANK_WORDS = {
    "cb", "carte", "cartes", "paiement", "paiemt", "paie", "par", "achat", "achats", "prlv", "prelevement", "prelev",
    "prel", "europeen", "sepa", "sdd", "vir", "virement", "virt", "inst", "instantane", "recu", "emis",
    "facture", "fact", "fac", "en", "votre", "faveur", "ordre", "web", "internet", "contactless", "sans", "contact",
    "nfc", "debit", "differe", "immediat", "prlvt", "tip", "echeance", "ech", "avoir", "remise", "operation",
    "op", "frais", "commission", "com", "eur", "euro", "euros", "x", "n", "no", "num", "le", "la", "les",
    "du", "de", "des", "d", "l", "a", "au", "aux", "et", "pour", "fr", "france", "sas", "sa", "sarl", "srl",
    "ltd", "gmbh", "inc", "bv", "eu", "europe", "s", "cie", "ste", "mr", "mme", "m", "monsieur", "madame",
}
# Marqueurs après lesquels viennent des références (mandat, identifiant créancier, motif…)
_REF_MARKERS = re.compile(
    r"\b(id|ref|refs|rum|mandat|mdt|ics|motif|libelle|lib|ntt|n°|reference|date|ech|echeance|creancier)\b\s*[:.]?",
)
_DE_MARKER = re.compile(r"(?:^|\s|/)de\s*:\s*(.+)$")          # PRELEVEMENT ... DE: FREE MOBILE ID: ...
_SLASH_DE = re.compile(r"/de\s+([^/]+)")                       # VIR SEPA RECU /DE M DUPONT /MOTIF ...
_INTERMEDIARY = re.compile(r"\b(paypal|sumup|sum up|zettle|stripe|lydia|payplug|adyen)\s*\*+\s*")
_CARD_MASK = re.compile(r"\b(x+\d+|\d*x{2,}\d*|\*+\d+|\d+\*+)\b")
_DATES = re.compile(r"\b\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?\b")
_TOKEN = re.compile(r"[a-z][a-z0-9&+]*")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()


def normalize_text(text: str) -> str:
    """Forme comparable d'un libellé ou d'un motif : minuscules, sans accents, ponctuation réduite."""
    return " ".join(re.sub(r"[^a-z0-9&+.]+", " ", _ascii(text)).split())


def merchant_key(label: str) -> str:
    """Clé stable du commerçant : 'CB CARREFOUR MARKET 12/10 X1234' -> 'carrefour market'.

    Trois mots significatifs au plus : les villes et numéros de magasin qui suivent sont ignorés.
    Renvoie '' si le libellé ne contient rien d'exploitable.
    """
    text = _ascii(label)
    text = _INTERMEDIARY.sub(" ", text)
    for pattern in (_DE_MARKER, _SLASH_DE):
        match = pattern.search(text)
        if match and match.group(1).strip():
            text = match.group(1)
            break
    marker = _REF_MARKERS.search(text)
    if marker and marker.start() > 0:
        text = text[: marker.start()]
    text = _CARD_MASK.sub(" ", _DATES.sub(" ", text))
    words = _TOKEN.findall(text)
    words = [w for w in words if w and w not in _BANK_WORDS and not any(c.isdigit() for c in w[1:])]
    return " ".join(words[:3])


def merchant_name(label: str, amount_cents: int | None = None) -> str:
    """Nom lisible du commerçant, pour l'affichage. Repli sur le libellé si rien n'est reconnu."""
    return identify(label, amount_cents)["name"]


def identify(label: str, amount_cents: int | None = None) -> dict:
    """{key, name, category} : clé de regroupement, nom affiché, catégorie par défaut (ou None).

    Un commerçant du dictionnaire est regroupé sous son nom (« Carrefour » à Paris comme à Lyon) ;
    sinon, la clé est celle de merchant_key().
    """
    known = known_merchant(label, amount_cents)
    if known:
        return {"key": normalize_text(known[0]), "name": known[0], "category": known[1]}
    key = merchant_key(label)
    if not key:
        return {"key": "", "name": " ".join(str(label or "").split())[:60], "category": None}
    return {"key": normalize_text(key), "name": _display_name(key, label), "category": None}


# --------------------------------------------------------------------------- commerçants connus

# (motifs recherchés dans le libellé normalisé, nom affiché, catégorie par défaut, sens)
# Sens : "debit" = uniquement pour une sortie d'argent, "credit" = entrée, None = les deux
# (un remboursement Amazon reste classé « Shopping » et vient réduire les dépenses).
# L'ordre compte : les motifs les plus précis d'abord (« uber eats » avant « uber »).
KNOWN_MERCHANTS: list[tuple[tuple[str, ...], str, str, str | None]] = [
    # Restaurants et livraison de repas
    (("uber eats", "ubereats"), "Uber Eats", "Restaurants", None),
    (("deliveroo",), "Deliveroo", "Restaurants", None),
    (("just eat",), "Just Eat", "Restaurants", None),
    (("mcdonald", "mc donald"), "McDonald's", "Restaurants", None),
    (("burger king",), "Burger King", "Restaurants", None),
    (("kfc",), "KFC", "Restaurants", None),
    (("starbucks",), "Starbucks", "Restaurants", None),
    (("restaurant", "brasserie", "pizzeria", "sushi", "creperie", "bistrot"), None, "Restaurants", "debit"),
    # Abonnements numériques
    (("netflix",), "Netflix", "Abonnements", None),
    (("spotify",), "Spotify", "Abonnements", None),
    (("deezer",), "Deezer", "Abonnements", None),
    (("disney plus", "disneyplus", "disney+"), "Disney+", "Abonnements", None),
    (("canal+", "canal plus", "canalplus"), "Canal+", "Abonnements", None),
    (("amazon prime", "prime video", "amzn prime"), "Amazon Prime", "Abonnements", None),
    (("apple.com bill", "apple com bill", "itunes"), "Apple (abonnements)", "Abonnements", None),
    (("youtube premium", "google storage", "google one"), "Google (abonnements)", "Abonnements", None),
    (("icloud",), "iCloud", "Abonnements", None),
    (("microsoft 365", "msft", "xbox"), "Microsoft", "Abonnements", None),
    (("adobe",), "Adobe", "Abonnements", None),
    (("openai", "chatgpt"), "OpenAI", "Abonnements", None),
    (("anthropic", "claude ai"), "Anthropic", "Abonnements", None),
    (("basic fit", "basicfit", "fitness park", "keepcool", "on air fitness"), None, "Abonnements", "debit"),
    # Énergie, eau, télécoms
    (("edf",), "EDF", "Énergie & Internet", None),
    (("engie",), "Engie", "Énergie & Internet", None),
    (("totalenergies electricite", "total direct energie", "total energie gaz"), "TotalEnergies (énergie)",
     "Énergie & Internet", None),
    (("ekwateur",), "ekWateur", "Énergie & Internet", None),
    (("ohm energie",), "Ohm Énergie", "Énergie & Internet", None),
    (("veolia",), "Veolia (eau)", "Énergie & Internet", None),
    (("suez eau", "eau de paris", "saur"), None, "Énergie & Internet", "debit"),
    (("free mobile", "free telecom", "freebox", "free sas", "free haut debit"), "Free", "Énergie & Internet", None),
    (("orange",), "Orange", "Énergie & Internet", None),
    (("sosh",), "Sosh", "Énergie & Internet", None),
    (("sfr", "red by sfr"), "SFR", "Énergie & Internet", None),
    (("bouygues telecom", "bouygtel", "b and you"), "Bouygues Telecom", "Énergie & Internet", None),
    # Courses
    (("carrefour",), "Carrefour", "Courses", None),
    (("leclerc",), "E.Leclerc", "Courses", None),
    (("auchan",), "Auchan", "Courses", None),
    (("intermarche",), "Intermarché", "Courses", None),
    (("lidl",), "Lidl", "Courses", None),
    (("aldi",), "Aldi", "Courses", None),
    (("monoprix", "monop"), "Monoprix", "Courses", None),
    (("franprix",), "Franprix", "Courses", None),
    (("super u", "hyper u", "u express", "magasins u", "systeme u"), "Magasins U", "Courses", None),
    (("casino",), "Casino", "Courses", None),
    (("picard",), "Picard", "Courses", None),
    (("biocoop",), "Biocoop", "Courses", None),
    (("naturalia",), "Naturalia", "Courses", None),
    (("grand frais",), "Grand Frais", "Courses", None),
    (("netto",), "Netto", "Courses", None),
    (("cora",), "Cora", "Courses", None),
    (("g20", "spar", "vival", "proxi"), None, "Courses", "debit"),
    (("boulangerie", "patisserie", "boucherie", "fromagerie", "primeur"), None, "Courses", "debit"),
    # Transport
    (("sncf", "ouigo", "tgv inoui"), "SNCF", "Transport", None),
    (("ratp",), "RATP", "Transport", None),
    (("navigo",), "Navigo", "Transport", None),
    (("uber",), "Uber", "Transport", None),
    (("bolt",), "Bolt", "Transport", None),
    (("blablacar",), "BlaBlaCar", "Transport", None),
    (("lime",), "Lime", "Transport", None),
    (("vinci autoroute", "sanef", "aprr", "asf ", "autoroute", "peage"), "Péage", "Transport", "debit"),
    (("indigo", "parking", "saemes", "effia"), "Parking", "Transport", "debit"),
    (("esso", "shell", "avia", "station total", "totalenergies station", "relais total", "bp "), "Carburant",
     "Transport", "debit"),
    (("air france", "easyjet", "transavia", "ryanair", "vueling"), None, "Transport", None),
    # Shopping
    (("amazon", "amzn"), "Amazon", "Shopping", None),
    (("fnac",), "Fnac", "Shopping", None),
    (("darty",), "Darty", "Shopping", None),
    (("boulanger",), "Boulanger", "Shopping", None),
    (("decathlon",), "Decathlon", "Shopping", None),
    (("ikea",), "IKEA", "Shopping", None),
    (("leroy merlin",), "Leroy Merlin", "Shopping", None),
    (("castorama",), "Castorama", "Shopping", None),
    (("zara",), "Zara", "Shopping", None),
    (("h&m", "h m ", "hennes"), "H&M", "Shopping", None),
    (("kiabi",), "Kiabi", "Shopping", None),
    (("vinted",), "Vinted", "Shopping", None),
    (("cdiscount",), "Cdiscount", "Shopping", None),
    (("sephora",), "Sephora", "Shopping", None),
    (("action ",), "Action", "Shopping", "debit"),
    (("apple store",), "Apple Store", "Shopping", None),
    # Santé
    (("pharmacie", "pharma "), "Pharmacie", "Santé", None),
    (("doctolib",), "Doctolib", "Santé", None),
    (("cpam", "ameli", "assurance maladie"), "Assurance maladie", "Santé", None),
    (("laboratoire", "labo ", "opticien", "optique", "dentiste", "kine", "medecin", "docteur", "dr "),
     None, "Santé", "debit"),
    # Impôts et taxes
    (("dgfip", "impot", "finances publiques", "tresor public", "direction generale des finances"), "Impôts",
     "Impôts & Taxes", None),
    (("urssaf",), "URSSAF", "Impôts & Taxes", None),
    (("antai", "amende"), "Amende (ANTAI)", "Impôts & Taxes", "debit"),
    # Logement
    (("loyer",), "Loyer", "Logement", "debit"),
    (("foncia", "nexity", "syndic", "citya", "oralia"), None, "Logement", "debit"),
    # Revenus
    (("interets", "remuneration livret", "remuneration compte"), "Intérêts", "Intérêts", "credit"),
    (("salaire", "paie ", "remuneration"), "Salaire", "Salaire", "credit"),
    (("dividende",), "Dividendes", "Dividendes", "credit"),
    # Espèces
    (("retrait dab", "retrait guichet", "retrait especes", "retrait "), "Retrait d'espèces", "Divers", "debit"),
]


def _haystack(label: str) -> str:
    # Espaces autour pour que les motifs « bp  », « dr  »… ne correspondent qu'à des mots entiers
    return f" {normalize_text(label)} "


def _matches(pattern: str, hay: str) -> bool:
    word = pattern.strip()
    # Motif court ou terminé par une espace : mot entier exigé (« edf », « bp », « dr »…)
    if len(word) <= 4 or pattern.endswith(" "):
        return f" {word} " in hay
    return pattern in hay


def known_merchant(label: str, amount_cents: int | None = None) -> tuple[str, str] | None:
    """Commerçant reconnu dans le dictionnaire : (nom affiché, catégorie par défaut), ou None."""
    hay = _haystack(label)
    for patterns, display, category, direction in KNOWN_MERCHANTS:
        if direction == "debit" and amount_cents is not None and amount_cents > 0:
            continue
        if direction == "credit" and amount_cents is not None and amount_cents < 0:
            continue
        for p in patterns:
            if _matches(p, hay):
                return (display or merchant_name_from_key(merchant_key(label)) or category, category)
    return None


def _display_name(key: str, label: str) -> str:
    """Nom affiché à partir de la clé, en reprenant l'orthographe accentuée du libellé (« Électricité »)."""
    originals = {}
    for word in re.findall(r"[^\W\d_][\w&+]*", str(label or "")):
        originals.setdefault(_ascii(word), word)
    words = []
    for w in key.split():
        o = originals.get(w)
        words.append(o[0].upper() + o[1:].lower() if o and len(w) > 3 else merchant_name_from_key(w))
    return " ".join(words)


def merchant_name_from_key(key: str) -> str:
    return " ".join(w.upper() if len(w) <= 3 and w.isalpha() and w not in ("bio", "eau", "bar", "les") else w.capitalize()
                    for w in key.split())
