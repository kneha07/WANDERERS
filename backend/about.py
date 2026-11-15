"""'About this star': what the catalogs know about an object, in plain words.

GET /api/about?q=<name> or ?ra=&dec= -> catalog facts from CDS Sesame (SIMBAD by position first, for coordinates)
and one history sentence quoted from Wikipedia. No language model writes these facts: every word of
facts_sentence comes from a catalog value, and history_sentence is a quoted Wikipedia sentence (CC BY-SA 4.0).
Each source can be missing; the answer then says so in notes. Cached on disk for 30 days (not when a source failed).
"""
import hashlib
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from urllib.parse import quote

import requests
from astropy.coordinates import SkyCoord
from fastapi import HTTPException

from backend import spherex
from backend.spherex import read_cache, sesame_resolver, write_json

CACHE_DIR = spherex.CACHE_DIR
ABOUT_VERSION, ABOUT_MAX_AGE_S = 2, 30 * 86400  # version 2: position answers have fast_movers
ABOUT_DEGRADED_AGE_S = 3600  # a position answer whose fast-mover search failed is rebuilt after an hour
# -oxpI: XML with proper motion, parallax, spectral type, number of papers (nrefs) and all identifiers (aliases).
SESAME_FULL = tuple(u.replace("/-oxp/", "/-oxpI/") for u in spherex.SESAME_URLS)
SIMBAD_TAP = ("https://simbad.cds.unistra.fr/simbad/sim-tap/sync", "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync")
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
UA = {"User-Agent": "WANDERERS-hackathon/0.1 (https://github.com/kneha07/WANDERERS)"}  # no e-mail address
CONE_ARCSEC, TIMEOUT_S = 5, 8
TIE_ARCSEC = 1  # objects this close to the nearest one count as the same place (a star and its components)
PLANET_TYPES = {"Pl"}  # SIMBAD's planet type ("Pl?": planet candidate)
FAST_MAS_YR = 1000  # a proper motion above 1"/yr moves a star out of the 5" cone between J2000 and now
FAST_SEARCH_ARCSEC, FAST_NEAR_ARCSEC = 300, 60  # fast movers within 300" whose path passes within 60" (NM2)
FAST_HERE_ARCSEC = 5  # no hint when the typed position is where the star is now
FAST_TIMEOUT_S = 6  # the fast-mover search runs next to the other lookups and gets at most this long
_pool = ThreadPoolExecutor(4, thread_name_prefix="about")  # shared: a slow search finishes on its own after the cap
# Identifiers worth showing, in this order (SIMBAD lists 50 or more for a famous star).
ALIAS_ORDER = ("NAME ", "HD ", "HIP ", "GJ ", "2MASS ", "Gaia DR3 ", "WISEA ", "LHS ", "TYC ")

# SIMBAD object types (https://simbad.cds.unistra.fr/guide/otypes.htx) that say more than the spectral type.
OTYPES = {
    "TT*": "young T Tauri star", "Y*O": "young stellar object", "Ae*": "young Herbig Ae/Be star", "Or*": "young variable star",
    "Mi*": "Mira variable, a pulsating red giant", "LP*": "long-period variable star", "C*": "carbon star", "S*": "S-type star",
    "AB*": "asymptotic giant branch star", "Ce*": "Cepheid variable", "cC*": "Cepheid variable", "RR*": "RR Lyrae variable",
    "BD*": "brown dwarf", "WD*": "white dwarf", "N*": "neutron star", "Psr": "pulsar", "Pl": "planet",
    "EB*": "eclipsing binary star", "SB*": "spectroscopic binary star", "**": "double or multiple star",
    "CV*": "cataclysmic variable", "No*": "nova", "SN*": "supernova", "WR*": "Wolf-Rayet star", "Be*": "Be star",
    "G": "galaxy", "QSO": "quasar", "AGN": "active galactic nucleus", "Sy1": "Seyfert galaxy", "Sy2": "Seyfert galaxy",
    "GlC": "globular star cluster", "OpC": "open star cluster", "Cl*": "star cluster", "PN": "planetary nebula",
    "HII": "glowing hydrogen cloud (HII region)", "SNR": "supernova remnant", "MoC": "molecular cloud", "DNe": "dark nebula",
}
# Types that only say "a star" (or how it varies); then the spectral type says what kind of star it is.
STARLIKE = {"*", "PM*", "HV*", "BY*", "V*", "Er*", "Ro*", "Fl*", "Pu*", "Ir*", "Em*", "MS*", "LM*", "RS*", "El*", "dS*",
            "gD*", "RG*", "Ev*", "HB*", "SX*", "Ma*", "sg*", "OH*"}
COLOUR = {"O": "blue", "B": "blue-white", "A": "white", "F": "yellow-white", "G": "yellow", "K": "orange", "M": "red"}
SPECTRAL = re.compile(r"(esd|usd|sd|d)?([OBAFGKM])[\d.]*(?:[-/][\d.]*)?\s*(Ia|Iab|Ib|III|II|IV|VI|V|I)?")
LY_PER_MAS = 3261.56  # light-years for a parallax of 1 mas
HISTORY_VERB = re.compile(r"\b(discover\w*|found|identified|detected|named|designated|catalogu?ed|measured|observed|"
                          r"announced|recorded|noted|confirmed|classified|reported)\b", re.I)
YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
# A sentence ends at . ! ? and a space before anything but a small letter (a capital, a digit, "ε Indi"), but not
# after an initial ("E. E. Barnard") or "St." and the like.
SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\b[A-Z]\.)(?<!\b(?:St|Dr|No|vs|ca)\.)\s+(?=[^a-z\s])")
PREFIX = re.compile(r"^(NAME|V\*|\*\*|\*)\s+")  # SIMBAD name prefixes: "NAME Barnard's star", "V* R Dra", "* eps Ind B"


def star_kind(sp):
    """Plain words for a spectral type: 'M4V' -> 'red dwarf', 'K0III' -> 'orange giant'. None if it does not say."""
    if not sp:
        return None
    if re.match(r"[LTY]\d", sp):
        return "brown dwarf"
    if re.match(r"D[ABCOQZX]", sp):
        return "white dwarf"
    m = SPECTRAL.match(sp)
    if not m:
        return None
    colour, lum = COLOUR[m[2]], "VI" if m[1] in ("sd", "esd", "usd") else "V" if m[1] == "d" else m[3]
    if lum == "VI":
        return f"{colour} subdwarf"
    if lum == "V":
        return f"{colour} dwarf" if m[2] in "GKM" else f"{colour} main-sequence star"
    if lum in ("III", "IV"):
        return f"{colour} {'giant' if lum == 'III' else 'subgiant'}"
    if lum:
        return f"{colour} {'bright giant' if lum == 'II' else 'supergiant'}"
    return f"{colour} star"


def object_kind(otype, sp):
    """SIMBAD object type and spectral type -> plain words ('red dwarf', 'young T Tauri star'), or None if unknown."""
    base, candidate = (otype or "").removesuffix("?"), (otype or "").endswith("?")
    if candidate and base + "*" in OTYPES.keys() | STARLIKE:  # a candidate swaps the "*" for "?": BD* -> BD?
        base += "*"
    if base in OTYPES:
        words = OTYPES[base]
    elif base in STARLIKE or (not base and sp):
        words = star_kind(sp) or "star"
    else:
        return None
    return f"{words} candidate" if candidate else words


def distance_ly(plx, err):
    """Distance in light-years from a parallax in mas, only when the parallax is measured to 5 sigma or better."""
    if plx is None or plx <= 0 or (err is not None and plx < 5 * err):
        return None
    return LY_PER_MAS / plx


def light_years(d):
    """6.0, 41, 210, 2,600: one decimal near the Sun, then whole numbers, then two significant figures."""
    if d < 20:
        return f"{d:.1f}"
    if d < 100:
        return f"{d:.0f}"
    return f"{float(f'{d:.2g}'):,.0f}"


def facts_sentence(name, kind, sp, dist):
    """One sentence from catalog values only, e.g. "Barnard's Star is a red dwarf (spectral type M4V) about 6.0
    light-years away." Unknown parts are left out; None when nothing is known."""
    if not kind and sp:
        kind = "star"
    parts = []
    if kind:
        parts.append(f"{'an' if kind[0] in 'aeiou' else 'a'} {kind}")
    if sp:
        parts.append(f"(spectral type {sp})")
    if dist:
        parts.append(f"about {light_years(dist)} light-years away")
    return f"{name} is {' '.join(parts)}." if parts else None


def history_sentence(extract):
    """The first sentence of a Wikipedia summary that tells a discovery, naming or measurement with a year, or None."""
    for s in SENTENCE_END.split(extract or ""):
        s = s.strip()
        if HISTORY_VERB.search(s) and YEAR.search(s) and len(s.split()) <= 45:
            return s
    return None


def plain_name(name):
    """'NAME Barnard's star' -> "barnard's star": SIMBAD prefixes, spacing, case and the Unicode minus do not count."""
    return " ".join(PREFIX.sub("", name).replace("\u2212", "-").split()).casefold()


def page_is_about(page, names, constellation):
    """True if a Wikipedia summary is clearly about this object: not a disambiguation page, and its title is one of the
    object's names, or its text has one of them, or it places the object in its constellation ("RW Aur" -> the page
    "RW Aurigae ... in the constellation Auriga")."""
    if page.get("type") != "standard":
        return False
    keys = {plain_name(n) for n in names if n}
    text = plain_name(f"{page.get('description') or ''} {page.get('extract') or ''}")
    if plain_name(page.get("title") or "") in keys:
        return True
    if any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text) for k in keys if len(k) > 3):
        return True
    return bool(constellation) and re.search(rf"\bconstellation (of )?{re.escape(constellation.casefold())}\b", text) is not None


def simbad_url(host, ident):
    """SIMBAD's page for an identifier, on the host that answered (CDS or its CfA mirror)."""
    base = "https://simbad.cfa.harvard.edu" if "harvard" in (host or "") else "https://simbad.cds.unistra.fr"
    return f"{base}/simbad/sim-id?Ident={quote(ident)}"


def catalog_facts(name):
    """CDS Sesame facts for a name: dict, or None if no mirror knows it. HTTPException(502) if Sesame fails."""
    hit = sesame_resolver(name, SESAME_FULL)
    if hit is None:
        return None
    def num(path):
        try:
            return float(hit.findtext(path))
        except (TypeError, ValueError):
            return None
    nrefs = hit.findtext("nrefs") or ""
    return {"main_id": " ".join((hit.findtext("oname") or name).split()), "otype": hit.findtext("otype"),
            "sp": (hit.findtext("spType") or "").strip() or None, "plx": num("plx/v"), "plx_err": num("plx/e"),
            "ra": num("jradeg"), "dec": num("jdedeg"), "papers": int(nrefs) if nrefs.isdigit() else None,
            "aliases": [" ".join(a.text.split()) for a in hit.findall("alias") if a.text], "mirror": hit.get("mirror")}


def pick_object(rows):
    """The object that a position means, from SIMBAD rows [main_id, otype, nbref, distance in degrees], or None.

    SIMBAD gives a planet its star's position (Barnard's Star c sits at Barnard's Star), so a plain nearest-first pick
    can name the planet. A planet counts only when nothing else is in the cone; among the objects within 1" of the
    nearest one, the most studied wins (a star before its components).
    """
    others = [r for r in rows if (r[1] or "").rstrip("?") not in PLANET_TYPES]
    rows = others or rows
    if not rows:
        return None
    nearest = min(r[3] for r in rows)
    return max((r for r in rows if r[3] - nearest <= TIE_ARCSEC / 3600), key=lambda r: r[2] or 0)[0]


def j2000(ra, dec, pmra, pmdec, epoch):
    """A position at epoch (Julian year) moved back to J2000 by its proper motion (mas/yr; pmra includes cos dec).
    SIMBAD lists positions at J2000, so a fast mover is found there, not where it is now."""
    years = 2000.0 - epoch
    dec0 = dec + pmdec * years / 3.6e6
    return (ra + pmra * years / 3.6e6 / math.cos(math.radians(dec))) % 360, dec0


def path_near(ra0, dec0, pmra, pmdec, ra, dec):
    """How near the path of a star (J2000 position ra0, dec0, proper motion in mas/yr) passes ra, dec between 1990 and
    2030, and how far it is from ra, dec in 2026.0: (closest, now) in arcsec. Flat sky: good to ~0.1" over 300"."""
    dx = ((ra - ra0 + 180) % 360 - 180) * math.cos(math.radians(dec0)) * 3600  # east of the star, arcsec
    dy = (dec - dec0) * 3600
    vx, vy = pmra / 1000, pmdec / 1000  # arcsec per year
    t = max(-10.0, min(30.0, (dx * vx + dy * vy) / (vx * vx + vy * vy)))  # years after 2000 of the closest point
    return math.hypot(dx - vx * t, dy - vy * t), math.hypot(dx - vx * 26, dy - vy * 26)


def fast_movers(ra, dec):
    """SIMBAD stars faster than 1"/yr whose path (1990-2030) passes within FAST_NEAR_ARCSEC of ra, dec: typed
    coordinates from an old catalogue can be where such a star was, not where it is. [{name, pm_arcsec_yr,
    sep_arcsec (in 2026)}], nearest path first, without a star that is now within FAST_HERE_ARCSEC (the position is
    already right). None when SIMBAD does not answer: unknown, not "no fast mover"."""
    query = (f"SELECT TOP 20 main_id, ra, dec, pmra, pmdec FROM basic WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), "
             f"CIRCLE('ICRS', {ra}, {dec}, {FAST_SEARCH_ARCSEC / 3600})) AND pmra * pmra + pmdec * pmdec > {FAST_MAS_YR ** 2}")
    for url in SIMBAD_TAP:
        try:
            r = requests.get(url, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query},
                             headers=UA, timeout=TIMEOUT_S)
            r.raise_for_status()
            rows = r.json()["data"]
        except (requests.RequestException, ValueError, KeyError, TypeError):
            continue
        near = []
        for row in rows:
            try:
                name, ra0, dec0, pmra, pmdec = row
                closest, now = path_near(ra0, dec0, pmra, pmdec, ra, dec)
            except (ValueError, TypeError, ZeroDivisionError):  # a row without a full position or motion
                continue
            if closest <= FAST_NEAR_ARCSEC and now > FAST_HERE_ARCSEC:
                near.append((closest, {"name": PREFIX.sub("", " ".join(name.split())),
                                       "pm_arcsec_yr": round(math.hypot(pmra, pmdec) / 1000, 2), "sep_arcsec": round(now)}))
        return [f for _, f in sorted(near, key=lambda c: c[0])]
    return None


def simbad_near(ra, dec):
    """(main identifier or None, host) of the SIMBAD object that ra, dec means, within CONE_ARCSEC (pick_object).
    HTTPException(502) when no SIMBAD TAP host answers."""
    query = (f"SELECT TOP 20 main_id, otype, nbref, DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', {ra}, {dec})) AS d "
             f"FROM basic WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {CONE_ARCSEC / 3600})) "
             "ORDER BY d")
    for url in SIMBAD_TAP:
        try:
            r = requests.get(url, params={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": query},
                             headers=UA, timeout=TIMEOUT_S)
            r.raise_for_status()
            rows = r.json()["data"]
        except (requests.RequestException, ValueError, KeyError, TypeError):
            continue
        return pick_object(rows), url.split("/")[2]
    raise HTTPException(502, "SIMBAD did not answer")


def wiki_page(title):
    """Wikipedia REST summary of a page (redirects followed), or None when there is no such page."""
    r = requests.get(WIKI_SUMMARY + quote(title.replace(" ", "_"), safe=""), headers=UA, timeout=TIMEOUT_S)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def wiki_history(titles, names, constellation):
    """The first Wikipedia page about the object, trying titles in order: (page or None, failed)."""
    for title in titles:
        try:
            page = wiki_page(title)
        except (requests.RequestException, ValueError):
            return None, True
        if page and page_is_about(page, names, constellation):
            return page, False
    return None, False


def pick_aliases(aliases, shown):
    """Up to 5 identifiers that a reader can look up: common names first, then the big catalogs."""
    out = []
    for prefix in ALIAS_ORDER:
        for a in aliases:
            b = a.removeprefix("NAME ")
            if a.startswith(prefix) and plain_name(b) != plain_name(shown) and b not in out:
                out.append(b)
    return out[:5]


def build_about(q, ra, dec, pm=None, epoch=None):
    """(answer, failed): failed is True when a source did not answer (the answer is then not cached).
    pm (pmra, pmdec in mas/yr) and epoch (Julian year of ra, dec): a fast mover is also looked for at J2000."""
    notes, sources, failed, name = [], [], False, q
    # The fast-mover hint runs next to the other lookups, so it adds at most FAST_TIMEOUT_S to a position answer.
    movers, t0 = (_pool.submit(fast_movers, ra, dec), time.monotonic()) if q is None else (None, None)
    if q is None:
        try:
            fast = bool(pm) and epoch is not None and math.hypot(*pm) > FAST_MAS_YR
            if fast:  # SIMBAD positions are J2000: look where the fast mover was then
                name, host = simbad_near(*j2000(ra, dec, *pm, epoch))
            if not fast or name is None:
                name, host = simbad_near(ra, dec)
        except HTTPException:
            failed = True
            notes.append("SIMBAD did not answer, so the object at this position is not known here.")
        else:
            if name is None:
                notes.append(f"SIMBAD lists no object within {CONE_ARCSEC}″ of this position.")
            base = "https://simbad.cfa.harvard.edu" if "harvard" in host else "https://simbad.cds.unistra.fr"
            sources.append({"label": "SIMBAD, objects near this position",
                            "url": f"{base}/simbad/sim-coo?Coord={quote(f'{ra} {dec}')}&Radius={CONE_ARCSEC}&Radius.unit=arcsec"})
    facts = None
    if name:
        try:
            facts = catalog_facts(name)
        except HTTPException:
            failed = True
            notes.append("CDS Sesame did not answer, so the catalog facts are missing. Try again later.")
        else:
            if facts is None:
                notes.append(f"CDS Sesame does not know '{name}'.")
    shown, page, kind, dist = (q or PREFIX.sub("", name)) if name else None, None, None, None
    if facts:
        names = [q, facts["main_id"], *facts["aliases"]]
        titles = list({plain_name(t): t for t in [q, PREFIX.sub("", facts["main_id"]),
                                                  *(a[5:] for a in facts["aliases"] if a.startswith("NAME "))] if t}.values())[:4]
        where = SkyCoord(facts["ra"], facts["dec"], unit="deg").get_constellation() if facts["ra"] is not None else None
        page, wiki_failed = wiki_history(titles, names, where)
        if wiki_failed:
            failed = True
            notes.append("Wikipedia did not answer, so the history is missing.")
        if page and plain_name(page["title"]) in {plain_name(n) for n in names if n}:
            shown = page["title"]  # Wikipedia writes names with proper capitals ("Barnard's Star")
        kind, dist = object_kind(facts["otype"], facts["sp"]), distance_ly(facts["plx"], facts["plx_err"])
        sources.insert(0, {"label": "CDS Sesame / SIMBAD", "url": simbad_url(facts["mirror"], facts["main_id"])})
    page_url = page and (page.get("content_urls") or {}).get("desktop", {}).get("page")
    history = history_sentence(page.get("extract")) if page else None
    if page:
        sources.append({"label": f"Wikipedia: {page['title']}", "url": page_url})
    fast = []
    if movers is not None:
        try:
            fast = movers.result(timeout=max(0.0, FAST_TIMEOUT_S - (time.monotonic() - t0)))
        except FuturesTimeout:
            fast = None
        if fast is None:
            notes.append("The search for fast-moving stars near this position did not finish, so that hint is missing.")
    return {
        "name": shown,
        "object_type": kind,
        "spectral_type": facts and facts["sp"],
        "distance_ly": round(dist, 2) if dist else None,
        "aliases": pick_aliases(facts["aliases"], shown) if facts else [],
        "facts_sentence": facts_sentence(shown, kind, facts["sp"], dist) if facts else None,
        "history_sentence": history,
        "history_source": {"title": page["title"], "url": page_url, "license": "CC BY-SA 4.0"} if history else None,
        "papers": facts and facts["papers"],
        "sources": sources,
        "notes": notes,
        "fast_movers": fast,  # None: the search failed (the answer is then kept one hour only)
    }, failed


def get_about(q=None, ra=None, dec=None, pmra=None, pmdec=None, epoch=None):
    """GET /api/about: by name (q) or by position (ra, dec in degrees, at epoch with proper motion pmra, pmdec when
    known). Served from the disk cache for 30 days, or one hour when the fast-mover search failed."""
    pm = (pmra, pmdec) if pmra is not None and pmdec is not None else None
    key = (["q", " ".join(q.split()).casefold()] if q is not None
           else ["pos", round(ra, 5), round(dec, 5), pm and [round(pm[0]), round(pm[1])], epoch])
    path = CACHE_DIR / f"about-{hashlib.sha256(json.dumps([ABOUT_VERSION, *key]).encode()).hexdigest()[:32]}.json"
    cached, age = read_cache(path)
    if cached is not None and age <= (ABOUT_MAX_AGE_S if cached.get("fast_movers") is not None else ABOUT_DEGRADED_AGE_S):
        return cached
    answer, failed = build_about(q, ra, dec, pm, epoch)
    if not failed:  # a missing source is tried again on the next request
        write_json(path, answer)
    return answer
