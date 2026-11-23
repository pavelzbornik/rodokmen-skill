#!/usr/bin/env python3
"""Místní seznam úkolů pro výzkum podle údajů v projektu a importů FamilySearch."""
import argparse
from collections import defaultdict, deque
import datetime as dt
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fs_sync
import zamek
from web_pohledy import fold

SCITANI = (1869, 1880, 1890, 1900, 1910, 1921)
KROKY = {1: "Mapování FamilySearch", 2: "Co ještě přečíst na FamilySearch", 3: "Sčítání",
         4: "Křest", 5: "Zatím bez další stopy"}
SKUPINY = {"predci": "Přímá linie včetně kořene", "pokrevni": "Pokrevní příbuzní",
           "prizeneni": "Ostatní spojení s rodinou", "ostatni": "Osoby mimo známé vazby"}


def rok(text):
    m = re.search(r"\b\d{4}\b", text or "")
    return int(m[0]) if m else None


def obec(misto):
    misto = re.split(r"[,()]", misto, maxsplit=1)[0].strip()
    return re.sub(r"\s+(?:(?:čp|č\.?\s*p|Nro|No)\.?\s*)?\d+[a-z]?$", "", misto, flags=re.I)


def udaje(p):
    hints = p["research"]
    person = hints["person"]
    events = hints["events"]
    narozeni = events.get("BIRT", ["", ""])
    krest = events.get("CHR", ["", ""])
    umrti = events.get("DEAT", ["", ""])
    pohreb = events.get("BURI", ["", ""])
    roky = person.get("y") or ""
    od, _, do = re.sub(r"\s*([–—-])\s*", "–", roky).partition("–")
    if od.lstrip().startswith("†"):
        od, do = "", od
    rok_narozeni, rok_krtu = rok(narozeni[0]), rok(krest[0])
    by = rok(p.get("birth")) or rok(od) or rok_narozeni or rok_krtu
    nejiste = r"\b(?:asi|kolem|před|po|abt|cal|est|bef|aft|bet|from|to)\b|\?"
    by_priblizne = bool(by and (
        any(rok(datum) == by and re.search(nejiste, datum, re.I) for datum in (od, narozeni[0]))
        or not rok_narozeni and rok_krtu == by and not p.get("birth")))
    dy = rok(umrti[0]) or rok(pohreb[0]) or rok(do)
    odkud, kam = obec(narozeni[1] or krest[1]), obec(umrti[1] or pohreb[1])
    for fact in person.get("f", []):
        m = re.match(r"^\s*([*†])\s*(?:(\d{1,2}\.\s*\d{1,2}\.)\s*)?(\d{4})(?:\s+(.+))?$", fact)
        if m:
            year, misto = int(m[3]), obec(m[4] or "")
            if m[1] == "*":
                by_priblizne = by_priblizne and year == by and not m[2]
                by, odkud = year, misto or odkud
            else:
                dy, kam = year, misto or kam
    resi = events.get("RESI", ["", ""])
    return dict(by=by, by_priblizne=by_priblizne, dy=dy, rodiste=odkud, umrti=kam,
                bydleni=(rok(resi[0]), obec(resi[1])))


def vyber_snapshot(cesty):
    """Úspěšné čtení se počítá i s prázdným výsledkem a může pocházet z různých importů."""
    channels = {"zdroje": set(), "shody záznamů": set(), "shody MyHeritage": set()}
    targets = defaultdict(set)
    fields = (("zdroje", "sources", list), ("shody záznamů", "record_matches", (dict, list)),
              ("shody záznamů", "record_matches_read", str), ("shody MyHeritage", "myheritage", dict),
              ("shody MyHeritage", "myheritage_read", str))
    for path in sorted(cesty):
        snap = fs_sync.read_json(path)
        if (not isinstance(snap, dict) or snap.get("schema") != fs_sync.SCHEMA + "snapshot.v1"
                or not isinstance(snap.get("persons"), dict)):
            raise ValueError(f"Neplatný snapshot FamilySearch: {path.name}")
        for channel, field, valid in fields:
            data = snap.get(field, {})
            if isinstance(data, dict):
                channels[channel].update(pid for pid, value in data.items()
                                         if isinstance(value, valid) and (not isinstance(value, str) or value.strip()))
        merged = snap.get("merged")
        if isinstance(merged, dict):
            for original, target in merged.items():
                if isinstance(target, str) and fs_sync.PID.fullmatch(target):
                    targets[original].add(target)
    merged = {original: next(iter(new)) for original, new in targets.items() if len(new) == 1}
    for original in merged:
        target, seen = original, set()
        while target in merged and target not in seen:
            seen.add(target)
            target = merged[target]
        if target not in targets:
            for read in channels.values():
                if target in read:
                    read.add(original)
    return {name: ids for name, ids in channels.items() if ids or name == "zdroje"}


def vzdalenost(vazby, starts):
    dist = dict.fromkeys(starts, 0)
    queue = deque(dist)
    while queue:
        key = queue.popleft()
        for other in vazby[key]:
            if other not in dist:
                dist[other] = dist[key] + 1
                queue.append(other)
    return dist


def scitani_ctena(records):
    ctene = {}
    for record in records:
        if record.get("druh") == "S":
            m = re.search(r"(?:^|_)scitani_(\d{4})(?:_|$)", record["klic"])
            year = int(m[1]) if m else rok(record.get("datum"))
            if year:
                ctene[year] = record
    return ctene


def navrh_scitani(key, p, people, udalosti, deti, ctene):
    u = udalosti[key]
    by, dy = u["by"], u["dy"]
    if not by:
        return []
    navrhy = []
    marriages = p["research"]["marriages"]
    for year in SCITANI:
        if not by <= year <= (dy or by + 90) or year in ctene[key]:
            continue
        partneri = [other for other, marr in marriages.items() if marr <= year]
        domacnost = partneri + ([] if partneri else p["parents"])
        for other in domacnost:
            if year in ctene.get(other, {}) and people[other]["living"] is False:
                rec = ctene[other][year]
                popis = rec.get("nazev") or rec["klic"]
                navrhy.append((year, f"{popis} (domácnost příbuzného)"))
                break
        else:
            deti_v_letech = sorted((udalosti[c] for c in deti[key] if people[c]["living"] is False and udalosti[c]["by"]
                                    and year - 3 <= udalosti[c]["by"] <= year + 1 and udalosti[c]["rodiste"]),
                                   key=lambda d: abs(d["by"] - year))
            resi_year, resi_place = u["bydleni"]
            for place, source, near in ((deti_v_letech[0]["rodiste"] if deti_v_letech else "", "rodiště dítěte", True),
                                        (resi_place, "bydliště", resi_year and abs(resi_year - year) <= 10),
                                        (u["rodiste"], "rodiště", year - by <= 10),
                                        (u["umrti"], "místo úmrtí", dy and dy - year <= 10)):
                if place and near:
                    navrhy.append((year, f"{place} ({source})"))
                    break
    return navrhy


def stav(people, zaznamy, snapshot, fary, *, bez_scitani=False):
    if not isinstance(fary, dict) or any(not isinstance(value, dict) for value in fary.values()):
        raise ValueError('data/fary.json musí mít tvar {"obec": {"fara": "název"}}.')
    records = {r["klic"]: r for r in zaznamy}
    deti, vazby = defaultdict(list), defaultdict(set)
    for key, p in people.items():
        for par in p["parents"]:
            deti[par].append(key)
        for other in p["parents"] + p.get("spouses", []):
            vazby[key].add(other)
            vazby[other].add(key)
    prima = {key: p["research"]["k"] for key, p in people.items() if p["research"]["k"]}
    blizkost = vzdalenost(vazby, [key for key, k in prima.items() if k == 1] or prima)
    pokrevni = vzdalenost(deti, prima)
    udalosti = {key: udaje(p) for key, p in people.items()}
    ctene = {key: scitani_ctena(records[r] for r in p["records"] if r in records) for key, p in people.items()}
    rows = []
    for key, p in people.items():
        if p["living"] is not False:
            continue
        by, rodiste = udalosti[key]["by"], udalosti[key]["rodiste"]
        refs = sorted(set(p["records"]) & records.keys())
        has_birth_record = any(records[r].get("druh") == "N" for r in refs)
        fs = None if p.get("mapping_conflicts") else p["fs"]
        precteno = [name for name, ids in snapshot.items() if fs in ids]
        chybi = [name for name in snapshot if name not in precteno] if fs else []
        kroky = []
        if p.get("mapping_conflicts"):
            kroky.append((1, "ověřit rozporné místní mapování FamilySearch"))
        elif not fs:
            kroky.append((1, "dohledat osobu na FamilySearch"))
        elif chybi:
            kroky.append((2, "přečíst na FS: " + ", ".join(chybi)))
        scitani = [] if bez_scitani else navrh_scitani(key, p, people, udalosti, deti, ctene)
        if scitani:
            kroky.append((3, "; ".join(f"{year}: {place}" for year, place in scitani)))
        fara = fary.get(rodiste, {}).get("fara")
        if not has_birth_record and by and fara:
            priblizne = "okolo " if udalosti[key]["by_priblizne"] else ""
            kroky.append((4, f"křest {priblizne}{by}: {rodiste}, fara {fara}"))
        if not kroky:
            kroky.append((5, "zatím bez další stopy"))
        skupina = ("predci" if key in prima else "pokrevni" if key in pokrevni else
                   "prizeneni" if key in blizkost else "ostatni")
        rows.append(dict(id=key, keys=p["keys"], name=p["name"], k=prima.get(key), by=by, fs=fs, skupina=skupina,
                         fs_precteno=precteno, fs_neprecteno=chybi,
                         zapisy=refs, krest_cten=has_birth_record, scitani_ctena=sorted(ctene[key]),
                         scitani_chybi=scitani, kroky=kroky))
    return sorted(rows, key=lambda r: (list(SKUPINY).index(r["skupina"]), r["k"] or 0,
                                      blizkost.get(r["id"], float("inf")), r["by"] or 9999, r["name"], r["id"]))


def souhrn(rows):
    skupiny = {s: dict(celkem=0, zapis=0, fs=0) for s in SKUPINY}
    for r in rows:
        group = skupiny[r["skupina"]]
        group["celkem"] += 1
        group["zapis"] += bool(r["zapisy"])
        group["fs"] += bool(r["fs"])
    return skupiny


def rozdil(stary, novy):
    """Porovná záznamy podle místních identit, případně podle jednoznačného aliasu."""
    aliases = defaultdict(set)
    old = {r["id"]: r for r in stary}
    for r in stary:
        for key in r["keys"]:
            aliases[tuple(key)].add(r["id"])
    result = dict(nove_zapisy=[], nove_fs=[], splnene_kroky=[],
                  souhrn_pred=souhrn(stary), souhrn_po=souhrn(novy))
    for r in novy:
        matches = {match for key in r["keys"] for match in aliases[tuple(key)]}
        before = old.get(r["id"], old[next(iter(matches))] if len(matches) == 1 else {})
        delta = set(r["zapisy"]) - set(before.get("zapisy", []))
        if delta:
            result["nove_zapisy"].append(f"{r['name']} (+{len(delta)})" if before.get("zapisy") else r["name"])
        if r["fs"] and r["fs"] != before.get("fs"):
            result["nove_fs"].append(r["name"])
        before_steps = dict(before.get("kroky", []))
        if 1 in before_steps and r["fs"]:
            result["splnene_kroky"].append(f"{r['name']}: mapování FamilySearch")
        if (2 in before_steps and r["fs"] == before["fs"]
                and set(before["fs_neprecteno"]) <= set(r["fs_precteno"])):
            result["splnene_kroky"].append(f"{r['name']}: čtení na FamilySearch")
        for year, _ in before.get("scitani_chybi", []):
            if year in r["scitani_ctena"]:
                result["splnene_kroky"].append(f"{r['name']}: sčítání {year}")
        if 4 in before_steps and r["krest_cten"]:
            result["splnene_kroky"].append(f"{r['name']}: křest")
    return result


def markdown(rows, args):
    lines = ["# Pokrytí výzkumu", "", "| Skupina | Osob | Se zápisem | S FS ID |", "|---|---:|---:|---:|"]
    for group, counts in souhrn(rows).items():
        lines.append(f"| {SKUPINY[group]} | {counts['celkem']} | {counts['zapis']} | {counts['fs']} |")
    for k, title in KROKY.items():
        if args.krok and args.krok != k or args.obec and k not in (3, 4):
            continue
        tasks = [(r, text) for r in rows for step, text in r["kroky"] if step == k
                 and (not args.prijmeni or fold(args.prijmeni) in fold(r["name"]))
                 and (not args.obec or fold(args.obec) in fold(text))]
        if tasks:
            lines += ["", f"## {k}. {title} ({len(tasks)})", ""]
            lines += [f"- {r['name']} ({r['by'] or '?'}): {text}" for r, text in tasks[:args.max]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("ukoly", help="uloží místní přehled úkolů jako Markdown a JSON")
    r = sub.add_parser("rozdil", help="porovná stav se starším výstupem JSON")
    for parser in (u, r):
        parser.add_argument("--ged", type=Path, help="GEDCOM projektu, jinak hodnota velka_rodina.ged z data/web.json")
        parser.add_argument("--koren", help="identifikátor kořene v GEDCOMu, např. @I1@")
        parser.add_argument("--bez-scitani", action="store_true", help="bez návrhů sčítání pro české země")
    u.add_argument("--prijmeni", help="část jména (bez ohledu na diakritiku)")
    u.add_argument("--krok", type=int, choices=KROKY)
    u.add_argument("--obec", help="text obce v návrzích sčítání nebo křtu")
    u.add_argument("--max", type=int, default=60, help="nejvýš tolik osob na krok v Markdownu")
    r.add_argument("stary", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "ukoly" and args.max < 1:
        ap.error("--max musí být kladné.")
    root = fs_sync.ROOT
    try:
        people = fs_sync.load_local(root, ged_path=args.ged, ged_root=args.koren, research=True)
        snapshot = vyber_snapshot((root / "pracovni/fs_sync").glob("snapshot-*.json"))
        rows = stav(people, fs_sync.read_json(root / "data/zaznamy.json"), snapshot,
                    fs_sync.read_json(root / "data/fary.json", {}), bez_scitani=args.bez_scitani)
        if args.cmd == "rozdil":
            old = fs_sync.read_json(args.stary)
            print(json.dumps(rozdil(old, rows), ensure_ascii=False, indent=1))
            return
        out = root / "pracovni/pokryti"
        out.mkdir(parents=True, exist_ok=True)
        base = out / f"pokryti-{dt.datetime.now():%Y-%m-%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        md = base.with_suffix(".md")
        zamek.zapis_text(str(md), markdown(rows, args))
        try:
            zamek.zapis_text(str(base.with_suffix(".json")), json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
        except OSError:
            md.unlink(missing_ok=True)
            raise
        print(md)
        print(json.dumps(souhrn(rows), ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as e:
        ap.exit(2, f"Chyba: {e}\n")


if __name__ == "__main__":
    main()
