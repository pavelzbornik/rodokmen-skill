"""Offline synchronizace nesmí zaměnit stopu za doklad ani zopakovat zápis."""
import json
import subprocess
from pathlib import Path

import pytest

import fs_sync as sync


URL = "https://digi.ceskearchivy.cz/123/45"
TYPE = "http://gedcomx.org/"


def person(name="Jan Novák", fs="AAAA-BBB", st="doc", living=False):
    return dict(name=name, fs=fs, st=st, living=living, birth="+1800-01-02",
                keys=[["kekule", "8"]], facts=[dict(type="Birth", date="+1800-01-02",
                image=URL, reason="Křest přečtený ze snímku", record="krest")],
                sources=[dict(url=URL, title="Křest Jana", reason="Čteno ze snímku", record="krest")],
                parents=[], relation_evidence={})


def remote(pid="AAAA-BBB", name="Johann Novák", birth=None, living=False):
    p = dict(id=pid, living=living, names=[dict(nameForms=[dict(fullText=name)])], facts=[])
    if birth:
        p["facts"].append(dict(type=TYPE + "Birth", date=dict(formal=birth)))
    return p


def snapshot(*people):
    return dict(schema="rodokmen.fs-snapshot.v1", captured_at="2026-11-11T12:00:00Z",
                persons={p["id"]: p for p in people}, sources={p["id"]: [] for p in people},
                relationships=[], tasks=[], record_matches={}, complete=True)


def test_diff_then_applied_snapshot_is_empty_on_every_rerun():
    loc = {"k:8": person()}
    snap = snapshot(remote())
    plan = sync.build_plan(loc, snap)
    assert {i["kind"] for i in plan["items"]} == {"fact", "source"}
    assert all(URL in i["reason"] and i["st"] == "doc" for i in plan["items"])
    snap["persons"]["AAAA-BBB"]["facts"] = [dict(type=TYPE + "Birth", date=dict(formal="+1800-01-02"))]
    snap["sources"]["AAAA-BBB"] = [dict(about=URL)]
    assert sync.build_plan(loc, snap)["items"] == []
    assert sync.build_plan(loc, snap)["items"] == []


@pytest.mark.parametrize("st,living", [("prob", False), ("mh", False), ("fam", False), ("doc", True)])
def test_only_documented_deceased_people_can_be_written(st, living):
    assert sync.build_plan({"x": person(st=st, living=living)}, snapshot(remote()))["items"] == []


def test_remote_living_and_unknown_status_block_writes():
    for value in (True, None):
        r = remote(living=value)
        assert sync.build_plan({"x": person()}, snapshot(r))["items"] == []


def test_fact_without_image_is_not_pushable_and_conflict_is_report_only():
    p = person()
    p["facts"][0]["image"] = ""
    assert not any(i["kind"] == "fact" for i in sync.build_plan({"x": p}, snapshot(remote()))["items"])
    plan = sync.build_plan({"x": person()}, snapshot(remote(birth="+1801-01-02")))
    assert len(plan["conflicts"]) == 1
    assert not any(i["kind"] == "fact" for i in plan["items"])


@pytest.mark.parametrize("previous", [{}, {"formal": "+1800"}, {"formal": "+1800-01"},
                                     {"formal": "A+1800", "original": "about 1800"},
                                     {"original": "About 1800"}])
def test_exact_date_refines_existing_fact_without_conflict(previous):
    s = snapshot(remote())
    s["persons"]["AAAA-BBB"]["facts"] = [dict(id="birth1", type=TYPE + "Birth", date=previous,
                                               place=dict(original="Praha"))]
    plan = sync.build_plan({"x": person()}, s)
    updates = [i for i in plan["items"] if i["kind"] == "fact-update"]
    assert len(updates) == 1
    assert updates[0]["fact_id"] == "birth1"
    assert updates[0]["previous_date"] == previous
    assert updates[0]["date"] == "+1800-01-02"
    assert not plan["conflicts"]
    s["persons"]["AAAA-BBB"]["facts"][0]["date"] = dict(formal=updates[0]["date"])
    assert not any(i["kind"] == "fact-update" for i in sync.build_plan({"x": person()}, s)["items"])


@pytest.mark.parametrize("previous", [{"formal": "+1801"}, {"formal": "+1800-02"},
                                     {"formal": "+1800-01-03"}, {"formal": "A+1801"},
                                     {"original": "before 1800"}])
def test_different_or_bounded_dates_stay_conflicts(previous):
    s = snapshot(remote())
    s["persons"]["AAAA-BBB"]["facts"] = [dict(id="birth1", type=TYPE + "Birth", date=previous)]
    plan = sync.build_plan({"x": person()}, s)
    assert plan["conflicts"]
    assert not any(i["kind"] == "fact-update" for i in plan["items"])


def test_refinement_requires_full_local_date_unique_remote_fact_and_id():
    p = person()
    s = snapshot(remote())
    fact = dict(id="birth1", type=TYPE + "Birth", date=dict(formal="+1800"))
    for facts in [[{k: v for k, v in fact.items() if k != "id"}], [fact, dict(fact, id="birth2")]]:
        s["persons"]["AAAA-BBB"]["facts"] = facts
        assert sync.build_plan({"x": p}, s)["conflicts"]
    s["persons"]["AAAA-BBB"]["facts"] = [fact]
    p["facts"][0]["date"] = "+1800-01"
    assert not any(i["kind"] == "fact-update" for i in sync.build_plan({"x": p}, s)["items"])


@pytest.mark.parametrize("summary_date", [None, "+1820", "+1819"])
def test_marriage_refinement_deduplicates_copies_of_same_relationship(summary_date):
    p, wife = person(), person(fs="CCCC-DDD")
    wife.update(facts=[], sources=[], keys=[])
    p["facts"] = [dict(type="Marriage", date="+1820-01-02", spouse="wife", image=URL,
                       reason="Sňatek čtený ze snímku", record="snatek")]
    s = snapshot(remote(), remote("CCCC-DDD"))
    rel = dict(id="couple1", type=TYPE + "Couple", person1=dict(resourceId="AAAA-BBB"),
               person2=dict(resourceId="CCCC-DDD"),
               facts=[dict(id="marriage1", type=TYPE + "Marriage", date=dict(formal="+1820"))])
    s["relationships"] = [dict(rel, facts=[]), rel, rel]
    if summary_date:
        s["relationships"].insert(0, dict(rel, facts=[dict(type=TYPE + "Marriage", date=dict(formal=summary_date))]))
    updates = [i for i in sync.build_plan({"x": p, "wife": wife}, s)["items"] if i["kind"] == "fact-update"]
    if summary_date == "+1819":
        assert not updates  # Jiný stručný fakt se nesmí zahodit jako kopie.
        assert sync.build_plan({"x": p, "wife": wife}, s)["conflicts"]
        return
    assert len(updates) == 1
    assert updates[0]["fact_id"] == "marriage1"
    assert updates[0]["relationship_id"] == "couple1"


def test_jan_johann_mapping_needs_unique_name_birth_and_family_context():
    p = person(fs=None)
    p["parents"] = ["dad"]
    dad = person(name="Josef Novák", fs="CCCC-DDD")
    dad.update(keys=[], facts=[], sources=[])
    s = snapshot(remote(birth="+1800-01-02"), remote("CCCC-DDD", "Josef Novák"))
    s["relationships"] = [dict(type=TYPE + "ParentChild", person1=dict(resourceId="CCCC-DDD"),
                               person2=dict(resourceId="AAAA-BBB"))]
    plan = sync.build_plan({"x": p, "dad": dad}, s)
    assert plan["mappings"] == [dict(local="x", group="kekule", key="8", fs="AAAA-BBB")]
    assert plan["items"] == []  # nejdřív map, pak nový diff
    s["persons"]["EEEE-FFF"] = remote("EEEE-FFF", birth="+1800-01-02")
    s["relationships"].append(dict(type=TYPE + "ParentChild", person1=dict(resourceId="CCCC-DDD"),
                                     person2=dict(resourceId="EEEE-FFF")))
    assert sync.build_plan({"x": p, "dad": dad}, s)["mappings"] == []
    assert sync.build_plan({"x": p}, s)["mappings"] == []


def test_relationship_needs_document_and_both_people_deceased():
    p, dad = person(), person("Josef Novák", "CCCC-DDD")
    dad.update(keys=[], facts=[], sources=[])
    p["parents"] = ["dad"]
    s = snapshot(remote(), remote("CCCC-DDD", "Josef Novák"))
    assert not any(i["kind"] == "relationship" for i in sync.build_plan({"x": p, "dad": dad}, s)["items"])
    p["relation_evidence"]["dad"] = dict(image=URL, reason="Rodiče v křtu", record="krest")
    plan = sync.build_plan({"x": p, "dad": dad}, s)
    rel = next(i for i in plan["items"] if i["kind"] == "relationship")
    s["relationships"] = [dict(type=TYPE + "ParentChild", person1=dict(resourceId=rel["parent"]),
                               person2=dict(resourceId=rel["child"]))]
    assert not any(i["kind"] == "relationship" for i in sync.build_plan({"x": p, "dad": dad}, s)["items"])
    dad["living"] = True
    s["relationships"] = []
    assert not any(i["kind"] == "relationship" for i in sync.build_plan({"x": p, "dad": dad}, s)["items"])


def test_map_preserves_unrelated_json_bytes_and_refuses_replacement(tmp_path):
    path = tmp_path / "familysearch.json"
    before = '{\n "kekule": {\n  "4": "AAAA-BBB"\n },\n "ged": { "@I1@" : "CCCC-DDD" },\n "cizi" : [1,  2]\n}\n'
    path.write_text(before, encoding="utf-8")
    mappings = [dict(group="kekule", key="8", fs="EEEE-FFF")]
    sync.write_mappings(path, mappings)
    after = path.read_text(encoding="utf-8")
    assert '"ged": { "@I1@" : "CCCC-DDD" },\n "cizi" : [1,  2]' in after
    assert '"4": "AAAA-BBB"' in after
    assert json.loads(after)["kekule"]["8"] == "EEEE-FFF"
    sync.write_mappings(path, mappings)
    assert path.read_text(encoding="utf-8") == after
    with pytest.raises(ValueError, match="konflikt"):
        sync.write_mappings(path, [dict(group="kekule", key="4", fs="EEEE-FFF")])
    assert path.read_text(encoding="utf-8") == after


def test_ledger_is_idempotent_but_does_not_hide_remote_conflict(tmp_path):
    plan = sync.build_plan({"x": person()}, snapshot(remote()))
    result = dict(schema="rodokmen.fs-result.v1", plan_id=plan["id"],
                  items=[dict(id=i["id"], status="applied") for i in plan["items"]])
    ledger, log = tmp_path / "state.json", tmp_path / "research_log.md"
    log.write_text("# Deník\n", encoding="utf-8")
    sync.log_result(result, plan, ledger, log)
    before = (ledger.read_bytes(), log.read_bytes())
    sync.log_result(result, plan, ledger, log)
    assert before == (ledger.read_bytes(), log.read_bytes())
    assert sync.build_plan({"x": person()}, snapshot(remote()), json.loads(ledger.read_text()))["items"] == []
    conflicting = sync.build_plan({"x": person()}, snapshot(remote(birth="+1801")), json.loads(ledger.read_text()))
    assert conflicting["conflicts"]


def test_partial_snapshot_does_not_treat_missing_person_or_sources_as_empty():
    s = snapshot()
    s["complete"] = False
    plan = sync.build_plan({"x": person()}, s)
    assert plan["items"] == []
    assert plan["unread"]
    s["persons"]["AAAA-BBB"] = remote()
    assert not any(i["kind"] == "source" for i in sync.build_plan({"x": person()}, s)["items"])


def test_original_dates_and_image_urls_keep_identity():
    s = snapshot(remote(birth=None))
    s["persons"]["AAAA-BBB"]["facts"] = [dict(type=TYPE + "Birth", date=dict(original="2 January 1800"))]
    assert not any(i["kind"] == "fact" for i in sync.build_plan({"x": person()}, s)["items"])
    assert sync.url_key("https://data.matricula-online.eu/en/a/b/?pg=1") != sync.url_key("https://data.matricula-online.eu/en/a/b/?pg=2")


def test_equivalent_image_urls_do_not_propose_duplicate_sources():
    pairs = [
        ("http://data.matricula-online.eu/en/a/01%252C2%252C3%252F02/?pg=180",
         "https://data.matricula-online.eu/de/a/01%2C2%2C3%2F02/?pg=180"),
        ("https://familysearch.org/ark:/61903/3:1:TEST-IMAGE",
         "https://www.familysearch.org/ark:/61903/3:1:TEST-IMAGE"),
    ]
    for attached, proposed in pairs:
        p = person()
        p["sources"][0]["url"] = proposed
        snap = snapshot(remote())
        snap["sources"]["AAAA-BBB"] = [dict(about=attached)]
        assert not any(i["kind"] == "source" for i in sync.build_plan({"x": p}, snap)["items"])
    assert sync.url_key(pairs[0][0]) != sync.url_key(pairs[0][1].replace("pg=180", "pg=181"))
    assert sync.url_key("https://example.org/en/a") != sync.url_key("http://example.org/de/a")


def test_marriage_uses_existing_couple_without_proposing_another():
    p, spouse = person(), person("Marie Malá", "CCCC-DDD")
    spouse.update(keys=[], facts=[], sources=[])
    p["facts"] = [dict(type="Marriage", date="+1820-01-02", spouse="wife", image=URL,
                       reason="Sňatek čtený ze snímku", record="snatek")]
    s = snapshot(remote(), remote("CCCC-DDD", "Marie Malá"))
    s["relationships"] = [dict(id="r1", type=TYPE + "Couple", person1=dict(resourceId="AAAA-BBB"),
                               person2=dict(resourceId="CCCC-DDD"), facts=[])]
    plan = sync.build_plan({"x": p, "wife": spouse}, s)
    assert not any(i["kind"] == "couple" for i in plan["items"])
    marriage = next(i for i in plan["items"] if i["kind"] == "fact")
    assert marriage["spouse"] == "CCCC-DDD"
    s["relationships"][0]["facts"] = [dict(type=TYPE+"Marriage", date=dict(formal="+1820-01-02"))]
    assert not any(i["kind"] == "fact" for i in sync.build_plan({"x": p, "wife": spouse}, s)["items"])
    # Rodičovský endpoint vrací stejný pár bez faktů před plnou kopií od partnerů.
    s["relationships"].insert(0, {**s["relationships"][0], "facts": []})
    assert not any(i["kind"] == "fact" for i in sync.build_plan({"x": p, "wife": spouse}, s)["items"])


def test_loader_uses_source_tree_supplements_side_and_disconnected_branches(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "osoby.py").write_text("P = {1: dict(n='Žijící', y='* 2000', st='fam', f=[], r=[])}\nSIDE=[]\nSAME={}\n", encoding="utf-8")
    (data / "tree.ged").write_text("0 @I1@ INDI\n1 NAME Žijící\n1 BIRT\n2 DATE 2000\n", encoding="utf-8")
    (data / "doplnky_rodiny.ged").write_text(
        "0 @I900001@ INDI\n1 NAME Jan /Novák/\n1 BIRT\n2 DATE 2 JAN 1800\n1 _ZAZNAM krest\n"
        "0 @I900002@ INDI\n1 NAME Josef /Novák/\n1 BIRT\n2 DATE 1770\n"
        "0 @F900001@ FAM\n1 HUSB @I900002@\n1 CHIL @I900001@\n", encoding="utf-8")
    for name, obj in {
        "familysearch": dict(kekule={}, ged={}),
        "web": dict(velka_rodina=dict(ged="data/tree.ged", doplnky="data/doplnky_rodiny.ged", koren="@I1@", overeno=["@I900001@"])),
        "zaznamy": [dict(klic="krest", nazev="Křest Jana", datum="2. 1. 1800", druh="N", odkaz=URL)],
        "vetve": dict(novaci=[dict(zakladatel="@I900002@")]),
    }.items():
        (data / (name + ".json")).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    loc = sync.load_local(tmp_path)
    assert loc["g:@I900001@"]["facts"][0]["date"] == "+1800-01-02"
    assert loc["g:@I900001@"]["parents"] == ["g:@I900002@"]
    assert loc["g:@I900002@"]["st"] == "mh"
    assert loc["k:1"]["living"] is True


def marriage_tree(tmp_path, texts, second=True, family_dates=False):
    data = tmp_path / "data"
    data.mkdir()
    p = {1: dict(n="Jan Novák", y="1800–1880", st="doc", f=texts, r=["first", "second"])}
    (data / "osoby.py").write_text("P = " + repr(p) + "\nSIDE=[]\nSAME={}\n", encoding="utf-8")
    tree = ("0 @I1@ INDI\n1 NAME Jan /Novák/\n1 BIRT\n2 DATE 1800\n1 DEAT\n2 DATE 1880\n"
            "1 FAMS @F1@\n1 FAMS @F2@\n"
            "0 @I2@ INDI\n1 NAME Marie /Malá/\n1 BIRT\n2 DATE 1801\n1 DEAT\n2 DATE 1850\n1 FAMS @F1@\n"
            "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n")
    if family_dates:
        tree += "1 MARR\n2 DATE 2 JAN 1820\n"
    if second:
        tree += ("0 @I3@ INDI\n1 NAME Anna /Velká/\n1 BIRT\n2 DATE 1810\n1 DEAT\n2 DATE 1890\n1 FAMS @F2@\n"
                 "0 @F2@ FAM\n1 HUSB @I1@\n1 WIFE @I3@\n")
        if family_dates:
            tree += "1 MARR\n2 DATE 3 FEB 1851\n"
    (data / "tree.ged").write_text(tree, encoding="utf-8")
    for name, obj in {
        "familysearch": dict(kekule={"1": "AAAA-BBB"}, ged={"@I2@": "CCCC-DDD", "@I3@": "EEEE-FFF"}),
        "web": dict(velka_rodina=dict(ged="data/tree.ged", koren="@I1@", overeno=["@I2@", "@I3@"])),
        "zaznamy": [dict(klic=k, druh="O", datum=d, odkaz=URL) for k, d in
                    [("first", "2. 1. 1820"), ("second", "3. 2. 1851")]],
        "vetve": {},
    }.items():
        sync.save_json(data / (name + ".json"), obj)
    return sync.load_local(tmp_path)


@pytest.mark.parametrize("second", [True, False])
def test_loader_matches_each_marriage_to_its_own_named_partner(tmp_path, second):
    loc = marriage_tree(tmp_path, ["× 2. 1. 1820 Marie Malá", "× 3. 2. 1851 Anna Velká"], second)
    marriages = loc["k:1"]["facts"]
    assert marriages[0].get("spouse") == "g:@I2@"
    assert marriages[1].get("spouse") == ("g:@I3@" if second else None)


def test_loader_can_match_marriage_by_gedcom_family_date(tmp_path):
    loc = marriage_tree(tmp_path, ["× 2. 1. 1820", "× 3. 2. 1851"], family_dates=True)
    assert [f.get("spouse") for f in loc["k:1"]["facts"]] == ["g:@I2@", "g:@I3@"]


def test_two_matching_couples_with_different_spouses_are_not_conflicts(tmp_path):
    loc = marriage_tree(tmp_path, ["× 2. 1. 1820 Marie Malá", "× 3. 2. 1851 Anna Velká"])
    s = snapshot(remote(), remote("CCCC-DDD"), remote("EEEE-FFF"))
    s["relationships"] = [dict(id=rid, type=TYPE + "Couple", person1=dict(resourceId="AAAA-BBB"),
                               person2=dict(resourceId=pid),
                               facts=[dict(type=TYPE + "Marriage", date=dict(formal=date))])
                          for rid, pid, date in [("couple1", "CCCC-DDD", "+1820-01-02"),
                                                  ("couple2", "EEEE-FFF", "+1851-02-03")]]
    plan = sync.build_plan(loc, s)
    assert not plan["conflicts"]
    assert not any(i.get("type") == "Marriage" for i in plan["items"])


def test_unresolved_second_marriage_is_manual_without_first_wife_conflict(tmp_path):
    loc = marriage_tree(tmp_path, ["× 2. 1. 1820 Marie Malá", "× 3. 2. 1851 Anna Velká"], second=False)
    s = snapshot(remote(), remote("CCCC-DDD"), remote("EEEE-FFF"))
    s["relationships"] = [dict(id="couple1", type=TYPE + "Couple", person1=dict(resourceId="AAAA-BBB"),
                               person2=dict(resourceId="CCCC-DDD"),
                               facts=[dict(type=TYPE + "Marriage", date=dict(formal="+1820-01-02"))]),
                          dict(id="couple2", type=TYPE + "Couple", person1=dict(resourceId="AAAA-BBB"),
                               person2=dict(resourceId="EEEE-FFF"),
                               facts=[dict(type=TYPE + "Marriage", date=dict(formal="+1851-02-03"))])]
    plan = sync.build_plan(loc, s)
    assert not plan["conflicts"]
    assert not any(i.get("type") == "Marriage" for i in plan["items"])
    assert any(m["local"] == "k:1" and m.get("date") == "+1851-02-03" for m in plan["manual"])


def death_tree(tmp_path, date, transcript, summary="", facts=None, title="Zápis"):
    marriage_tree(tmp_path, [])
    p = {1: dict(n="Jan Novák", y="1600–1900", st="doc", f=facts or ["† " + date], r=["death"])}
    (tmp_path / "data/osoby.py").write_text("P = " + repr(p) + "\nSIDE=[]\nSAME={}\n", encoding="utf-8")
    sync.save_json(tmp_path / "data/zaznamy.json", [dict(klic="death", druh="Z", datum=date,
                   odkaz=URL, nazev=title, shrnuti=summary)])
    sync.save_json(tmp_path / "data/prepisy.json", {"death": transcript})
    return sync.load_local(tmp_path)


# Krátké výňatky prepisy.json z případů vypsaných v pom_fs_rozpory/navrhy.md.
@pytest.mark.parametrize("key,date,orig,cs", [
    (1153, "18. 2. 1726", "Pochowana gest Worssila stará Dunowska, wěku swého 60 let.",
     "18. února 1726 byla pohřbena Voršila, stará Novotná ze Lhoty."),
    (1648, "4. 11. 1706", "Den 4. Novembr. ist begraben word. Gregor Zwettler von Erdweiss.", ""),
    (1649, "19. 5. 1724", "Den 19. May ist begraben worden Maria Zwettlerin von Erdweiss.", ""),
    (1650, "27. 7. 1706", "Den 27. [Julij] ist begraben worden Augustin Räml.", ""),
    (1651, "27. 3. 1706", "Den 27. Martij ist begrab. Christina Rämlin.", ""),
    (1656, "18. 7. 1703", "Den 18. Julij Adam Prenner von Dietmans seines alters 50 Jahr.",
     "18. 7. 1703 pohřben Adam Prenner z Dietmanns, 50 let."),
    (1660, "9. 2. 1746", "9. Sepultus est Marcus Miedler ex Aichberg aetatis suae 64 an.",
     "9. února pohřben Marcus Miedler z Eichbergu, 64 let."),
    (1662, "6. 4. 1758", "6. Ist begraben worden Adam Romeder ein Köch(?) zu St. Martin.", ""),
    (3315, "16. 1. 1695", "16 huius Sep. est Maria Meindlin ex Dietmans 71 annorum aetatis.", ""),
    (3316, "13. 10. 1699", "13 Jacob Zwettler von alten Waittra circiter 70 annorum.",
     "13. října 1699 pohřben Jacob Zwettler z Altweitry, asi 70 let."),
    (3317, "30. 5. 1680", "Altenweittra den 2[8?] Maij. Obiit in Dno virtuosa Dna Ursula. "
     "30 huius honeste sepulta.", "V květnu 1680 zemřela Uršula; pohřbena 30. května. Den úmrtí je přepsaný."),
    (577, "11. 8. 1738", "Pohřbena při chrámu Páně Paračowském, Alžbieta Dunowska hospodyně.", ""),
    (828, "4. 5. 1743", "[4?] huius Urban Prenner von Ditmans alt 50 Jahr.",
     "pohřben Urban Prenner z Dietmanns, 50 let (den 1 nebo 4)."),
])
def test_loader_never_refines_death_from_reviewed_burials(tmp_path, key, date, orig, cs):
    loc = death_tree(tmp_path, date, dict(orig=orig, cs=cs))
    facts = loc["k:1"]["facts"]
    assert all(f["type"] == "Burial" for f in facts), key
    if key != 828:
        assert any(f["type"] == "Burial" for f in facts), key
    else:
        assert facts == []  # Přepis nejistý den nedokládá.
    s = snapshot(remote())
    s["persons"]["AAAA-BBB"]["facts"] = [dict(id="death1", type=TYPE + "Death", date={})]
    assert not any(i.get("type") == "Death" for i in sync.build_plan(loc, s)["items"])


@pytest.mark.parametrize("transcript,summary,facts", [
    ({}, "Pohřeb Jana", None),
    ({"orig": "[Begräbnis] 2. 1. 1800"}, "", None),
    ({"orig": "[Burial] 2. 1. 1800"}, "", None),
    ({"orig": "Pochován Jan Novák"}, "", None),
    ({}, "", ["† 2. 1. 1800 (pohřeb)"]),
    ({}, "", ["pohřben 2. 1. 1800"]),
])
def test_burial_can_be_identified_from_summary_column_or_local_fact(tmp_path, transcript, summary, facts):
    loc = death_tree(tmp_path, "2. 1. 1800", transcript, summary, facts)
    assert [(f["type"], f["date"]) for f in loc["k:1"]["facts"]] == [("Burial", "+1800-01-02")]


@pytest.mark.parametrize("transcript", [
    {"cs": "Zemřel 2. 1. 1800; pohřben 4. 1. 1800."},
    {"orig": "[Úmrtí] 2. 1. 1800\n[Pohřeb] 4. 1. 1800"},
    {"cs": "Jan zemřel 2. ledna 1800 a byl pohřben 4. ledna 1800."},
    {"orig": "[Úmrtí / pohřeb] 1800, 2. ledna / 4. ledna"},
    {"cs": "Dne 2. ledna 1800 zemřel Jan a 4. ledna byl pohřben. Narodil se 5. 8. 1734."},
    {"orig": "[Sterbetag] 2. Januar 1800\n[Beerdigung] 4. Januar\n[Alter] geboren 5. VIII. 1734"},
    {"orig": "[Úmrtí] 2. ledna 1800\n[Zemřelý] Jan, narozený 5. srpna 1734\n[Pohřeb] 4. ledna"},
    {"orig": "[Úmrtí / pohřeb] 2. / 4. ledna 1800"},
    {"cs": "Jan zemřel v noci 2. ledna 1800 a pohřben byl 4. ledna."},
    {"orig": "1800, zemř. 2. ledna, pohřben 4. ledna."},
])
def test_explicit_death_and_burial_dates_stay_separate(tmp_path, transcript):
    loc = death_tree(tmp_path, "2. 1. 1800", transcript)
    assert {(f["type"], f["date"]) for f in loc["k:1"]["facts"]} == {
        ("Death", "+1800-01-02"), ("Burial", "+1800-01-04")}
    s = snapshot(remote())
    s["persons"]["AAAA-BBB"]["facts"] = [dict(id="death1", type=TYPE + "Death", date={})]
    updates = [i for i in sync.build_plan(loc, s)["items"] if i["kind"] == "fact-update"]
    assert [(i["type"], i["date"]) for i in updates] == [("Death", "+1800-01-02")]


def test_uncertain_death_date_never_becomes_a_refinement(tmp_path):
    loc = death_tree(tmp_path, "4. 1. 1800", dict(orig="[Úmrtí] 2. 1. 1800 (?)\n[Pohřeb] 4. 1. 1800"))
    assert [(f["type"], f["date"]) for f in loc["k:1"]["facts"]] == [("Burial", "+1800-01-04")]


def test_burial_location_does_not_turn_stillbirth_date_into_burial(tmp_path):
    loc = death_tree(tmp_path, "2. 1. 1800", dict(
        orig="[2. 1. 1800] Mrtvě narozený syn Jana Nováka | pohřben u sv. Anny",
        cs="Dne 2. 1. 1800 se narodil mrtvý syn Jana Nováka."))
    assert not any(f["type"] == "Burial" for f in loc["k:1"]["facts"])


@pytest.mark.parametrize("title,summary", [
    ("Úmrtí 2. 1. 1800", ""),
    ("Úmrtí Jana", "Zemřel 2. 1. 1800."),
])
def test_burial_transcript_overrides_generic_death_description(tmp_path, title, summary):
    loc = death_tree(tmp_path, "2. 1. 1800", dict(orig="Den 2. ist begraben worden Jan Novak."),
                     summary=summary, title=title)
    assert [(f["type"], f["date"]) for f in loc["k:1"]["facts"]] == [("Burial", "+1800-01-02")]


def test_burial_date_does_not_come_from_next_person_in_summary(tmp_path):
    loc = death_tree(tmp_path, "6. 4. 1758", dict(
        orig="6. Ist begraben worden Adam Romeder ein Köch(?) zu St. Martin.",
        cs="6. dubna 1758 pohřben Adam Romeder. Na téže stránce 15. 5. 1758 Regina Romederin."))
    assert [(f["type"], f["date"]) for f in loc["k:1"]["facts"]] == [("Burial", "+1758-04-06")]


def test_fact_proof_must_match_full_date_and_not_promote_gedcom_estimate():
    recs = {"x": dict(klic="x", druh="N", datum="3. 1. 1800", odkaz=URL)}
    assert sync.backed_facts(dict(f=["* 2. 1. 1800"], r=["x"]), recs) == []
    assert sync.backed_facts(dict(f=["* asi 1800", "* 2. 1. 1800 (?)"], r=["x"]), recs) == []


def test_map_cli_is_rerunnable_and_revalidates_proposed_ids(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    mapping = data / "familysearch.json"
    mapping.write_text('{"kekule": {}, "ged": {}}\n', encoding="utf-8")
    snap = snapshot(remote(birth="+1800-01-02"), remote("CCCC-DDD", "Josef Novák"))
    snap["relationships"] = [dict(type=TYPE+"ParentChild", person1=dict(resourceId="CCCC-DDD"),
                                  person2=dict(resourceId="AAAA-BBB"))]
    p, dad = person(fs=None), person("Josef Novák", "CCCC-DDD")
    p["parents"] = ["dad"]
    dad.update(keys=[], facts=[], sources=[])
    def current_local():
        p["fs"] = sync.read_json(mapping)["kekule"].get("8")
        return {"x": p, "dad": dad}
    plan = sync.build_plan(current_local(), snap)
    snap_path, plan_path = tmp_path / "snapshot.json", tmp_path / "plan.json"
    sync.save_json(snap_path, snap)
    plan.update(reviewed=True, snapshot_file=str(snap_path))
    sync.save_json(plan_path, plan)
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "load_local", current_local)
    sync.main(["map", str(plan_path)])
    before = mapping.read_bytes()
    sync.main(["map", str(plan_path)])
    assert mapping.read_bytes() == before
    plan["mappings"][0]["fs"] = "EEEE-FFF"
    sync.save_json(plan_path, plan)
    with pytest.raises(ValueError):
        sync.main(["map", str(plan_path)])
    assert mapping.read_bytes() == before


def test_browser_sync_with_fake_fs():
    script = Path(__file__).with_name("fs_sync_browser.cjs")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_browser_pacing_uses_worker_timer():
    script = Path(__file__).with_name("fs_spanek.cjs")
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_couple_precedes_marriage_and_rerun_only_keeps_missing_fact():
    p, spouse = person(), person("Marie Malá", "CCCC-DDD")
    p["facts"] = [dict(type="Marriage", date="+1820-01-02", spouse="wife",
                       image=URL, reason="Sňatek ze snímku", record="snatek")]
    spouse["facts"] = []
    loc, snap = dict(husband=p, wife=spouse), snapshot(remote(), remote("CCCC-DDD"))
    items = [i for i in sync.build_plan(loc, snap)["items"] if i.get("type") == "Marriage"]
    assert [i["kind"] for i in items] == ["couple", "fact"]
    assert all(i["spouse"] == "CCCC-DDD" and URL in i["reason"] for i in items)
    snap["relationships"] = [dict(id="couple1", type=TYPE + "Couple",
        person1=dict(resourceId="CCCC-DDD"), person2=dict(resourceId="AAAA-BBB"), facts=[])]
    assert [i["kind"] for i in sync.build_plan(loc, snap)["items"] if i.get("type") == "Marriage"] == ["fact"]
    snap["relationships"][0]["facts"] = [dict(type=TYPE + "Marriage", date=dict(formal="+1820-01-02"))]
    assert not any(i.get("type") == "Marriage" for i in sync.build_plan(loc, snap)["items"])
    spouse["st"] = "prob"
    snap["relationships"] = []
    assert not any(i.get("type") == "Marriage" for i in sync.build_plan(loc, snap)["items"])


def test_merge_is_report_only_even_when_target_matches():
    p = person()
    s = snapshot(remote("CCCC-DDD", birth="+1800-01-02"))
    s["merged"] = {"AAAA-BBB": "CCCC-DDD"}
    plan = sync.build_plan({"x": p}, s)
    assert plan["id_changes"] == [dict(local="x", name=p["name"], old="AAAA-BBB", new="CCCC-DDD",
                                       reason="ID změněno, aktualizujte data/familysearch.json po ověření jména, narození a rodiče")]
    assert plan["mappings"] == []
    assert plan["items"] == []


def couple(a, b):
    return dict(type=TYPE + "Couple", person1=dict(resourceId=a), person2=dict(resourceId=b))


def parent_child(a, b):
    return dict(type=TYPE + "ParentChild", person1=dict(resourceId=a), person2=dict(resourceId=b))


def test_exact_birth_and_mapped_spouse_maps_automatically():
    wife, husband = person("Anna Nováková", fs=None), person("Josef Novák", "CCCC-DDD")
    wife.update(keys=[["ged", "@I5@"]], spouses=["h"])
    s = snapshot(remote(name="Anna Nováková", birth="+1800-01-02"), remote("CCCC-DDD", "Josef Novák"))
    s["relationships"] = [couple("CCCC-DDD", "AAAA-BBB")]
    plan = sync.build_plan(dict(w=wife, h=husband), s)
    assert plan["mappings"] == [dict(local="w", group="ged", key="@I5@", fs="AAAA-BBB")]
    assert plan["mapping_review"] == []


def test_year_only_birth_or_surname_form_goes_to_review_not_mapping():
    child, dad = person("Marie Urbanová", fs=None), person("Franz Urban", "CCCC-DDD")
    child.update(birth="+1850", parents=["dad"], keys=[["ged", "@I7@"]])
    s = snapshot(remote(name="Maria Anna Urban", birth="+1850-03-04"), remote("CCCC-DDD", "Franz Urban"),
                 remote("EEEE-FFF", "Maria Urban", birth="+1852"))
    s["relationships"] = [parent_child("CCCC-DDD", "AAAA-BBB"), parent_child("CCCC-DDD", "EEEE-FFF")]
    plan = sync.build_plan(dict(c=child, dad=dad), s)
    assert plan["mappings"] == []
    assert [(r["local"], r["fs"], r["link"]) for r in plan["mapping_review"]] == [("c", "AAAA-BBB", "rodič")]
    review = plan["mapping_review"][0]
    assert review["keys"] == [["ged", "@I7@"]] and review["fs_birth"] == "+1850-03-04"
    # Dva kandidáti téhož roku = nic k revizi, jen seznam k dohledání.
    s["persons"]["EEEE-FFF"] = remote("EEEE-FFF", "Maria Urban", birth="+1850")
    ambiguous = sync.build_plan(dict(c=child, dad=dad), s)
    assert ambiguous["mapping_review"] == []
    assert next(m for m in ambiguous["missing_ids"] + ambiguous["missing_ids_other"] if m["local"] == "c")["candidates"] \
        == ["AAAA-BBB", "EEEE-FFF"]


def test_mapped_child_links_parent_only_for_review():
    dad, child = person("Franz Urban", fs=None), person("Johann Urban", "CCCC-DDD")
    dad.update(keys=[["ged", "@I9@"]])
    child["parents"] = ["dad"]
    s = snapshot(remote(name="Franz Urban", birth="+1800-01-02"), remote("CCCC-DDD", "Johann Urban"))
    s["relationships"] = [parent_child("AAAA-BBB", "CCCC-DDD")]
    plan = sync.build_plan(dict(dad=dad, c=child), s)
    assert plan["mappings"] == []
    assert [(r["local"], r["fs"], r["link"]) for r in plan["mapping_review"]] == [("dad", "AAAA-BBB", "dítě")]


def test_map_cli_accepts_reviewed_candidate_only(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    mapping = data / "familysearch.json"
    mapping.write_text('{"kekule": {}, "ged": {}}\n', encoding="utf-8")
    child, dad = person("Marie Urbanová", fs=None), person("Franz Urban", "CCCC-DDD")
    child.update(birth="+1850", parents=["dad"], keys=[["ged", "@I7@"]])
    snap = snapshot(remote(name="Maria Urban", birth="+1850-03-04"), remote("CCCC-DDD", "Franz Urban"))
    snap["relationships"] = [parent_child("CCCC-DDD", "AAAA-BBB")]
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "load_local", lambda: dict(c=child, dad=dad))
    plan = sync.build_plan(dict(c=child, dad=dad), snap)
    snap_path, plan_path = tmp_path / "snapshot.json", tmp_path / "plan.json"
    sync.save_json(snap_path, snap)
    review = plan["mapping_review"][0]
    plan.update(reviewed=True, snapshot_file=str(snap_path),
                mappings=[dict(local="c", group=g, key=k, fs=review["fs"]) for g, k in review["keys"]])
    sync.save_json(plan_path, plan)
    sync.main(["map", str(plan_path)])
    assert sync.read_json(mapping)["ged"] == {"@I7@": "AAAA-BBB"}
    mapping.write_text('{"kekule": {}, "ged": {}}\n', encoding="utf-8")
    sync.save_json(plan_path, dict(plan, mappings=[review]))
    sync.main(["map", str(plan_path)])
    assert sync.read_json(mapping)["ged"] == {"@I7@": "AAAA-BBB"}
    mapping.write_text('{"kekule": {}, "ged": {}}\n', encoding="utf-8")
    plan["mappings"][0]["fs"] = "EEEE-FFF"
    sync.save_json(plan_path, plan)
    with pytest.raises(ValueError):
        sync.main(["map", str(plan_path)])


def test_mapping_requires_full_birth_date_even_with_matching_parent():
    p, dad = person(fs=None), person("Josef Novák", "CCCC-DDD")
    p.update(birth="+1800", parents=["dad"])
    s = snapshot(remote(birth="+1800"), remote("CCCC-DDD", "Josef Novák"))
    s["relationships"] = [dict(type=TYPE + "ParentChild", person1=dict(resourceId="CCCC-DDD"),
                               person2=dict(resourceId="AAAA-BBB"))]
    assert sync.build_plan(dict(child=p, dad=dad), s)["mappings"] == []


def test_tasks_are_sorted_classified_and_keep_record_ids():
    direct, sibling, distant = person(), person("Marie Nováková", "CCCC-DDD"), person("Cizí", "EEEE-FFF")
    direct["keys"] = [["kekule", "8"]]
    direct["parents"] = ["dad"]
    sibling.update(keys=[["ged", "@I2@"]], parents=["dad"])
    distant.update(keys=[["ged", "@I3@"]], parents=[])
    dad = person("Josef Novák", "GGGG-HHH")
    dad["keys"] = [["kekule", "16"]]
    s = snapshot()
    s["tasks_read"] = True
    s["tasks_raw"] = {"summaries": [
        dict(personId="EEEE-FFF", name="Cizí", closeness=10, NEW_PERSON=["r3"]),
        dict(personId="CCCC-DDD", name="Marie Nováková", closeness=59, NEW_SOURCE=["r2"]),
        dict(personId="AAAA-BBB", name="Jan Novák", closeness=1, NEW_SOURCE=["r1", "r4"]),
        dict(personId="IIII-JJJ", name="FS blízký", closeness=59, NEW_PERSON="r5"),
        dict(personId="KKKK-LLL", name="FS vzdálený", closeness=60, NEW_SOURCE="r6"),
    ]}
    loc = dict(line=direct, sister=sibling, other=distant, dad=dad)
    # Výchozí výpis zahrnuje všechny a řadí je podle vztahu a blízkosti.
    everyone = sync.build_plan(loc, s)
    assert [t["fs"] for t in everyone["tasks_close"]] == ["AAAA-BBB", "CCCC-DDD", "EEEE-FFF", "IIII-JJJ", "KKKK-LLL"]
    assert everyone["tasks_distant"] == [] and everyone["task_closeness"] is None
    plan = sync.build_plan(loc, s, task_closeness=59)
    assert [t["fs"] for t in plan["tasks_close"]] == ["AAAA-BBB", "CCCC-DDD", "IIII-JJJ"]
    assert {t["fs"] for t in plan["tasks_distant"]} == {"EEEE-FFF", "KKKK-LLL"}
    task = plan["tasks_close"][0]
    assert task["local"] == "line" and task["name"] == "Jan Novák"
    assert task["hint_type"] == "NEW_SOURCE" and task["record_ids"] == ["r1", "r4"]
    assert all(t["fs"] != "IIII-JJJ" for t in sync.build_plan(loc, s, task_closeness=58)["tasks_close"])
    rendered = sync.markdown(plan)
    assert "Úkoly: řešit" in rendered and "Úkoly: jen vypsat" in rendered


def test_unknown_task_format_is_never_actionable():
    s = snapshot()
    s.update(tasks_read=True, tasks_raw={"unknown": [dict(personId="AAAA-BBB", NEW_SOURCE="r1")]})
    plan = sync.build_plan({"x": person()}, s)
    assert not plan["tasks_read"]
    assert plan["tasks_close"] == []
    assert plan["tasks_raw"] == s["tasks_raw"]


def test_live_opportunities_person_summaries_and_record_types():
    s = snapshot(remote())
    s.update(tasks_read=True, tasks_raw={"count": 2, "hasMore": False, "personSummaries": [
        {"personId": "AAAA-BBB", "closeness": 29.5562243957226, "hasRecord": True,
         "recordTypes": {"NEW_CONCLUSION": ["TEST-REC"], "NEW_PERSON": [], "NEW_SOURCE": [], "OTHER": ["DEMO-REC"]}},
        {"personId": "CCCC-DDD", "closeness": 59.1124487914452,
         "recordTypes": {"NEW_SOURCE": ["FVZC-9P5"], "NEW_PERSON": []}},
    ]})
    assert len(sync.build_plan({}, s)["tasks_close"]) == 3
    plan = sync.build_plan({}, s, task_closeness=59)
    assert plan["tasks_read"]
    assert len(plan["tasks_close"]) == 2
    assert {t["hint_type"] for t in plan["tasks_close"]} == {"NEW_CONCLUSION", "OTHER"}
    assert plan["tasks_close"][0]["name"] == "Johann Novák"
    assert len(plan["tasks_distant"]) == 1


def test_missing_ids_separate_documented_and_tree_only_and_prioritize_line():
    line, sibling, other, tree = [person(fs=None) for _ in range(4)]
    line.update(parents=["dad"], records=["krest"])
    sibling.update(keys=[["ged", "@I2@"]], parents=["dad"], records=["krest"])
    other.update(keys=[["ged", "@I3@"]], records=["krest"])
    tree.update(keys=[["ged", "@I4@"]], st="mh", facts=[], sources=[])
    dad = person(fs="CCCC-DDD")
    dad["keys"] = [["kekule", "16"]]
    plan = sync.build_plan(dict(z=line, b=sibling, a=other, mh=tree, dad=dad), snapshot())
    assert [p["local"] for p in plan["missing_ids"]] == ["z", "b", "a"]
    assert [p["local"] for p in plan["missing_ids_other"]] == ["mh"]
    rendered = sync.markdown(plan)
    assert '"local": "mh"' not in rendered
    assert "Ostatní bez FS ID: 1" in rendered


def test_scope_incremental_cache_uses_per_person_age_not_snapshot_age(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "load_local", lambda: {"x": person()})
    now = sync.dt.datetime.now(sync.dt.timezone.utc)
    s = snapshot()
    s["captured_at"] = now.isoformat()
    s["record_matches"] = {"AAAA-BBB": {"matches": []}, "CCCC-DDD": {}, "EEEE-FFF": {}, "GGGG-HHH": {}}
    s["record_matches_read"] = {
        "AAAA-BBB": (now - sync.dt.timedelta(days=2)).isoformat(),
        "CCCC-DDD": (now - sync.dt.timedelta(days=8)).isoformat(),
        "EEEE-FFF": (now + sync.dt.timedelta(days=1)).isoformat(),
        "GGGG-HHH": "bad date",
    }
    previous = tmp_path / "previous.json"
    sync.save_json(previous, s)
    sync.main(["scope", "--since", str(previous), "--matches-max-age-days", "7"])
    cfg = sync.read_json(tmp_path / "pracovni/fs_sync/scope.json")
    assert set(cfg["cachedMatches"]) == {"AAAA-BBB"}
    assert cfg["cachedMatches"]["AAAA-BBB"]["read_at"] == s["record_matches_read"]["AAAA-BBB"]
    sync.main(["scope"])
    assert not sync.read_json(tmp_path / "pracovni/fs_sync/scope.json").get("cachedMatches")


def test_legacy_incremental_cache_only_includes_successfully_read_matches():
    now = sync.dt.datetime.now(sync.dt.timezone.utc)
    s = snapshot()
    s["captured_at"] = now.isoformat()
    s["record_matches"] = {"AAAA-BBB": {"matches": []}, "CCCC-DDD": None}
    assert set(sync.cached_matches(s, 7, now)) == {"AAAA-BBB"}


def mh_hint(total, *details, link="https://www.myheritage.com/matchingresult-abc?lang=EN"):
    return dict(totalHints=total, hintDetails=[dict(type=t, name=n, modifier="adds") for t, n in details],
                factorsDescription="Adds: " + ", ".join(n for _, n in details), link=link)


def test_myheritage_matches_are_sorted_like_tasks_and_never_become_items():
    direct, sibling, distant = person(), person("Marie Nováková", "CCCC-DDD"), person("Cizí", "EEEE-FFF")
    direct["parents"] = ["dad"]
    sibling.update(keys=[["ged", "@I2@"]], parents=["dad"])
    distant.update(keys=[["ged", "@I3@"]], parents=[])
    dad = person("Josef Novák", "GGGG-HHH")
    dad["keys"] = [["kekule", "16"]]
    loc = dict(line=direct, sister=sibling, other=distant, dad=dad)
    s = snapshot(remote(), remote("CCCC-DDD"), remote("EEEE-FFF"), remote("GGGG-HHH"), remote("IIII-JJJ", "FS blízký"))
    base = sync.build_plan(loc, s)
    s["myheritage"] = {
        "EEEE-FFF": mh_hint(3, ("story", "story"), ("source", "source")),
        "CCCC-DDD": mh_hint(1, ("record", "residence"), ("record", "sibling(s)"), ("source", "source")),
        "AAAA-BBB": mh_hint(6, ("record", "birth place")),
        "GGGG-HHH": mh_hint(0),
        "IIII-JJJ": mh_hint(2, ("record", "death"), link="javascript:alert(1)"),
    }
    s["myheritage_read"] = {k: "2026-11-19T10:00:00Z" for k in s["myheritage"]}
    s["tasks_read"] = True
    s["tasks_raw"] = {"personSummaries": [dict(personId="IIII-JJJ", closeness=40, recordTypes={})]}
    assert all(r["close"] for r in sync.build_plan(loc, s)["myheritage"]), "bez hranice se řeší všichni"
    plan = sync.build_plan(loc, s, task_closeness=59)
    assert plan["items"] == base["items"], "shoda MyHeritage je jen stopa, ne zápis"
    rows = plan["myheritage"]
    assert [r["fs"] for r in rows] == ["AAAA-BBB", "CCCC-DDD", "EEEE-FFF", "IIII-JJJ"]
    assert [r["close"] for r in rows] == [True, True, False, True]
    first = rows[0]
    assert first["name"] == "Jan Novák" and first["local"] == "line" and first["relation"] == "přímá linie"
    assert first["total"] == 6 and first["link"].startswith("https://www.myheritage.com/")
    assert rows[1]["record"] is True and rows[1]["record_adds"] == ["residence", "sibling(s)"]
    assert rows[1]["other_adds"] == ["source"]
    assert rows[2]["record"] is False and rows[2]["other_adds"] == ["story", "source"]
    assert rows[3]["closeness"] == 40 and rows[3]["link"] is None, "jen odkaz na myheritage.com"
    assert plan["myheritage_summary"] == dict(read=5, with_hints=4, zero=1, unread=0)
    rendered = sync.markdown(plan)
    section = rendered.split("## Shody MyHeritage", 1)[1]
    assert "Jan Novák" in section and "line" in section and "záznam" in section
    assert "https://www.myheritage.com/matchingresult-abc" in section
    assert "Josef Novák" not in section, "osoba s 0 shodami se nevypisuje"


def test_myheritage_distinguishes_unread_from_zero():
    s = snapshot(remote(), remote("CCCC-DDD"))
    s["myheritage"] = {"AAAA-BBB": mh_hint(0)}
    plan = sync.build_plan({"x": person(), "y": person("Marie", "CCCC-DDD")}, s)
    assert plan["myheritage"] == []
    assert plan["myheritage_summary"] == dict(read=1, with_hints=0, zero=1, unread=1)
    legacy = sync.build_plan({"x": person()}, snapshot(remote()))
    assert legacy["myheritage_summary"]["read"] == 0 and legacy["myheritage_summary"]["unread"] == 1
    assert "nečteno: 1" in sync.markdown(legacy)


def test_scope_can_disable_or_reuse_recent_myheritage(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "load_local", lambda: {"x": person()})
    now = sync.dt.datetime.now(sync.dt.timezone.utc)
    s = snapshot()
    s["myheritage"] = {"AAAA-BBB": mh_hint(0), "CCCC-DDD": mh_hint(1, ("record", "residence"))}
    s["myheritage_read"] = {"AAAA-BBB": (now - sync.dt.timedelta(days=1)).isoformat(),
                            "CCCC-DDD": (now - sync.dt.timedelta(days=9)).isoformat()}
    previous = tmp_path / "previous.json"
    sync.save_json(previous, s)
    sync.main(["scope", "--since", str(previous), "--myheritage-max-age-days", "7"])
    cfg = sync.read_json(tmp_path / "pracovni/fs_sync/scope.json")
    assert cfg["myheritage"] is True
    assert set(cfg["cachedMyHeritage"]) == {"AAAA-BBB"}
    assert cfg["cachedMyHeritage"]["AAAA-BBB"]["data"]["totalHints"] == 0
    sync.main(["scope", "--no-myheritage"])
    cfg = sync.read_json(tmp_path / "pracovni/fs_sync/scope.json")
    assert cfg["myheritage"] is False and "cachedMyHeritage" not in cfg


def test_scope_reads_neighbours_at_two_seconds_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "load_local", lambda: {"x": person()})
    sync.main(["scope"])
    cfg = sync.read_json(tmp_path / "pracovni/fs_sync/scope.json")
    assert cfg["neighbours"] is True and cfg["pace"] == 2000
    sync.main(["scope", "--no-neighbours", "--pace", "1100"])
    cfg = sync.read_json(tmp_path / "pracovni/fs_sync/scope.json")
    assert cfg["neighbours"] is False and cfg["pace"] == 1100


def test_ged_citation_of_own_name_is_review_candidate_and_lookup(tmp_path, monkeypatch):
    ged = tmp_path / "strom.ged"
    ged.write_text("0 @I5@ INDI\n1 NAME Marie /Urbanová/\n1 NOTE <p>FamilySearch Family Tree, entry for Maria Ur\n"
                   "2 CONC ban, person ID AAAA-BBB.</p> entry for Josef Urban, person ID CCCC-DDD.\n"
                   "0 @I6@ INDI\n1 NAME X /Y/\n", encoding="utf-8")
    cites = sync.ged_citations(ged)
    assert cites["@I5@"] == {("Maria Urban", "AAAA-BBB"), ("Josef Urban", "CCCC-DDD")}
    p = person("Marie Urbanová", fs=None)
    p.update(birth="+1850", keys=[["ged", "@I5@"]], fs_cited=["AAAA-BBB"])
    s = snapshot()
    s["relatives"] = {"AAAA-BBB": remote(name="Maria Urban", birth="+1850-02-03")}
    plan = sync.build_plan(dict(c=p), s)
    assert plan["mappings"] == []
    assert [(r["local"], r["fs"], r["link"]) for r in plan["mapping_review"]] == [("c", "AAAA-BBB", "citace")]
    s["relatives"]["AAAA-BBB"] = remote(name="Maria Urban", birth="+1851")
    assert sync.build_plan(dict(c=p), s)["mapping_review"] == [], "jiný rok narození nestačí ani s citací"
    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync, "load_local", lambda: dict(c=p, x=person(fs="CCCC-DDD")))
    sync.main(["scope"])
    assert sync.read_json(tmp_path / "pracovni/fs_sync/scope.json")["lookup"] == ["AAAA-BBB"]


def test_neighbours_from_snapshot_are_mapping_candidates_but_not_read_persons():
    child, dad = person("Marie Nováková", fs=None), person("Josef Novák", "CCCC-DDD")
    child.update(parents=["dad"], keys=[["ged", "@I3@"]])
    s = snapshot(remote("CCCC-DDD", "Josef Novák"))
    s["relatives"] = {"AAAA-BBB": remote(name="Marie Nováková", birth="+1800-01-02")}
    s["children"] = {"CCCC-DDD": ["AAAA-BBB"]}
    plan = sync.build_plan(dict(c=child, dad=dad), s)
    assert plan["mappings"] == [dict(local="c", group="ged", key="@I3@", fs="AAAA-BBB")]
    assert plan["unread"] == [] or all(u.get("fs") != "AAAA-BBB" for u in plan["unread"])
