"""Rodokmen ke stažení jako GEDCOM 5.5.1 (web/public/rodokmen.ged).

Obsahuje přímé předky z data/osoby.py a ověřené příbuzné se stránkou (tools/pribuzni.py), rodiny mezi nimi
a matriční zápisy jako prameny s odkazem na snímek v archivu. Žijící lidé: jen jméno a rok narození, bez míst,
poznámek a pramenů. Rozšíření projektu, ve skillu rodokmen zatím není.
"""
import datetime, re

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DATE_RE = re.compile(r"^((?:asi|kolem|≈|před|po)\s+)?(?:(\d{1,2})\.\s*(\d{1,2})\.\s*|(\d{1,2})/)?(\d{4})")


def ged_date(text):
    """„5. 1. 1867“ → „5 JAN 1867“, „3/1867“ → „MAR 1867“, „asi 1808“ → „ABT 1808“, „před 1743“ → „BEF 1743“."""
    m = DATE_RE.match((text or "").strip())
    if not m:
        return ""
    pre, d, mo, mo2, y = m.groups()
    mo = mo or mo2
    parts = ([str(int(d))] if d else []) + ([MONTHS[int(mo) - 1]] if mo and 1 <= int(mo) <= 12 else []) + [y]
    qual = {"asi": "ABT ", "kolem": "ABT ", "≈": "ABT ", "před": "BEF ", "po": "AFT "}.get((pre or "").strip(), "")
    return qual + " ".join(parts)


def split_fact(fact, spouse=""):
    """„* 17. 5. 1834 Tišice čp. 2“ → („17. 5. 1834“, „Tišice čp. 2“); u sňatku se jméno partnera z konce odřízne."""
    rest = fact[1:].strip()
    m = DATE_RE.match(rest)
    date = m.group(0).strip() if m else ""
    place = rest[m.end():].strip(" ,") if m else rest
    if spouse and place.endswith(spouse):
        place = place[: -len(spouse)].strip(" ,")
    return date, place


FS_RE = re.compile(r"\b(?:FamilySearch|FS)\b[^.;]*?\bosob[ay]\s+([A-Z0-9]{4}-[A-Z0-9]{2,4})\b")


def fs_from_note(note):
    """ID osoby ve stromu FamilySearch z poznámky („… FamilySearch (osoba AAAA-BBB) …“), jinak None."""
    m = FS_RE.search(note or "")
    return m.group(1) if m else None


def fs_id(fsmap, k=None, gid=None, note=None):
    """FamilySearch ID osoby: data/familysearch.json (kekule podle čísla předka, ged podle id ve stromu), pak poznámka."""
    fsmap = fsmap or {}
    if k is not None and str(k) in fsmap.get("kekule", {}):
        return fsmap["kekule"][str(k)]
    if gid and gid in fsmap.get("ged", {}):
        return fsmap["ged"][gid]
    return fs_from_note(note)


def ged_name(name):
    """„Anna Letošníková (Kaubová ?)“ → „Anna /Letošníková/“ (závorky a „(?)“ pryč, příjmení = poslední slovo)."""
    words = re.sub(r"\([^)]*\)", " ", name or "").split()
    if len(words) < 2:
        return " ".join(words)
    return " ".join(words[:-1]) + f" /{words[-1]}/"


def _text(level, tag, value):
    """Řádek s textem: nové řádky jako CONT, dlouhé kusy jako CONC (řádek max. 255 znaků)."""
    out = []
    for n, para in enumerate(str(value).split("\n")):
        chunks = [para[i:i + 200] for i in range(0, len(para), 200)] or [""]
        for c, chunk in enumerate(chunks):
            if n == 0 and c == 0:
                out.append(f"{level} {tag} {chunk}".rstrip())
            else:
                out.append(f"{level + 1} {'CONC' if c else 'CONT'} {chunk}".rstrip())
    return out


def _event(tag, date, place, living):
    if living:
        y = re.search(r"\d{4}", date or "")
        return [f"1 {tag}", f"2 DATE {y.group(0)}"] if y and tag == "BIRT" else []
    g = ged_date(date)
    if not g and not place:
        return []
    return [f"1 {tag}"] + ([f"2 DATE {g}"] if g else []) + (_text(2, "PLAC", place) if place else [])


def build(people, families, title, sources=None):
    """people: [{id, name, male, birth: [datum, místo], death, living, note?, sources?: [klíč]}],
    families: [{id, husb?, wife?, children, marr?: [datum, místo]}], sources: {klíč: {title, text?, url?, archive?}}."""
    sources = sources or {}
    sid = {k: f"S{n}" for n, k in enumerate(sorted(sources), 1)}
    fams_of, famc_of = {}, {}
    for f in families:
        for x in (f.get("husb"), f.get("wife")):
            if x:
                fams_of.setdefault(x, []).append(f["id"])
        for c in f.get("children", []):
            famc_of.setdefault(c, []).append(f["id"])
    L = ["0 HEAD", "1 SOUR RODOKMEN", "2 NAME " + title, "1 DEST ANY", "1 DATE " + ged_date(datetime.date.today().strftime("%d. %m. %Y")).upper(),
         "1 GEDC", "2 VERS 5.5.1", "2 FORM LINEAGE-LINKED", "1 CHAR UTF-8", "1 LANG Czech"]
    used = set()
    for p in people:
        living = p.get("living")
        L.append(f"0 @{p['id']}@ INDI")
        L.append("1 NAME " + ged_name(p["name"]))
        L.append("1 SEX " + ("M" if p.get("male") else "F"))
        L += _event("BIRT", *p.get("birth", ["", ""]), living)
        if not living:
            L += _event("DEAT", *p.get("death", ["", ""]), living)
            if re.sub(r"\([^)]*\)", "", p["name"]).split() != p["name"].split():
                L += _text(1, "NOTE", "Jméno v rodokmenu: " + p["name"])
            if p.get("fs"):   # ID ve stromu FamilySearch (rozšíření GEDCOM 5.5.1 jako u RootsMagic / Ancestral Quest)
                L.append("1 _FSFTID " + p["fs"])
            if p.get("note"):
                L += _text(1, "NOTE", p["note"])
            for k in p.get("sources", []):
                if k in sources:
                    used.add(k)
                    L.append(f"1 SOUR @{sid[k]}@")
        for f in famc_of.get(p["id"], []):
            L.append(f"1 FAMC @{f}@")
        for f in fams_of.get(p["id"], []):
            L.append(f"1 FAMS @{f}@")
    for f in families:
        L.append(f"0 @{f['id']}@ FAM")
        if f.get("husb"):
            L.append(f"1 HUSB @{f['husb']}@")
        if f.get("wife"):
            L.append(f"1 WIFE @{f['wife']}@")
        for c in f.get("children", []):
            L.append(f"1 CHIL @{c}@")
        if f.get("marr") and not f.get("living"):
            L += _event("MARR", *f["marr"], False)
    for k in sorted(used):
        s = sources[k]
        L.append(f"0 @{sid[k]}@ SOUR")
        L += _text(1, "TITL", s["title"])
        if s.get("archive"):
            L += _text(1, "PUBL", s["archive"])
        if s.get("text"):
            L += _text(1, "TEXT", s["text"])
        if s.get("url"):
            L += _text(1, "NOTE", s["url"])
    L.append("0 TRLR")
    return "\n".join(L) + "\n"


def collect(people, families, relatives, vr, records, is_living, today_year):
    """Ze site.json dat (people, families) a stránek příbuzných poskládá vstup pro build()."""
    out, fams = [], []
    id_of = {}
    for slug, p in sorted(people.items(), key=lambda x: x[1]["k"]):
        id_of[slug] = f"I{p['k']}"
        living = is_living(dict(f=p["facts"], y=p["y"], note=p["note"]), today_year)
        spouse = people.get(p.get("spouse") or "", {}).get("name", "")
        b = next((split_fact(f) for f in p["facts"] if f.startswith("*")), ("", ""))
        d = next((split_fact(f) for f in p["facts"] if f.startswith("†")), ("", ""))
        if living and not b[0]:
            b = (p["y"], "")
        other = [f for f in p["facts"] if not f.startswith(("*", "†", "×"))]
        note = "\n".join(x for x in [p.get("status") and "Stav: " + p["status"], "\n".join(other), p.get("note", "")] if x)
        out.append(dict(id=id_of[slug], name=p["name"], male=p["sex"] == "M", birth=list(b), death=list(d), living=living,
                        note=note, sources=p["records"], fs=p.get("fs")))
        p["_marr"] = next((split_fact(f, spouse) for f in p["facts"] if f.startswith("×") and (not spouse or spouse in f)), None)
    for fid, f in families.items():
        h, w = id_of.get(f.get("father")), id_of.get(f.get("mother"))
        marr = (people.get(f.get("father") or "", {}).get("_marr") or people.get(f.get("mother") or "", {}).get("_marr"))
        fams.append(dict(id="F" + str(len(fams) + 1), husb=h, wife=w, children=[id_of[c] for c in f["children"] if c in id_of],
                         marr=list(marr) if marr else None,
                         living=any(x["living"] for x in out if x["id"] in (h, w))))
    for p in people.values():
        p.pop("_marr", None)
    # příbuzní se stránkou: k rodině svých rodičů (rodič z linie nebo jiný příbuzný se stránkou)
    P = vr["people"] if vr else {}
    by_vr = {r["id"]: f"R{n}" for n, r in enumerate(relatives.values(), 1)}
    slug_by_k = {p["k"]: s for s, p in people.items()}
    for r in relatives.values():
        out.append(dict(id=by_vr[r["id"]], name=r["name"], male=r["male"], birth=r["birth"], death=r["death"], living=False,
                        note="\n".join(x for x in [r.get("rel") and "Vztah: " + r["rel"], *(s["name"] + ": " + s["text"] for s in r["sources"])] if x),
                        sources=r["records"], fs=r.get("fs")))

    def gid(x):
        q = P.get(x, {})
        if q.get("k") and q["k"] in slug_by_k:
            return id_of[slug_by_k[q["k"]]]
        return by_vr.get(x)
    for r in relatives.values():
        pars = [gid(x) for x in P[r["id"]].get("parents", [])]
        pars = [x for x in pars if x]
        if not pars:
            continue
        male = {x["id"]: x["male"] for x in out}
        h = next((x for x in pars if male.get(x)), None)
        w = next((x for x in pars if not male.get(x)), None)
        fam = next((f for f in fams if f["husb"] == h and f["wife"] == w), None)
        if not fam:
            fam = dict(id="F" + str(len(fams) + 1), husb=h, wife=w, children=[], marr=None, living=False)
            fams.append(fam)
        fam["children"].append(by_vr[r["id"]])
    srcs = {r["key"]: dict(title=f"{r['title']} ({r['date']})", archive=" – ".join(x for x in (r.get("archive"), r.get("volume"), r.get("scan") and f"snímek {r['scan']}") if x),
                           text=r.get("cs", ""), url=r.get("url", "")) for r in records}
    return out, fams, srcs
