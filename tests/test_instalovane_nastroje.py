"""Ověří nástroje v projektu vytvořeném skutečnou šablonou skillu."""
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

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
