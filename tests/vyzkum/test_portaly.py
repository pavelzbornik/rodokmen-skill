"""Syntetické odpovědi portálů, bez volání sítě."""
import importlib.util
import json
from argparse import Namespace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest


TOOLS = Path(__file__).resolve().parents[2] / "skills/rodokmen/tools"


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))

    def load(name):
        path = TOOLS / (name + ".py")
        assert path.is_file(), f"Chybí nástroj {name}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load


def test_badame_ulozi_stranku_a_cizi_odkazy_jen_vypise(tool, monkeypatch, tmp_path):
    badame = tool("badame")
    cache = tmp_path / "pracovni/badame"
    catalog = tmp_path / "docs/zdroje_badame.md"
    catalog.parent.mkdir()
    catalog.write_bytes(b"https://example.org/first/\n")
    monkeypatch.setattr(badame, "ROOT", str(tmp_path))
    monkeypatch.setattr(badame, "SLOZKA", str(cache))
    listing = """
        <article class="post-7 category-databaze"><h2 class="preview-title">
        <a href="https://example.org/first/#new_tab">První</a></h2></article>
        <article class="post-8"><h2 class="preview-title">
        <a href="https://example.org/second/">Druhý</a></h2></article>
        <article class="post-9"><h2 class="preview-title">
        <a href="/test/">Příspěvek</a></h2></article>
        <article class="post-10"><h2 class="preview-title">
        <a href="javascript:void(0)">Neplatný</a></h2></article>
    """
    requests = []

    def fetch(url):
        requests.append(url)
        return {"https://badame.cz/": listing, "https://badame.cz/test/":
                '<div class="entry-content"><a href="https://example.net/test">Zdroj</a></div>'}[url]

    monkeypatch.setattr(badame, "_stahni", fetch)
    page = badame.stranka(1)
    assert [row["zhodnoceno"] for row in page["polozky"]] == [True, False, False]
    assert page["polozky"][2]["odkazy_prispevku"] == ["https://example.net/test"]
    assert badame.stranka(1) == page
    assert json.loads((cache / "stranka_1.json").read_text(encoding="utf-8")) == page
    assert requests == ["https://badame.cz/", "https://badame.cz/test/"]


def test_badame_neotevre_presmerovani_mimo_rozcestnik(tool):
    badame = tool("badame")
    redirect = badame.PresmerovaniBadame()
    request = Request("https://badame.cz/test/")
    with pytest.raises(HTTPError, match="mimo Bádáme.cz"):
        redirect.redirect_request(request, None, 302, "", {}, "https://example.org/")
    assert redirect.redirect_request(request, None, 302, "", {}, "https://www.badame.cz/test/").host == "www.badame.cz"


def test_kramerius_hledani_a_ocr(tool, monkeypatch):
    k7 = tool("kramerius7")
    pid = "uuid:00000000-0000-4000-8000-000000000001"
    record = {"pid": pid, "model": "page", "title.search": ["Zkušební list"], "accessibility": "private"}
    payload = {"response": {"numFound": 1, "docs": [record]},
               "highlighting": {pid: {"text_ocr": ["&amp; <strong>noviny</strong>"]}}}
    assert k7.parse_hledani(payload)["vysledky"][0]["uryvek"] == ""
    filters = k7.parametry_hledani("zkušební list", od=1900, do=1910, jen_volne=True)
    assert filters["q"] == 'text_ocr:"zkušební list"'
    assert filters["fq"] == ("model:page AND accessibility:public AND "
                             "date_range_start.year:[* TO 1910] AND date_range_end.year:[1900 TO *]")
    requests = []

    def fetch(url):
        requests.append(url)
        return "\ufeffPrvní řádek\r\n" if url.endswith("/ocr/text") else json.dumps(payload)

    monkeypatch.setattr(k7, "_stahni", fetch)
    with pytest.raises(ValueError, match="veřejné"):
        k7.ocr(pid)
    record["accessibility"] = "public"
    assert k7.parse_hledani(payload)["vysledky"][0]["uryvek"] == "& [noviny]"
    with pytest.raises(ValueError, match="nenalezena"):
        k7.ocr(pid[:-1] + "2")
    assert all(not url.endswith("/ocr/text") for url in requests)
    assert k7.ocr(pid)["text"] == "První řádek\n"
    assert requests[-1].endswith("/items/" + pid.replace(":", "%3A") + "/ocr/text")


def test_forum_ukonci_hledani_pri_limitu(tool, monkeypatch):
    forum = tool("forum_genealogie")
    requests = []
    html = '<div class="error">Nyní nemůžete vyhledávat. Zkuste to znovu později.</div>'
    monkeypatch.setattr(forum, "_stahni", lambda url: requests.append(url) or html)
    with pytest.raises(ValueError, match="limit"):
        forum.hledej("Příklad")
    assert len(requests) == 1


def test_forum_cache_rozlisuje_dotaz_a_rozsah(tool, monkeypatch, tmp_path):
    forum = tool("forum_genealogie")
    monkeypatch.setattr(forum, "ROOT", str(tmp_path))
    monkeypatch.setattr(forum, "SLOZKA", str(tmp_path / "forum"))
    requests = []

    def search(slova, nazvy, rubrika, autor, max_stran):
        requests.append((slova, max_stran))
        return dict(dotaz=slova, celkem=0, vysledky=[], kdy="2026-01-01 00:00")

    monkeypatch.setattr(forum, "hledej", search)
    args = Namespace(slova="Test*", nazvy=False, rubrika=None, autor=None, max_stran=1, znovu=False)
    forum._cmd_hledej(args)
    forum._cmd_hledej(args)
    args.slova = "Test"
    forum._cmd_hledej(args)
    args.max_stran = 2
    forum._cmd_hledej(args)
    assert requests == [("Test*", 1), ("Test", 1), ("Test", 2)]


def test_forum_cita_tema_a_pokracuje_jen_na_jeho_stranku(tool, monkeypatch):
    forum = tool("forum_genealogie")
    page = """
        <h2><a href="./viewtopic.php?t=100">Zkušební téma</a></h2>
        Stránka <strong>1</strong> z <strong>2</strong>
        <div id="p10" class="post bg1">
        <h3><a href="#p10">Předmět</a></h3>
        <p class="author">od <strong>Testovací autor</strong> &raquo; 1. ledna</p>
        <div class="content">První<br />druhý řádek.</div><div class="notice"></div>
        <a href="./viewtopic.php?t=200&amp;start=10">Jiné téma</a>
        <a href="./viewtopic.php?t=100&amp;start=25">Další</a>
    """
    requests = []

    def fetch(url):
        requests.append(url)
        if not url.endswith("start=25"):
            return page
        return page.replace('id="p10"', 'id="p11"').replace("<strong>1</strong>", "<strong>2</strong>")

    monkeypatch.setattr(forum, "_stahni", fetch)
    topic = forum.tema(100, 2)
    assert topic["nazev"] == "Zkušební téma"
    assert [p["id"] for p in topic["prispevky"]] == [10, 11]
    assert topic["prispevky"][0]["text"] == "První\ndruhý řádek."
    assert requests[-1] == "https://genealogie.taby.cz/viewtopic.php?t=100&start=25"


def test_pokryti_nepovazuje_ztraceny_kanal_snapshotu_za_splneny(tool):
    coverage = tool("pokryti")
    people = {"k:2": dict(name="Zkušební osoba", birth="1880", fs="AAAA-BBB", living=False,
                          keys=[["kekule", "2"]], parents=[], records=[],
                          research=dict(k=2, person={}, events={}, marriages={}))}
    before = coverage.stav(people, [], {"zdroje": {"AAAA-BBB"}, "shody záznamů": {"CCCC-DDD"}}, {})
    assert [step for step, _ in before[0]["kroky"]] == [2]
    missing = coverage.stav(people, [], {"zdroje": {"AAAA-BBB"}}, {})
    assert coverage.rozdil(before, missing)["splnene_kroky"] == []
    after = coverage.stav(people, [], {"zdroje": {"AAAA-BBB"}, "shody záznamů": {"AAAA-BBB"}}, {})
    assert coverage.rozdil(before, after)["splnene_kroky"] == ["Zkušební osoba: čtení na FamilySearch"]
