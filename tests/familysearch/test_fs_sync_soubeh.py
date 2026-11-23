"""Map a log zachovají všechny položky, i když je zapisuje několik procesů souběžně."""
import json, os, subprocess, sys

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../skills/rodokmen/tools"))
MAP = ("import sys; sys.path.insert(0, sys.argv[1]); import fs_sync\n"
       "for n in range(int(sys.argv[4])):\n"
       "    fs_sync.write_mappings(sys.argv[2], [dict(group='ged', key=f'@I{sys.argv[3]}x{n}@', fs='AAAA-BBB')])\n")
LOG = ("import sys; sys.path.insert(0, sys.argv[1]); import fs_sync\n"
       "for n in range(int(sys.argv[5])):\n"
       "    pid = f'{sys.argv[4]}{n}'\n"
       "    item = dict(id='i' + pid, kind='source', pid='AAAA-BBB', image='https://x.org/' + pid, reason='r ' + pid)\n"
       "    plan = dict(id='p' + pid, items=[item])\n"
       "    res = dict(schema='rodokmen.fs-result.v1', plan_id='p' + pid, items=[dict(id='i' + pid, status='applied')])\n"
       "    fs_sync.log_result(res, plan, sys.argv[2], sys.argv[3])\n")


def run_all(code, args, count=6):
    procesy = [subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", code, TOOLS, *args(i)]) for i in range(count)]
    assert all(p.wait(timeout=300) == 0 for p in procesy)


def test_soubezne_mapovani_nic_neztrati(tmp_path):
    cesta = tmp_path / "familysearch.json"
    cesta.write_text('{\n "kekule": {\n  "8": "CCCC-DDD"\n },\n "ged": {}\n}\n', encoding="utf-8")
    run_all(MAP, lambda i: [str(cesta), f"p{i}", "10"])
    data = json.loads(cesta.read_text(encoding="utf-8"))
    assert data["kekule"] == {"8": "CCCC-DDD"} and len(data["ged"]) == 6 * 10
    assert not [f for f in os.listdir(tmp_path) if f != "familysearch.json"]


def test_soubezny_log_nic_neztrati(tmp_path):
    ledger, denik = tmp_path / "fs_sync_stav.json", tmp_path / "research_log.md"
    denik.write_text("# Deník\n", encoding="utf-8")
    run_all(LOG, lambda i: [str(ledger), str(denik), f"v{i}x", "6"])
    assert len(json.loads(ledger.read_text(encoding="utf-8"))) == 6 * 6
    assert denik.read_text(encoding="utf-8").count("<!-- fs-sync:") == 6 * 6
    assert sorted(os.listdir(tmp_path)) == ["fs_sync_stav.json", "research_log.md"]
