"""'About this star' (backend/about.py): catalog facts in words, one Wikipedia history sentence. No network."""
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
    """Fake services: a dict of URL part -> answer (or an exception to raise). Records the URLs asked."""
    services, asked = {}, []
    def get(url, params=None, **kw):
        asked.append((url, kw.get("headers")))
        for part, answer in services.items():
            if part in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer
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
    services.update({"sim-tap": Answer(data={"data": [["NAME Barnard's star", 0.0001]]}),
                     "nph-sesame": Answer(content=BARNARD_XML.encode()), "page/summary/Barnard": Answer(data=BARNARD_PAGE)})
    a = about.get_about(ra=269.452077, dec=4.693365)
    assert (a["name"], a["papers"]) == ("Barnard's Star", 924)
    assert [s["label"] for s in a["sources"]] == ["CDS Sesame / SIMBAD", "SIMBAD, objects near this position", "Wikipedia: Barnard's Star"]


def test_a_position_without_simbad_says_what_is_missing(net):
    services, _ = net
    services["sim-tap"] = about.requests.Timeout("SIMBAD is down")
    a = about.get_about(ra=150.0, dec=2.2)
    assert (a["name"], a["facts_sentence"], a["history_sentence"]) == (None, None, None)
    assert a["notes"] == ["SIMBAD did not answer, so the object at this position is not known here."]
