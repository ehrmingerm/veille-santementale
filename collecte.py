#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veille « santé mentale et psychiatrie » : collecte des flux.

Produit deux fichiers à la racine du dépôt :
  - veille.json : la collecte du jour (ce que la tâche quotidienne lit)
  - jours.json  : l'archive jour par jour

Deux familles de sources :
  - des requêtes Google Actualités, qui couvrent la presse française et
    internationale, y compris les titres dont les sites refusent la lecture
    automatisée (Le Monde, Libération, Radio France, The Guardian, BBC) ;
  - des flux RSS d'éditeurs, interrogés directement.

Un exécuteur GitHub Actions n'a pas les restrictions réseau d'un client : il
atteint ces sources sans intermédiaire.

Aucune dépendance : bibliothèque standard uniquement.
"""

import base64
import binascii
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse
from xml.etree import ElementTree

# --------------------------------------------------------------- reglages

GNEWS_FR = "https://news.google.com/rss/search?q={}&hl=fr&gl=FR&ceid=FR:fr"
GNEWS_EN = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en"

# Google Actualites classe ses resultats par pertinence, pas par date : sans
# cet operateur, un flux rend cent articles dont la plupart ont des mois, et
# presque tout tombe hors de la fenetre. « when:7d » lui demande de ne rendre
# que la semaine ecoulee.
FENETRE_GOOGLE = "when:7d"

# Les requetes Google Actualites, une par axe de la veille.
# Chaque cle se retrouve dans le champ "feed" du JSON : la tache sait ainsi
# d'ou vient chaque reference.
REQUETES = [
    ("politiques-soins", GNEWS_FR,
     '("santé mentale" OR psychiatrie) '
     '(réforme OR financement OR pénurie OR "feuille de route" OR ministère '
     'OR "agence régionale de santé" OR hôpital OR "secteur psychiatrique")'),

    ("stigmatisation", GNEWS_FR,
     '("santé mentale" OR psychiatrie OR "troubles psychiques") '
     '(stigmatisation OR "idées reçues" OR préjugés OR représentations '
     'OR "regard sur" OR tabou)'),

    ("droits-contrainte", GNEWS_FR,
     'psychiatrie (contention OR isolement OR "soins sans consentement" '
     'OR "hospitalisation sous contrainte" OR "droits des patients" '
     'OR "contrôleur des lieux de privation")'),

    ("pair-aidance", GNEWS_FR,
     '"pair-aidance" OR "pair-aidant" OR "pair-aidants" '
     'OR "médiateur de santé pair" OR "savoir expérientiel" '
     'OR ("rétablissement" AND ("santé mentale" OR psychiatrie)) '
     'OR ("groupe d\'entraide mutuelle" AND psychiatrie)'),

    ("societe", GNEWS_FR,
     '"santé mentale" (jeunes OR adolescents OR étudiants OR écrans '
     'OR "réseaux sociaux" OR travail OR "intelligence artificielle" '
     'OR "grande cause")'),

    ("communication", GNEWS_FR,
     '("santé mentale" OR psychiatrie) '
     '(campagne OR sensibilisation OR "prise de parole" OR témoignage '
     'OR "parle de sa dépression" OR "a révélé souffrir")'),

    ("culture", GNEWS_FR,
     '("santé mentale" OR psychiatrie OR "trouble bipolaire" OR dépression) '
     '(livre OR essai OR roman OR documentaire OR série OR film OR podcast '
     'OR "bande dessinée")'),

    ("international", GNEWS_EN,
     '"mental health" (stigma OR "mental health policy" OR "mental health '
     'services" OR coercion OR "peer support" OR "lived experience" '
     'OR "media coverage")'),
]

# Flux RSS d'editeurs, interroges directement. Ils valent mieux que Google
# Actualites : l'adresse de l'article est reelle et le chapo est fourni.
#
# Verifies au passage du 24 octobre 2026 : the-conversation-fr, sante-mentale,
# stat-news. Les autres sont des candidats ; le journal de l'execution dira
# lesquels repondent. Retirez ceux qui echouent, ajoutez les votres.
FLUX_DIRECTS = [
    # verifies
    ("the-conversation-fr", "https://theconversation.com/fr/articles.atom"),
    ("sante-mentale", "https://www.santementale.fr/feed/"),
    ("stat-news", "https://www.statnews.com/feed/"),
    # candidats
    ("psycom", "https://www.psycom.org/actualites/feed/"),
    ("le-monde-sante", "https://www.lemonde.fr/sante/rss_full.xml"),
    ("guardian-mental-health", "https://www.theguardian.com/society/mental-health/rss"),
    ("nyt-health", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml"),
    ("liberation", "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml"),
]

FENETRE_JOURS = 7          # age maximal d'une reference retenue
ARCHIVE_JOURS = 400        # profondeur conservee dans jours.json
MAX_PAR_SOURCE = 30        # plafond par requete ou par flux
RETENTATIVES_RESOLUTION = 10
ECHECS_AVANT_ABANDON = 6   # au-dela, on cesse de resoudre pour ce passage

UA_FLUX = "veille-sante-mentale/1.0 (+github actions)"
UA_PAGE = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")

ARCHIVE = "jours.json"
BRUT = "veille.json"

# --------------------------------------------------------------- filtrage

# Une reference doit parler du champ, pas seulement contenir le mot « santé ».
MOTS_DU_CHAMP = [
    "sante mentale", "mental health", "psychiatrie", "psychiatric", "psychiatry",
    "psychique", "psychiatre", "psychologue", "psychologique", "psychothérapie",
    "psychotherapie", "depression", "dépression", "bipolaire", "schizophren",
    "troubles psy", "trouble psy", "souffrance psychique", "detresse psychique",
    "détresse psychique", "pair-aidance", "pair-aidant", "retablissement",
    "rétablissement", "stigmatisation", "psychotrope", "antidepresseur",
    "antidépresseur", "suicide", "mal-etre", "mal-être", "burn-out", "burnout",
    "autisme", "neuroatypi", "handicap psychique", "psy",
]

# Bruit recurrent des requetes generalistes.
EXCLUSIONS = re.compile(
    r"horoscope|astrolog|voyance|minceur|"
    r"perdre du poids|regime minceur|recette|bons plans|code promo|"
    r"black friday|soldes|cashback|"
    r"paris sportifs|pronostic|mercato|ligue 1|"
    r"\bhoroscope du\b",
    re.IGNORECASE,
)

# Hotes qui ne sont jamais un article.
HOTES_A_IGNORER = re.compile(
    r"(^|\.)("
    r"google\.[a-z.]{2,}|google-analytics\.com|googletagmanager\.com|"
    r"googleapis\.com|googlesyndication\.com|googleadservices\.com|"
    r"googleusercontent\.com|gstatic\.com|ggpht\.com|doubleclick\.net|"
    r"ampproject\.org|youtube\.com|youtu\.be|blogger\.com|"
    r"schema\.org|w3\.org|example\.com|localhost|"
    r"facebook\.com|twitter\.com|x\.com|linkedin\.com|instagram\.com|"
    r"pinterest\.[a-z.]{2,}|whatsapp\.com|t\.me|reddit\.com|tiktok\.com|"
    r"cloudflare\.com|jsdelivr\.net|unpkg\.com|bootstrapcdn\.com|jquery\.com|"
    r"cookielaw\.org|onetrust\.com|didomi\.io|sentry\.io|hotjar\.com|"
    r"chartbeat\.com|outbrain\.com|taboola\.com|criteo\.com|adsrvr\.org|"
    r"amazon-adsystem\.com|adnxs\.com|scorecardresearch\.com|quantserve\.com"
    r")$", re.IGNORECASE)

EXTENSIONS_A_IGNORER = re.compile(
    r"\.(js|mjs|css|map|json|xml|txt|ico|png|jpe?g|gif|svg|webp|avif|bmp|"
    r"woff2?|ttf|otf|eot|mp4|webm|mp3|wav|zip|gz)$", re.IGNORECASE)

CHEMINS_A_IGNORER = re.compile(
    r"^/(cdn-cgi|_next/static|_nuxt|static|assets|dist|build|media|"
    r"wp-content|wp-includes|wp-json)/", re.IGNORECASE)

MOTIF_URL = re.compile(rb"https?://[^\s\"'<>\\\x00-\x1f]{12,}")
MOTIF_ANCRE = re.compile(rb'data-n-au="([^"]+)"')
MOTIF_BALISES = re.compile(r"<[^>]+>")


# --------------------------------------------------------------- utilitaires

def sans_accents(s):
    """Normalise pour comparer : minuscules, sans accents."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def identifiant(url):
    """Cle stable derivee de l'URL, pour retrouver une reference d'un jour a l'autre."""
    h = 5381
    s = re.sub(r"^https?://", "", (url or "").strip().lower()).rstrip("/")
    for c in s:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFF
    return "u" + format(h, "x")


def recuperer(url, ua=UA_FLUX, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def texte(noeud, defaut=""):
    return (noeud.text or defaut).strip() if noeud is not None else defaut


def nettoyer(s, limite=320):
    """Retire les balises et resserre les espaces d'un resume de flux."""
    s = MOTIF_BALISES.sub(" ", s or "")
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&#39;", "'"), ("&quot;", '"'), ("&rsquo;", "’")):
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limite].rstrip() + ("…" if len(s) > limite else "")


def dans_le_champ(titre, resume):
    """Vrai si la reference parle bien de santé mentale ou de psychiatrie."""
    hay = sans_accents(titre + " " + resume)
    if EXCLUSIONS.search(hay):
        return False
    return any(m in hay for m in (sans_accents(x) for x in MOTS_DU_CHAMP))


def url_plausible(candidat):
    """Vrai si l'adresse peut etre celle d'un article.

    Le critere est severe : un lien faux est pire qu'un lien non resolu, puisqu'il
    mene le lecteur ailleurs sans prevenir.
    """
    if not candidat or len(candidat) > 2000:
        return False
    try:
        p = urlparse(candidat)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    hote = p.netloc.split("@")[-1].split(":")[0]
    if HOTES_A_IGNORER.search(hote) or "." not in hote:
        return False
    if len(p.path) < 2:
        return False
    if EXTENSIONS_A_IGNORER.search(p.path) or CHEMINS_A_IGNORER.search(p.path):
        return False
    return True


# --------------------------------------------------------- resolution Google

def _chaines_delimitees(blob):
    """Extrait les chaines longueur-prefixee du blob binaire.

    L'identifiant decode est un message au format protobuf : chaque chaine y est
    precedee d'un marqueur puis de sa longueur. Lire cette longueur evite de
    deviner ou l'URL s'arrete, car un octet de structure peut etre un caractere
    parfaitement legal dans une adresse.
    """
    n, i = len(blob), 0
    while i < n:
        if blob[i] & 0x07 == 0x02:
            j, longueur, decalage, complet = i + 1, 0, 0, False
            while j < n and decalage <= 28:
                octet = blob[j]
                j += 1
                longueur |= (octet & 0x7F) << decalage
                if not octet & 0x80:
                    complet = True
                    break
                decalage += 7
            if complet and 0 < longueur <= n - j:
                yield blob[j:j + longueur]
                i = j
                continue
        i += 1


def _par_decodage(lien):
    """Voie 1 : l'identifiant du lien encode parfois l'URL reelle."""
    m = re.search(r"/(?:rss/)?articles/([A-Za-z0-9_\-]+)", lien)
    if not m:
        return None
    brut = m.group(1) + "=" * (-len(m.group(1)) % 4)
    try:
        blob = base64.urlsafe_b64decode(brut)
    except (binascii.Error, ValueError):
        return None

    for morceau in _chaines_delimitees(blob):
        try:
            candidat = morceau.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if candidat.startswith(("http://", "https://")) and url_plausible(candidat):
            return candidat

    for trouve in MOTIF_URL.findall(blob):
        candidat = trouve.decode("utf-8", "ignore").rstrip("\\\u0001\u0002")
        if url_plausible(candidat):
            return candidat
    return None


def _par_page(lien):
    """Voie 2 : la page de redirection porte l'adresse d'origine.

    Seul l'attribut que Google reserve a cet usage est lu. Balayer tout le HTML
    ramene les scripts de mesure d'audience : mieux vaut ne rien resoudre.
    """
    try:
        html = recuperer(lien, ua=UA_PAGE, timeout=20)
    except (urllib.error.URLError, OSError):
        return None
    for trouve in MOTIF_ANCRE.findall(html):
        candidat = trouve.decode("utf-8", "ignore")
        if url_plausible(candidat):
            return candidat
    return None


MOTIF_SIGNATURE = re.compile(rb'data-n-a-sg="([^"]+)"')
MOTIF_HORODATAGE = re.compile(rb'data-n-a-ts="([^"]+)"')
MOTIF_IDENTIFIANT = re.compile(r"/(?:rss/)?articles/([A-Za-z0-9_\-]+)")


def _par_service(lien):
    """Voie 3 : demander l'adresse au service de Google.

    Depuis 2024, l'identifiant d'un article n'encode plus l'adresse : il faut la
    demander. La page de l'article porte une signature et un horodatage, qu'un
    second appel echange contre l'adresse reelle. C'est un service interne, sans
    garantie de stabilite : tout echec rend simplement None.
    """
    m = MOTIF_IDENTIFIANT.search(lien)
    if not m:
        return None
    identifiant_article = m.group(1)

    try:
        page = recuperer(lien, ua=UA_PAGE, timeout=20)
    except (urllib.error.URLError, OSError):
        return None

    sg = MOTIF_SIGNATURE.search(page)
    ts = MOTIF_HORODATAGE.search(page)
    if not sg or not ts:
        return None

    interne = json.dumps([
        "garturlreq",
        [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
          None, None, None, None, None, 0, 1],
         "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
        identifiant_article,
        int(ts.group(1).decode()),
        sg.group(1).decode(),
    ], separators=(",", ":"))

    corps = urllib.parse.urlencode({
        "f.req": json.dumps([[["Fbv4je", interne, None, "generic"]]],
                            separators=(",", ":"))
    }).encode()

    requete = urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=corps,
        headers={"User-Agent": UA_PAGE,
                 "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=20) as r:
            reponse = r.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError):
        return None

    for trouve in MOTIF_URL.findall(reponse.encode("utf-8", "ignore")):
        candidat = trouve.decode("utf-8", "ignore").rstrip('\\"')
        if url_plausible(candidat):
            return candidat
    return None


def resoudre(lien, compteur=None):
    """Rend (url, resolu). Conserve le lien d'origine si la resolution echoue.

    `compteur` est une liste d'un entier : le nombre d'echecs consecutifs. Au-dela
    de ECHECS_AVANT_ABANDON, la resolution est abandonnee pour le reste du
    passage, pour ne pas allonger l'execution sans profit.
    """
    if "news.google.com" not in lien:
        return lien, True
    if compteur is not None and compteur[0] >= ECHECS_AVANT_ABANDON:
        return lien, False

    for voie in (_par_decodage, _par_service, _par_page):
        try:
            trouve = voie(lien)
        except Exception as e:
            print("resolution ({}) : {}".format(voie.__name__, e), file=sys.stderr)
            trouve = None
        if trouve:
            if compteur is not None:
                compteur[0] = 0
            return trouve, True

    if compteur is not None:
        compteur[0] += 1
        if compteur[0] == ECHECS_AVANT_ABANDON:
            print("resolution abandonnee pour ce passage apres {} echecs consecutifs"
                  .format(ECHECS_AVANT_ABANDON), file=sys.stderr)
    return lien, False


# --------------------------------------------------------------- lecture flux

def _date_item(item):
    for balise in ("pubDate", "published", "updated",
                   "{http://www.w3.org/2005/Atom}published",
                   "{http://www.w3.org/2005/Atom}updated"):
        brut = texte(item.find(balise))
        if not brut:
            continue
        try:
            d = parsedate_to_datetime(brut)
        except (TypeError, ValueError):
            try:
                d = datetime.fromisoformat(brut.replace("Z", "+00:00"))
            except ValueError:
                continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    return None


def _lien_item(item):
    lien = texte(item.find("link"))
    if lien:
        return lien
    for a in item.findall("{http://www.w3.org/2005/Atom}link"):
        rel = a.get("rel") or "alternate"
        if rel == "alternate" and a.get("href"):
            return a.get("href")
    return ""


def _resume_item(item):
    for balise in ("description", "summary",
                   "{http://www.w3.org/2005/Atom}summary",
                   "{http://www.w3.org/2005/Atom}content",
                   "{http://purl.org/rss/1.0/modules/content/}encoded"):
        brut = texte(item.find(balise))
        if brut:
            return nettoyer(brut)
    return ""


def parser_flux(xml_bytes, cle, google):
    """Rend la liste des references d'un flux RSS ou Atom."""
    racine = ElementTree.fromstring(xml_bytes)
    items = list(racine.iter("item")) or \
        list(racine.iter("{http://www.w3.org/2005/Atom}entry"))

    sortie = []
    for item in items:
        titre = texte(item.find("title")) or \
            texte(item.find("{http://www.w3.org/2005/Atom}title"))
        lien = _lien_item(item)
        if not titre or not lien:
            continue

        source = texte(item.find("source"))
        resume = "" if google else _resume_item(item)

        if google:
            # Google Actualites suffixe le titre par « - Nom du media ».
            if source and titre.endswith(" - " + source):
                titre = titre[: -(len(source) + 3)].strip()
            elif " - " in titre:
                titre, _, suffixe = titre.rpartition(" - ")
                titre, source = titre.strip(), suffixe.strip()
        elif not source:
            source = urlparse(lien).netloc.replace("www.", "")

        horodatage = _date_item(item)
        sortie.append({
            "id": identifiant(lien),
            "title": titre,
            "url": lien,
            "source": source,
            "published": horodatage.date().isoformat() if horodatage else "",
            "summary": resume,
            "feed": cle,
            "_ts": horodatage,
        })
    return sortie


def charger_archive():
    if not os.path.exists(ARCHIVE):
        return {"jours": []}
    try:
        with open(ARCHIVE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("jours"), list):
            return data
    except (ValueError, OSError) as e:
        print("archive illisible, on repart a zero : {}".format(e), file=sys.stderr)
    return {"jours": []}


# --------------------------------------------------------------- programme

def main():
    maintenant = datetime.now(timezone.utc)
    aujourdhui = maintenant.date().isoformat()
    limite = maintenant - timedelta(days=FENETRE_JOURS)

    sources_a_lire = (
        [(cle,
          gabarit.format(quote(requete + " " + FENETRE_GOOGLE, safe="")),
          requete, True)
         for cle, gabarit, requete in REQUETES] +
        [(cle, url, "", False) for cle, url in FLUX_DIRECTS]
    )

    collectes, rapport = [], []
    for cle, url, requete, google in sources_a_lire:
        try:
            items = parser_flux(recuperer(url), cle, google)
            etat = "ok"
        except (urllib.error.URLError, ElementTree.ParseError, OSError) as e:
            items, etat = [], "echec: {}".format(e)
            print("source {} : {}".format(cle, etat), file=sys.stderr)

        retenus, hors_champ, hors_fenetre = 0, 0, 0
        for it in items:
            if retenus >= MAX_PAR_SOURCE:
                break
            if it["_ts"] and it["_ts"] < limite:
                hors_fenetre += 1
                continue
            if not dans_le_champ(it["title"], it["summary"]):
                hors_champ += 1
                continue
            collectes.append(it)
            retenus += 1

        rapport.append({
            "cle": cle, "type": "google" if google else "rss",
            "requete": requete, "etat": etat, "bruts": len(items),
            "retenus": retenus, "hors_champ": hors_champ,
            "hors_fenetre": hors_fenetre,
        })

    # --- dedoublonnage interne ---
    vus_id, vus_titre, frais = set(), set(), []
    for it in sorted(collectes, key=lambda x: x["_ts"] or maintenant, reverse=True):
        cle_titre = re.sub(r"[^a-z0-9]+", "", sans_accents(it["title"]))[:90]
        if it["id"] in vus_id or (cle_titre and cle_titre in vus_titre):
            continue
        vus_id.add(it["id"])
        vus_titre.add(cle_titre)
        it.pop("_ts", None)
        frais.append(it)

    # --- fusion dans l'archive ---
    archive = charger_archive()
    jours = {j["date"]: j for j in archive["jours"]
             if isinstance(j, dict) and j.get("date")}

    connus, titres_connus = set(), set()
    for j in jours.values():
        for it in j.get("items", []):
            connus.add(it.get("id") or identifiant(it.get("url", "")))
            titres_connus.add(
                re.sub(r"[^a-z0-9]+", "", sans_accents(it.get("title", "")))[:90])

    # Reparation des resolutions erronees laissees par une version anterieure.
    reparees = 0
    for j in jours.values():
        for it in j.get("items", []):
            lien = it.get("url", "")
            if not lien or "news.google.com" in lien or url_plausible(lien):
                continue
            if it.get("gnews"):
                it["url"], it["gnews"] = it["gnews"], ""
            it["resolu"] = False
            reparees += 1

    jour = jours.setdefault(aujourdhui, {"date": aujourdhui, "items": []})
    jour.setdefault("items", [])
    deja = {it.get("id") for it in jour["items"]}

    nouveaux, resolus, echecs_suite = [], 0, [0]
    for it in frais:
        cle_titre = re.sub(r"[^a-z0-9]+", "", sans_accents(it["title"]))[:90]
        if it["id"] in connus or it["id"] in deja:
            continue
        if cle_titre and cle_titre in titres_connus:
            continue

        url_finale, ok = resoudre(it["url"], echecs_suite)
        if ok and url_finale != it["url"]:
            resolus += 1

        entree = {
            "id": it["id"],
            "title": it["title"],
            "url": url_finale,
            "gnews": it["url"] if url_finale != it["url"] else "",
            "resolu": bool(ok),
            "source": it["source"],
            "published": it["published"],
            "summary": it["summary"],
            "feed": it["feed"],
        }
        jour["items"].append(entree)
        nouveaux.append(entree)
        connus.add(it["id"])
        if cle_titre:
            titres_connus.add(cle_titre)

    # --- nouvelle tentative sur les anciens liens opaques ---
    rattrapes, budget = 0, RETENTATIVES_RESOLUTION
    for d in sorted(jours, reverse=True):
        for it in jours[d].get("items", []):
            if budget <= 0:
                break
            if it.get("resolu"):
                continue
            lien = it.get("gnews") or it.get("url", "")
            if "news.google.com" not in lien:
                it["resolu"] = True
                continue
            budget -= 1
            url_finale, ok = resoudre(lien, echecs_suite)
            if ok and url_finale != lien:
                it["gnews"], it["url"], it["resolu"] = lien, url_finale, True
                rattrapes += 1
        if budget <= 0:
            break

    jour["collecte"] = maintenant.isoformat(timespec="seconds")
    jour["sources"] = [{"cle": r["cle"], "etat": r["etat"], "retenus": r["retenus"]}
                       for r in rapport]

    # --- ecriture ---
    with open(BRUT, "w", encoding="utf-8") as f:
        json.dump({"genere": maintenant.isoformat(timespec="seconds"),
                   "fenetre_jours": FENETRE_JOURS,
                   "sources": rapport,
                   "nouveaux": len(nouveaux),
                   "items": nouveaux},
                  f, ensure_ascii=False, indent=1)

    plancher = (maintenant - timedelta(days=ARCHIVE_JOURS)).date().isoformat()
    liste = sorted((j for d, j in jours.items() if d >= plancher),
                   key=lambda j: j["date"], reverse=True)
    total = sum(len(j.get("items", [])) for j in liste)
    opaques = sum(1 for j in liste for it in j.get("items", [])
                  if not it.get("resolu"))

    with open(ARCHIVE, "w", encoding="utf-8") as f:
        json.dump({"maj": maintenant.isoformat(timespec="seconds"),
                   "jours_couverts": len(liste), "total": total,
                   "liens_non_resolus": opaques, "jours": liste},
                  f, ensure_ascii=False, indent=1)

    echecs = [r["cle"] for r in rapport if r["etat"] != "ok"]
    print("{} nouvelle(s) reference(s) ; {} lien(s) resolu(s), {} rattrape(s), "
          "{} repare(s) ; archive : {} references sur {} jours, {} lien(s) opaque(s)"
          .format(len(nouveaux), resolus, rattrapes, reparees,
                  total, len(liste), opaques))
    print("sources en echec : {}".format(", ".join(echecs) if echecs else "aucune"))
    for r in rapport:
        print("  {:22s} {:7s} {:>4} bruts  {:>3} retenus  "
              "{:>3} hors champ  {:>3} hors fenetre   {}"
              .format(r["cle"], r["type"], r["bruts"], r["retenus"],
                      r["hors_champ"], r["hors_fenetre"],
                      r["etat"] if r["etat"] != "ok" else ""))


if __name__ == "__main__":
    main()
