"""'About this star' (backend/about.py): catalog facts in words, one Wikipedia history sentence. No network."""
import math
import os
import time

import pytest

from backend import about


@pytest.mark.parametrize("otype, sp, words", [
    ("BY*", "M4V", "red dwarf"),  # Barnard's Star: the type says "variable", the spectral type says what it is
    ("PM*", "M1VIp", "red subdwarf"),  # Kapteyn's Star: VI is a subdwarf
    ("PM*", "dM6", "red dwarf"),  # Wolf 359: the old "d" prefix
    ("*", "G2V", "yellow dwarf"),
    ("*", "K0III", "orange giant"),
    ("TT*", "K1/5e+K5e", "young T Tauri star"),  # RW Aur
    ("Mi*", "M4.5-6+e", "Mira variable, a pulsating red giant"),  # R Dra
    ("BD*", "T1V+T6V", "brown dwarf"),  # eps Ind B
    ("BD?", None, "brown dwarf candidate"),
    ("*", None, "star"),
    ("G", None, "galaxy"),
    ("zz*", None, None),  # a code it does not know: say nothing rather than guess
])
def test_object_types_in_plain_words(otype, sp, words):
    assert about.object_kind(otype, sp) == words


def test_facts_sentence_from_catalog_values():
    assert (about.facts_sentence("Barnard's Star", "red dwarf", "M4V", 5.963)
            == "Barnard's Star is a red dwarf (spectral type M4V) about 6.0 light-years away.")


@pytest.mark.parametrize("parts, sentence", [
    (("RW Aur", "young T Tauri star", "K1/5e+K5e", None), "RW Aur is a young T Tauri star (spectral type K1/5e+K5e)."),
    (("R Dra", "Mira variable, a pulsating red giant", None, 2607.0), "R Dra is a Mira variable, a pulsating red giant about 2,600 light-years away."),
    (("X", "orange dwarf", None, 41.2), "X is an orange dwarf about 41 light-years away."),
    (("X", None, "kA2hA5mA7V", None), "X is a star (spectral type kA2hA5mA7V)."),
    (("X", None, None, 211.5), "X is about 210 light-years away."),
    (("X", None, None, None), None),
])
def test_facts_sentence_skips_what_is_unknown(parts, sentence):
    assert about.facts_sentence(*parts) == sentence


def test_distance_only_from_a_parallax_measured_to_5_sigma():
    assert about.distance_ly(546.9759, 0.0401) == pytest.approx(5.963, abs=0.001)  # Barnard's Star
    assert about.distance_ly(15.42, 3.69) is None  # RW Aur in SIMBAD: 4 sigma, so no distance
    assert about.distance_ly(-0.5, 0.3) is None


@pytest.mark.parametrize("extract, sentence", [
    # Shortened Wikipedia summaries (CC BY-SA 4.0) of the challenge targets.
    ("RW Aurigae is a young binary system in the constellation of Auriga. RW Aurigae B was discovered in 1944.",
     "RW Aurigae B was discovered in 1944."),
    ("Epsilon Indi is a star system in Indus. It has an orange hue. The brown dwarfs were discovered in 2003. More text.",
     "The brown dwarfs were discovered in 2003."),
    ("It is named after E. E. Barnard, who measured its motion in 1916. It is a red dwarf.",
     "It is named after E. E. Barnard, who measured its motion in 1916."),
    ("Barnard's Star is a small red dwarf. At a distance of 5.96 light-years it is the fourth-nearest star.", None),
    ("A planet was found around it.", None),  # a discovery verb but no year
    ("The brown dwarfs were discovered in 2003. ε Indi Ba is an early T dwarf.",  # a sentence can start with a Greek letter
     "The brown dwarfs were discovered in 2003."),
])
def test_history_sentence_is_the_first_with_a_discovery_verb_and_a_year(extract, sentence):
    assert about.history_sentence(extract) == sentence


NAMES = ["RW Aur", "V* RW Aur", "HD 240764"]


@pytest.mark.parametrize("page, ok", [
    ({"type": "standard", "title": "RW Aurigae", "description": "Young binary star system in the constellation Auriga",
      "extract": "RW Aurigae is a young binary system."}, True),  # the constellation of the object
    ({"type": "standard", "title": "RW Aur", "description": "", "extract": ""}, True),  # the title is a name
    ({"type": "standard", "title": "Something", "description": "", "extract": "Also known as HD 240764, it is young."}, True),
    ({"type": "disambiguation", "title": "RW Aur", "description": "", "extract": ""}, False),
    ({"type": "standard", "title": "Eagle", "description": "Bird of prey", "extract": "Eagles are large birds."}, False),
])
def test_a_wikipedia_page_is_used_only_when_it_is_about_this_object(page, ok):
    assert about.page_is_about(page, NAMES, "Auriga") is ok


# ---- get_about with the network faked: CDS Sesame (-oxpI), SIMBAD TAP and the Wikipedia summary API ----

BARNARD_XML = """<?xml version="1.0"?><Sesame><Target><name>Barnard's Star</name><Resolver name="Sc=Simbad">
<otype>BY*</otype><jradeg>269.45207696</jradeg><jdedeg>4.69336497</jdedeg>
<pm><pmRA>-801.551</pmRA><pmDE>10362.394</pmDE></pm><plx><v>546.9759</v><e>0.0401</e></plx>
<spType>M4V</spType><oname>NAME Barnard's star</oname><alias>BD+04 3561a</alias><alias>GJ 699</alias>
<alias>HIP 87937</alias><alias>NAME Barnard's star</alias><alias>NAME Barnard Star</alias>
<alias>2MASS J17574849+0441405</alias><alias>Gaia DR3 4472832130942575872</alias><alias>V* V2500 Oph</alias>
<nrefs>924</nrefs></Resolver></Target></Sesame>"""
BARNARD_PAGE = {"type": "standard", "title": "Barnard's Star", "description": "Red dwarf star in the constellation Ophiuchus",
                "extract": "Barnard's Star is a small red dwarf. It is named after E. E. Barnard, who measured its motion in 1916.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Barnard%27s_Star"}}}


class Answer:
    def __init__(self, status=200, content=b"", data=None):
        self.status_code, self.ok, self.content, self.data = status, status < 400, content, data

    def json(self):
        return self.data

    def raise_for_status(self):
        if not self.ok:
            raise about.requests.HTTPError(str(self.status_code))


@pytest.fixture
def net(tmp_path, monkeypatch):
    """Fake services: a dict of URL part -> answer, an exception to raise, or a function (params -> answer).
    Records the URLs asked."""
    services, asked = {}, []
    def get(url, params=None, **kw):
        asked.append((url, kw.get("headers")))
        for part, answer in services.items():
            if part in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer(params) if callable(answer) else answer
        return Answer(404)
    monkeypatch.setattr(about.requests, "get", get)
    monkeypatch.setattr(about.spherex.requests, "get", get)
    monkeypatch.setattr(about.spherex, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(about, "CACHE_DIR", tmp_path)
    return services, asked


def test_about_a_named_star_in_three_sources(net):
    services, asked = net
    services.update({"nph-sesame": Answer(content=BARNARD_XML.encode()), "page/summary/Barnard": Answer(data=BARNARD_PAGE)})
    a = about.get_about(q="Barnard's Star")
    assert a == {
        "name": "Barnard's Star", "object_type": "red dwarf", "spectral_type": "M4V", "distance_ly": 5.96,
        "aliases": ["Barnard Star", "HIP 87937", "GJ 699", "2MASS J17574849+0441405", "Gaia DR3 4472832130942575872"],
        "facts_sentence": "Barnard's Star is a red dwarf (spectral type M4V) about 6.0 light-years away.",
        "history_sentence": "It is named after E. E. Barnard, who measured its motion in 1916.",
        "history_source": {"title": "Barnard's Star", "url": "https://en.wikipedia.org/wiki/Barnard%27s_Star", "license": "CC BY-SA 4.0"},
        "papers": 924,
        "sources": [{"label": "CDS Sesame / SIMBAD", "url": "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=NAME%20Barnard%27s%20star"},
                    {"label": "Wikipedia: Barnard's Star", "url": "https://en.wikipedia.org/wiki/Barnard%27s_Star"}],
        "notes": [],
        "fast_movers": [],
    }
    wiki = [h for u, h in asked if "wikipedia" in u]
    assert wiki and all("WANDERERS" in h["User-Agent"] and "@" not in h["User-Agent"] for h in wiki)  # no e-mail address
    n = len(asked)
    assert about.get_about(q="barnard's  star") == a and len(asked) == n  # cached: no new request


def test_without_wikipedia_the_answer_says_so_and_is_not_cached(net, tmp_path):
    services, _ = net
    services.update({"nph-sesame": Answer(content=BARNARD_XML.encode()), "wikipedia": about.requests.ConnectionError("down")})
    a = about.get_about(q="Barnard's Star")
    assert (a["facts_sentence"] is not None, a["history_sentence"], a["papers"]) == (True, None, 924)
    assert a["notes"] == ["Wikipedia did not answer, so the history is missing."]
    assert not list(tmp_path.glob("about-*.json"))


def test_a_clicked_position_asks_simbad_which_object_is_there(net):
    services, asked = net
    services.update({"sim-tap": Answer(data={"data": [["NAME Barnard's star", "BY*", 924, 0.0001]]}),
                     "nph-sesame": Answer(content=BARNARD_XML.encode()), "page/summary/Barnard": Answer(data=BARNARD_PAGE)})
    a = about.get_about(ra=269.452077, dec=4.693365)
    assert (a["name"], a["papers"]) == ("Barnard's Star", 924)
    assert [s["label"] for s in a["sources"]] == ["CDS Sesame / SIMBAD", "SIMBAD, objects near this position", "Wikipedia: Barnard's Star"]


def test_a_position_without_simbad_says_what_is_missing(net):
    services, _ = net
    services["sim-tap"] = about.requests.Timeout("SIMBAD is down")
    a = about.get_about(ra=150.0, dec=2.2)
    assert (a["name"], a["facts_sentence"], a["history_sentence"]) == (None, None, None)
    assert a["notes"] == ["SIMBAD did not answer, so the object at this position is not known here.",
                          "The search for fast-moving stars near this position did not finish, so that hint is missing."]


# ---- which object a position means ----

def test_a_star_wins_over_its_planet_at_the_same_position():
    # SIMBAD puts Barnard's Star c at its star's position: a tie at 0.0". The star is what the user means.
    rows = [["NAME Barnard's Star c", "Pl", 3, 0.0], ["NAME Barnard's star", "BY*", 924, 0.0]]
    assert about.pick_object(rows) == "NAME Barnard's star"


@pytest.mark.parametrize("rows, picked", [
    ([["A b", "Pl", 1, 0.0], ["A", "*", 50, 0.2 / 3600]], "A"),  # a planet nearer by 0.2": still the star
    ([["A", "**", 300, 0.0], ["A B", "BD*", 20, 0.5 / 3600]], "A"),  # within 1": the most studied one
    ([["Near", "*", 2, 0.5 / 3600], ["Far", "*", 900, 3.0 / 3600]], "Near"),  # 2.5" apart: the nearest one
    ([["A b", "Pl?", 1, 0.0]], "A b"),  # a planet when nothing else is there
    ([], None),
])
def test_the_picked_object_is_near_and_not_a_planet(rows, picked):
    assert about.pick_object(rows) == picked


def test_a_gaia_position_moved_back_to_j2000_is_simbads_position():
    # Barnard's Star: Gaia DR3 position at epoch 2016.0 and proper motion -> SIMBAD's J2000 position 269.452077 4.693365
    ra, dec = about.j2000(269.44850252543836, 4.739420051112412, -801.551, 10362.394, 2016.0)
    assert (ra, dec) == pytest.approx((269.452077, 4.693365), abs=2e-6)


def test_a_mark_on_a_fast_mover_finds_its_star_at_the_j2000_position(net):
    services, _ = net
    def simbad(params):  # SIMBAD lists Barnard's Star only at its J2000 position, 47" from its Gaia 2016 position
        here = "269.45207" in params["QUERY"] and "4.69336" in params["QUERY"]
        return Answer(data={"data": [["NAME Barnard's star", "BY*", 924, 0.0]] if here else []})
    services.update({"sim-tap": simbad, "nph-sesame": Answer(content=BARNARD_XML.encode()),
                     "page/summary/Barnard": Answer(data=BARNARD_PAGE)})
    assert about.get_about(ra=269.44850253, dec=4.73942005)["name"] is None  # the plain cone misses it
    # the Gaia DR3 position (epoch 2016.0) and proper motion that the web app sends for a mark on Barnard's Star
    a = about.get_about(ra=269.44850253, dec=4.73942005, pmra=-801.551, pmdec=10362.394, epoch=2016.0)
    assert a["name"] == "Barnard's Star"


# ---- a fast mover near a typed position (NM2) ----

def test_the_path_of_a_fast_mover_passes_its_old_coordinates():
    # WISE 0855: SIMBAD J2000 position and proper motion; the challenge coordinates are its 2010 position (85" away)
    closest, now = about.path_near(133.81890825, -7.247048, -8123.7, 673.2, 133.795129, -7.245147)
    assert closest == pytest.approx(0.2, abs=0.3)  # its path crosses the typed position (in 2010)
    assert now == pytest.approx(127, abs=2)  # in 2026.0 it is 127" away


def test_a_typed_position_names_the_fast_mover_whose_path_crosses_it(net):
    services, _ = net
    def simbad(params):
        q = params["QUERY"]
        if "pmra * pmra" in q:  # the search for fast movers within 300"
            return Answer(data={"data": [["WISEA J085510.74-071442.5", 133.81890825, -7.247048, -8123.7, 673.2],
                                         ["NAME Far Mover", 133.865, -7.245, 1100.0, 0.0]]})  # 250" east, moving away
        return Answer(data={"data": []})  # nothing within 5"
    services["sim-tap"] = simbad
    a = about.get_about(ra=133.795129, dec=-7.245147)
    assert a["fast_movers"] == [{"name": "WISEA J085510.74-071442.5", "pm_arcsec_yr": 8.15, "sep_arcsec": 127}]


def test_a_failed_fast_mover_search_is_said_and_kept_one_hour_only(net, tmp_path):
    services, _ = net
    calls = {"fast": 0}
    def simbad(params):
        if "pmra * pmra" in params["QUERY"]:
            calls["fast"] += 1
            if calls["fast"] <= 2:  # both SIMBAD hosts time out on the first request
                raise about.requests.Timeout("SIMBAD is slow")
            return Answer(data={"data": [["WISEA J085510.74-071442.5", 133.81890825, -7.247048, -8123.7, 673.2]]})
        return Answer(data={"data": []})
    services["sim-tap"] = simbad
    first = about.get_about(ra=133.795129, dec=-7.245147)
    assert first["fast_movers"] is None  # unknown, not "none near"
    assert any("fast-moving" in n for n in first["notes"])
    assert about.get_about(ra=133.795129, dec=-7.245147) == first  # kept for a while: no new SIMBAD request
    for p in tmp_path.glob("about-*.json"):  # 2 hours later the hint is looked for again
        t = time.time() - 2 * 3600
        os.utime(p, (t, t))
    assert about.get_about(ra=133.795129, dec=-7.245147)["fast_movers"][0]["sep_arcsec"] == 127


def test_a_slow_fast_mover_search_does_not_hold_the_answer(net, monkeypatch):
    services, _ = net
    def simbad(params):
        if "pmra * pmra" in params["QUERY"]:
            time.sleep(2)  # far longer than the cap below
        return Answer(data={"data": []})
    services["sim-tap"] = simbad
    monkeypatch.setattr(about, "FAST_TIMEOUT_S", 0.3)
    t0 = time.monotonic()
    a = about.get_about(ra=150.0, dec=2.2)
    assert time.monotonic() - t0 < 1.5
    assert a["fast_movers"] is None and any("fast-moving" in n for n in a["notes"])


def test_no_hint_when_the_typed_position_is_where_the_star_is_now(net):
    services, _ = net
    # the star's 2026.0 position: J2000 position moved 26 years at 8"/yr to the west
    ra0, dec0 = 133.81890825, -7.247048
    now_ra = ra0 + (-8123.7 * 26 / 3.6e6) / math.cos(math.radians(dec0))
    def simbad(params):
        rows = [["WISEA J085510.74-071442.5", ra0, dec0, -8123.7, 673.2]] if "pmra * pmra" in params["QUERY"] else []
        return Answer(data={"data": rows})
    services["sim-tap"] = simbad
    assert about.get_about(ra=now_ra, dec=dec0 + 673.2 * 26 / 3.6e6)["fast_movers"] == []
