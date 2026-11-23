"""Ověří nástroje v projektu vytvořeném skutečnou šablonou skillu."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request
import urllib.request

import pytest


SKILL = Path(__file__).resolve().parents[1] / "skills" / "rodokmen"


def run(path, *args):
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", str(path), *map(str, args)],
                            cwd=path.parent.parent, capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def projekt(tmp_path):
    run(SKILL / "tools/novy_projekt.py", tmp_path, "--ukazka")
    return tmp_path


def test_familysearch_na_ciste_instalaci(projekt):
    tools = projekt / "tools"
    assert (tools / "fs_prohlizec.js").is_file()
    tool = tools / "fs_sync.py"
    scope = projekt / "pracovni/fs_sync/scope.json"
    run(tool, "scope", "--no-myheritage")
    cfg = json.loads(scope.read_text(encoding="utf-8"))
    assert cfg["root"] is None
    assert cfg["ids"] == []
    assert cfg["tasks"] is False

    with (projekt / "data/familysearch.json").open("w", encoding="utf-8", newline="\n") as stream:
        json.dump({"kekule": {"8": "AAAA-BBB"}, "ged": {}}, stream)
    run(tool, "scope", "--root", "CCCC-DDD", "--max-persons", 5)
    cfg = json.loads(scope.read_text(encoding="utf-8"))
    assert cfg["root"] == "CCCC-DDD"
    assert cfg["ids"] == ["AAAA-BBB"]
    assert cfg["maxPersons"] == 5

    fixture = projekt / "pracovni/snapshot.json"
    with fixture.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump({"schema": "rodokmen.fs-snapshot.v1", "persons": {}}, stream)
    run(tool, "snapshot-import", fixture)
    run(tool, "diff")
    assert list(scope.parent.glob("plan-*.md"))


def test_gmail_odkaz_z_instalovaneho_nastroje(projekt):
    draft = projekt / "pracovni/dotaz.md"
    with draft.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("## Dotaz\n\n**Komu:** archiv@example.org\n**Kopie:** ja@example.org\n"
                     "**Předmět:** Matrika\n\nDobrý den,\n\nprosím o ověření zápisu.\n")
    tool = projekt / "tools/mailto.py"
    run(tool, draft, "--gmail")
    text = draft.read_text(encoding="utf-8")
    url = text.split("](https://mail.google.com/", 1)[1].split(")", 1)[0]
    assert parse_qs(urlsplit("https://mail.google.com/" + url).query) == {
        "view": ["cm"], "fs": ["1"], "to": ["archiv@example.org"], "cc": ["ja@example.org"],
        "su": ["Matrika"], "body": ["Dobrý den,\n\nprosím o ověření zápisu."],
    }
    run(tool, draft, "--gmail")
    assert draft.read_text(encoding="utf-8") == text


def test_archivni_nastroje_na_ciste_instalaci(projekt):
    tools = projekt / "tools"
    for name in ("badame", "forum_genealogie", "kramerius7", "matricula_img"):
        assert "usage:" in run(tools / (name + ".py"), "--help")
        assert (projekt / ".skill_sablona/tools" / (name + ".py")).is_file()
    assert "zatím nic" in run(tools / "forum_genealogie.py", "hledano")
    html = projekt / "pracovni/matricula.html"
    with html.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write('<script>var book = {"labels":["Obálka","Index Taufe","1"]};</script>')
    assert run(tools / "matricula_img.py", html, "https://data.matricula-online.eu/de/test/kniha/?pg=1",
               "--rejstriky").splitlines() == ["2\tIndex Taufe\thttps://data.matricula-online.eu/de/test/kniha/?pg=2"]


def test_pokryti_na_prazdne_instalaci(tmp_path):
    run(SKILL / "tools/novy_projekt.py", tmp_path)
    run(tmp_path / "tools/pokryti.py", "ukoly")
    report = next((tmp_path / "pracovni/pokryti").glob("*.json"))
    assert json.loads(report.read_text(encoding="utf-8")) == []
    assert report.with_suffix(".md").is_file()


def test_pokryti_s_gedcomem_a_importovanym_snapshotem(projekt):
    def write(relative, data):
        with (projekt / relative).open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))

    write("data/osoby.py", 'P = {2: dict(n="Jméno z poznámek", y="1870–1940", st="doc", f=["* 1870"], r=[])}\n')
    write("data/zaznamy.json", [])
    write("data/fary.json", {"Obec A": {"fara": "Fara A"}})
    write("data/familysearch.json", {"kekule": {"2": "AAAA-BBB"}, "ged": {"@I2@": "AAAA-BBB"}})
    write("pracovni/test.ged", """0 HEAD
0 @I1@ INDI
1 NAME Novější /Osoba/
1 BIRT
2 DATE 1980
1 FAMC @F1@
0 @I2@ INDI
1 NAME Starší /Osoba/
1 BIRT
2 DATE 1870
2 PLAC Obec A, Okres B
1 DEAT
2 DATE 1940
1 FAMS @F1@
0 @F1@ FAM
1 HUSB @I2@
1 CHIL @I1@
0 TRLR
""")
    snapshot_path = projekt / "pracovni/snapshot.json"
    snapshot = dict(schema="rodokmen.fs-snapshot.v1", persons={}, sources={"AAAA-BBB": []},
                    record_matches_read={"AAAA-BBB": "2026-01-01T00:00:00Z"})
    write("pracovni/snapshot.json", snapshot)
    run(projekt / "tools/fs_sync.py", "snapshot-import", snapshot_path)
    snapshot.update(sources={}, myheritage_read={"AAAA-BBB": "2026-01-02T00:00:00Z"},
                    myheritage={"AAAA-BBB": {"totalHints": 0}})
    write("pracovni/snapshot.json", snapshot)
    run(projekt / "tools/fs_sync.py", "snapshot-import", snapshot_path)
    coverage = projekt / "tools/pokryti.py"
    run(coverage, "ukoly", "--ged", "pracovni/test.ged", "--krok", 4)
    report = next((projekt / "pracovni/pokryti").glob("*.json"))
    rows = json.loads(report.read_text(encoding="utf-8"))
    assert [r["name"] for r in rows] == ["Jméno z poznámek"]
    assert rows[0]["id"] == "k:2"
    assert rows[0]["fs"] == "AAAA-BBB"
    assert [n for n, _ in rows[0]["kroky"]] == [3, 4]
    assert "Fara A" in report.with_suffix(".md").read_text(encoding="utf-8")
    assert "## 3." not in report.with_suffix(".md").read_text(encoding="utf-8")
    assert not (projekt / "web/src/data/site.json").exists()

    write("data/zaznamy.json", [{"klic": "obec_a_scitani_1880", "druh": "S"}])
    write("data/osoby.py", 'P = {2: dict(n="Jméno z poznámek", y="1870–1940", st="doc", f=["* 1870"], '
          'r=["obec_a_scitani_1880"])}\n')
    changes = json.loads(run(coverage, "rozdil", report, "--ged", "pracovni/test.ged"))
    assert changes["nove_zapisy"] == ["Jméno z poznámek"]
    assert "Jméno z poznámek: sčítání 1880" in changes["splnene_kroky"]
    assert len(list(report.parent.glob("*.json"))) == 1


def test_kontrola_verze_sleduje_fork(monkeypatch, tmp_path, capsys):
    """Upstream a fork mají vlastní verze na GitHubu i při sdílení adresáře mezipaměti."""
    verze = SKILL / "tools/verze.py"
    assert verze.is_file(), "Chybí nástroj kontroly verze"
    monkeypatch.setattr(sys, "argv", [str(verze), str(tmp_path)])
    monkeypatch.setenv("RODOKMEN_CACHE", str(tmp_path))
    monkeypatch.delenv("RODOKMEN_VERZE_URL", raising=False)
    cache = tmp_path / "rodokmen_verze.json"
    cache.write_bytes(b'{"cas": 9999999999, "verze": "0.99.0"}')
    (tmp_path / ".skill_verze").write_bytes(b"0.8.3-pavel.2\n")
    requests = []

    def version_response(request, timeout):
        from io import BytesIO

        assert isinstance(request, Request)
        requests.append(request.full_url)
        return BytesIO(b"0.10.2\n")

    monkeypatch.setattr(urllib.request, "urlopen", version_response)
    runpy.run_path(str(verze), run_name="__main__")
    assert requests == ["https://raw.githubusercontent.com/pavelzbornik/rodokmen-skill/main/skills/rodokmen/VERZE"]
    assert "AKTUALIZUJ_PROJEKT" in capsys.readouterr().out
    assert json.loads(cache.read_text(encoding="utf-8"))["verze"] == "0.99.0"
    assert json.loads((tmp_path / "rodokmen_verze_forku.json").read_text(encoding="utf-8"))["verze"] == "0.10.2"


def test_stejna_verze_bez_nastroju_odnoze_nabidne_instalaci(projekt):
    version_check = SKILL / "tools/verze.py"
    args = [sys.executable, "-I", "-X", "utf8", str(version_check), str(projekt)]
    env = dict(os.environ, RODOKMEN_VERZE_URL="http://127.0.0.1:9/nic",
               RODOKMEN_CACHE=str(projekt / "pracovni"))
    for name in ("fs_sync.py", "mailto.py", "pokryti.py"):
        (projekt / "tools" / name).unlink()
        (projekt / ".skill_sablona/tools" / name).unlink()
    result = subprocess.run(args, capture_output=True, encoding="utf-8", env=env, check=True)
    assert "AKTUALIZUJ_PROJEKT" in result.stdout and "nástroje odnože" in result.stdout

    run(SKILL / "tools/novy_projekt.py", projekt)
    (projekt / "tools/pokryti.py").unlink()
    result = subprocess.run(args, capture_output=True, encoding="utf-8", env=env, check=True)
    assert "AKTUALNI" in result.stdout and "AKTUALIZUJ_PROJEKT" not in result.stdout


def test_zapis_zachova_pole_pokud_uzivatel_nepotvrdi_prepsani(projekt):
    path = projekt / "data/svazky.json"
    original = b'{"test": {"nazev": "Test", "popis": "Popis"}}\n'
    path.write_bytes(original)
    source = projekt / "pracovni/svazek.json"
    source.write_bytes(b'{"nazev": "Novy nazev"}\n')
    tool = projekt / "tools/zapis.py"
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", str(tool), "svazky", "test", str(source)],
                            capture_output=True, encoding="utf-8")
    assert result.returncode != 0 and "--prepsat" in result.stderr
    assert path.read_bytes() == original
    run(tool, "svazky", "test", source, "--sloucit")
    assert json.loads(path.read_text(encoding="utf-8"))["test"] == {"nazev": "Novy nazev", "popis": "Popis"}
    run(tool, "svazky", "test", source, "--prepsat")
    assert json.loads(path.read_text(encoding="utf-8"))["test"] == {"nazev": "Novy nazev"}


def test_zapis_odkaz_drzi_zamek_po_celou_upravu(projekt, monkeypatch):
    source = projekt / "data/osoby.py"
    source.write_bytes(b'P = {2: dict(n="Test", r=[])}\n')
    (projekt / "data/zaznamy.json").write_bytes(b'[{"klic":"test"}]\n')
    spec = importlib.util.spec_from_file_location("zapis_odkaz_test", projekt / "tools/zapis.py")
    zapis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zapis)
    monkeypatch.setattr(zapis, "ROOT", str(projekt))
    nacti, replace = zapis.nacti_osoby, zapis.os.replace
    locked = False

    @contextmanager
    def lock(path):
        nonlocal locked
        assert Path(path) == source
        locked = True
        try:
            yield
        finally:
            locked = False

    def guarded_read(data):
        assert locked
        return nacti(data)

    def guarded_replace(old, new):
        assert locked
        return replace(old, new)

    monkeypatch.setattr(zapis, "zamceno", lock)
    monkeypatch.setattr(zapis, "nacti_osoby", guarded_read)
    monkeypatch.setattr(zapis.os, "replace", guarded_replace)
    zapis.odkaz("2", ["test"])
    assert runpy.run_path(str(source))["P"][2]["r"] == ["test"]
