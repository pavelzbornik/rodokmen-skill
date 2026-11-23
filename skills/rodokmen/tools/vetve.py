# -*- coding: utf-8 -*-
"""Větve rodů: rod (linie příjmení) může mít víc rodin téhož jména – boční linie sourozenců předků i rodiny bez
doloženého spojení. Větve se zadávají ručně v data/vetve.json:

  {"<slug rodu>": [{"slug", "nazev", "zakladatel": "@I…@", "vztah": "bocni|prob|none", "popis", "souvislost"?}]}

Strom větve = zakladatel a potomci se stejným příjmením (kmen jména, Novák = Nováková, Wotava = Otava);
dcery jsou v něm s manželem, jejich děti s jiným příjmením už ne. Žijící (bez úmrtí, narození v posledních
100 letech) jen jménem a rokem narození. Export (tools/export_web.py → attach) přidá lines[slug].branches
(první karta = přímá linie) a vrátí stránky větví pro /rod/<rod>/<větev>/. Rozšíření projektu, ve skillu není.
"""
import re, unicodedata

VZTAHY = {"bocni": "doložená boční větev", "prob": "pravděpodobně spřízněná", "none": "vztah nedoložen"}
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def stem(surname, variants=()):
    """Kmen příjmení pro porovnání: bez diakritiky, podoby ze skupin variant (data/web.json → varianty_prijmeni,
    Novákj = Novák) na první podobu, bez přídechu W (Wotava) a bez ženské či přídavné koncovky
    (Nováková = Novák, Horská = Horský, Wotava = Otava); Horec zůstane jiné jméno."""
    def base(x):
        x = re.sub(r"^w(?=o)", "", re.sub(r"[^a-z]", "", fold(x)))
        x = re.sub(r"ova$", "", x) if len(x) > 5 else x
        return re.sub(r"[ayi]$", "", x) if len(x) > 4 else x
    s = base(surname)
    for group in variants or ():                           # porovnává se už kmen, takže platí i ženské podoby
        if s in {base(v) for v in group}:
            return base(group[0])
    return s


def _year(d):
    m = re.search(r"\d{4}", d or "")
    return int(m.group(0)) if m else None


def cz_date(d):
    d = (d or "").strip()
    pre = ""
    for k, v in (("ABT", "asi "), ("EST", "asi "), ("CAL", "asi "), ("BEF", "před "), ("AFT", "po ")):
        if d.startswith(k + " "):
            pre, d = v, d[len(k) + 1:]
    m = re.match(r"^(\d{1,2}) ([A-Z]{3}) (\d{4})$", d)
    if m and m.group(2) in MONTHS:
        return f"{pre}{int(m.group(1))}. {MONTHS[m.group(2)]}. {m.group(3)}"
    y = _year(d)
    return f"{pre}{y}" if y else ""


def _event(r, main, alt):
    """[datum, místo] události: datum z hlavní (BIRT/DEAT), když ho má, jinak z náhradní (CHR/BURI); místo stejně."""
    a, b = r["ev"].get(main, ["", ""]), r["ev"].get(alt, ["", ""])
    return [a[0] or b[0], a[1] or b[1]]


def _years(r):
    b, d = _event(r, "BIRT", "CHR")[0], _event(r, "DEAT", "BURI")[0]
    pre = "asi " if re.match(r"^(ABT|EST|CAL)\b", b or "") else ""
    by, dy = _year(b), _year(d)
    dead = "DEAT" in r["ev"] or "BURI" in r["ev"]
    if by and dy:
        return f"{pre}{by}–{dy}"
    if by:
        return f"{pre}{by}–?" if dead else f"* {pre}{by}"
    if dy:
        return f"† {dy}"
    return ""


def _by(r):
    return _year(_event(r, "BIRT", "CHR")[0])


def living_map(recs, today_year):
    """Žijící podle pravidla Velké rodiny: bez úmrtí a narozen v posledních 100 letech; bez roku podle rodičů,
    dětí a manželů (nejbližší rok do 110 let, nebo žádný údaj = raději žijící); bez dat s žijícím rodičem žije."""
    indi = {i: r for i, r in recs.items() if r.get("tag") == "INDI"}

    def parents(i):
        return [p for f in indi[i].get("famc", []) for p in recs.get(f, {}).get("husb", []) + recs.get(f, {}).get("wife", []) if p in indi]

    def near(i):
        out = parents(i)
        for f in indi[i].get("fams", []):
            fr = recs.get(f, {})
            out += [p for p in fr.get("husb", []) + fr.get("wife", []) if p != i] + fr.get("chil", [])
        return [x for x in out if x in indi]

    def dead(r):
        return "DEAT" in r["ev"] or "BURI" in r["ev"]
    alive = {}
    for i, r in indi.items():
        if dead(r):
            alive[i] = False
        elif _by(r):
            alive[i] = _by(r) > today_year - 100
        else:
            ys = [_by(indi[x]) for x in near(i) if _by(indi[x])]
            alive[i] = not ys or max(ys) > today_year - 110
    for _ in range(3):
        for i, r in indi.items():
            if not alive[i] and not _by(r) and not dead(r) and any(alive.get(p) for p in parents(i)):
                alive[i] = True
    return alive


def _key(n):
    return (n["name"], n["years"], n["living"])


def _dedupe(children):
    """Sourozenci se stejným jménem, roky a stavem (žije/nežije) = dvojník ze stromu: sloučí se do prvního."""
    out, by_key = [], {}
    for c in children:
        k = _key(c)
        if k in by_key:
            _merge(by_key[k], c)
        else:
            by_key[k] = c
            out.append(c)
    return out


def _merge(a, b):
    """Sloučí uzel dvojníka b do a (děti, zápisy, manželé, data), aby se nic neztratilo; slučují se jen uzly se
    stejným stavem žijící/nežijící, takže žijící nedostane zápisy ani manžele."""
    a["records"] = list(dict.fromkeys(a["records"] + b["records"]))
    a["spouses"] += [s for s in b["spouses"] if s["name"] not in {x["name"] for x in a["spouses"]}]
    a["children"] = _dedupe(sorted(a["children"] + b["children"], key=lambda c: int((re.findall(r"\d{4}", c["years"]) or ["9999"])[0])))
    for k in ("birth", "death"):
        a[k] = [x or y for x, y in zip(a[k], b[k])]
    a["href"] = a["href"] or b["href"]
    a["ids"] = list(dict.fromkeys(a.get("ids", [a["id"]]) + b.get("ids", [b["id"]])))


def branch_tree(recs, founder, today_year, links=None, _seen=None, _alive=None, variants=()):
    """Strom potomků zakladatele se stejným kmenem příjmení. Uzel: {id, name, years, male, living, href,
    birth: [datum, místo], death, spouses: [{id, name, years, href}], records, children}. Žijící jen jménem a rokem,
    žijící manželé se neukazují; dvojníci mezi sourozenci (stejné jméno, roky a stav) se sloučí do jednoho uzlu."""
    links = links or {}
    seen = _seen if _seen is not None else set()
    alive = _alive if _alive is not None else living_map(recs, today_year)
    r = recs[founder]
    seen.add(founder)
    st = stem(r.get("surn") or r["name"].split()[-1], variants)
    by = _by(r)
    living = alive.get(founder, False)
    place = lambda x: (x or "").split(",")[0].strip()
    b_ev, d_ev = _event(r, "BIRT", "CHR"), _event(r, "DEAT", "BURI")
    node = dict(id=founder, name=r["name"], male=r.get("sex") != "F", living=living,
                years=(f"* {by}" if by else "") if living else _years(r), href=None if living else links.get(founder),
                birth=["", ""] if living else [cz_date(b_ev[0]), place(b_ev[1])],
                death=["", ""] if living else [cz_date(d_ev[0]), place(d_ev[1])],
                spouses=[], records=[] if living else list(dict.fromkeys(r.get("zaz", []))), children=[])
    kids = []
    for f in r.get("fams", []):
        fr = recs.get(f)
        if not fr:
            continue
        if not living:
            for s in fr["husb"] + fr["wife"]:
                if s != founder and s in recs and not alive.get(s) and s not in [x["id"] for x in node["spouses"]]:
                    sr = recs[s]
                    node["spouses"].append(dict(id=s, name=sr["name"], years=_years(sr), href=links.get(s)))
        for c in fr["chil"]:
            if c in recs and c not in seen and stem(recs[c].get("surn") or "", variants) == st:
                kids.append(c)
    order = sorted(dict.fromkeys(kids), key=lambda c: _by(recs[c]) or 9999)
    children = []
    for c in order:
        if c not in seen:
            children.append(branch_tree(recs, c, today_year, links, seen, alive, variants))
    node["children"] = _dedupe(children)
    return node


def walk(node, depth=1):
    yield node, depth
    for c in node["children"]:
        yield from walk(c, depth + 1)


def summary(tree):
    nodes = list(walk(tree))
    years = []
    for n, _ in nodes:
        years += [int(y) for y in re.findall(r"\d{4}", n["years"])]
    recs = {k for n, _ in nodes for k in n["records"]}
    return dict(people=len(nodes), gens=max(d for _, d in nodes), records=len(recs),
                **{"from": min(years) if years else None, "to": max(years) if years else None})


def check(data, line_slugs, recs):
    """Chyby v data/vetve.json (texty pro kontrola.py)."""
    err = []
    for rod, items in (data or {}).items():
        if rod not in line_slugs:
            err.append(f"vetve.json: rod „{rod}“ na webu není (slugy rodů: {', '.join(sorted(line_slugs))})")
            continue
        slugs = set()
        for b in items:
            s = b.get("slug", "")
            if not re.match(r"^[a-z0-9-]+$", s):
                err.append(f"vetve.json: {rod}: neplatný slug „{s}“")
            if s in slugs:
                err.append(f"vetve.json: {rod}: větev „{s}“ je tam dvakrát")
            slugs.add(s)
            if b.get("vztah") not in VZTAHY:
                err.append(f"vetve.json: {rod}/{s}: vztah „{b.get('vztah')}“ není {', '.join(VZTAHY)}")
            z = b.get("zakladatel")
            if not isinstance(z, str) or not re.match(r"^@[^@]+@$", z):
                err.append(f"vetve.json: {rod}/{s}: chybí zakladatel (id osoby ve stromu, např. @I900073@)")
            elif recs is not None and not (z in recs and recs[z]["tag"] == "INDI"):     # bez stromu se existence neověří
                err.append(f"vetve.json: {rod}/{s}: zakladatel {z} ve stromu není")
            if not b.get("nazev"):
                err.append(f"vetve.json: {rod}/{s}: chybí název")
    return err


def _parent_of(recs, i):
    for f in recs[i].get("famc", []):
        fr = recs.get(f)
        if fr:
            for p in fr["husb"] + fr["wife"]:
                if p in recs:
                    return p
    return None


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")


def auto_branches(recs, ancestors, existing, today_year, variants=(), min_people=2):
    """Boční větve sourozenců předků bez ručního zápisu: každý zemřelý sourozenec předka z `ancestors` (id ve stromu,
    předci s příjmením rodu), který má ve stromu potomka se stejným příjmením, dostane větev („Petr (* 1801)“,
    vztah bocni). Ruční větve z data/vetve.json (`existing`) mají přednost: kdo je v jejich stromu, novou větev
    nezakládá. Vrací seznam větví ve formátu vetve.json (navíc auto=True)."""
    alive = living_map(recs, today_year)
    covered = {a for a in ancestors if a in recs}
    for b in existing:
        if b.get("zakladatel") in recs:
            covered |= {n["id"] for n, _ in walk(branch_tree(recs, b["zakladatel"], today_year, _alive=alive,
                                                             variants=variants))}
    slugs = {b.get("slug") for b in existing}
    out = []
    for a in sorted((a for a in ancestors if a in recs), key=lambda a: _by(recs[a]) or 9999):
        st = stem(recs[a].get("surn") or recs[a]["name"].split()[-1], variants)
        sibs = [c for f in recs[a].get("famc", []) if f in recs for c in recs[f]["chil"]]
        for c in sorted(dict.fromkeys(sibs), key=lambda c: _by(recs[c]) or 9999):
            if c in covered or c not in recs or alive.get(c) or stem(recs[c].get("surn") or "", variants) != st:
                continue
            t = branch_tree(recs, c, today_year, _alive=alive, variants=variants)
            ids = {n["id"] for n, _ in walk(t)}
            if len(ids) < min_people or ids & covered:
                continue
            covered |= ids
            jmeno, by = (recs[c].get("givn") or recs[c]["name"]).split()[0], _by(recs[c])
            nazev = f"{jmeno} (* {by})" if by else jmeno
            slug, n = slugify(f"{jmeno}-{by or ''}"), 2
            while slug in slugs:
                slug, n = slugify(f"{jmeno}-{by or ''}-{n}"), n + 1
            slugs.add(slug)
            vztah = "Bratr" if recs[c].get("sex") != "F" else "Sestra"
            out.append(dict(slug=slug, nazev=nazev, zakladatel=c, vztah="bocni", auto=True,
                            popis=f"{vztah} předka {recs[a]['name']} a potomci se stejným příjmením."))
    return out


def person_pages(tree, recs, base, alive, links=None):
    """Stránky osob větve, které jinde stránku nemají (a nežijí): adresa <base><slug>/ se zapíše do uzlu (href) a
    vrátí se {slug: {name, years, birth, death, male, records, fullFamily: {parents, siblings, spouses, children}}}. Rodina se bere
    z rodin ve stromu (ne z vykresleného stromu), odkazy na nové stránky i na stránky předků a příbuzných (links)."""
    links = links or {}
    used, out = set(), {}
    for n, _ in walk(tree):
        if n["living"] or n["href"]:
            continue
        y = (re.findall(r"\d{4}", n["years"]) or [""])[0]
        s0 = slugify(f"{n['name']} {y}")
        s, k = s0, 2
        while s in used:
            s, k = f"{s0}-{k}", k + 1
        used.add(s)
        n["href"] = f"{base}{s}/"
        n["_slug"] = s
    href = dict(links)
    for n, _ in walk(tree):
        for i in n.get("ids", [n["id"]]):
            if n["href"]:
                href[i] = n["href"]

    def card(i):
        """Karta pro blok Celá rodina (FamilyCard.astro): žijící jen jméno a rok, bez odkazu."""
        r = recs[i]
        by = _by(r)
        if alive.get(i):
            return dict(id=i, name=r["name"], years=f"* {by}" if by else "", male=r.get("sex") != "F", url=None,
                        doc=False, infant=False, line=False, rel="", living=True)
        dy = _year(_event(r, "DEAT", "BURI")[0])
        return dict(id=i, name=r["name"], years=_years(r), male=r.get("sex") != "F", url=href.get(i), doc=bool(r.get("zaz")),
                    infant=bool(by and dy is not None and 0 <= dy - by <= 1), line=False, rel="", living=False)

    def cards(ids, skip_living=False):
        """Karty bez dvojníků (stejné jméno, roky a stav; odkaz z kteréhokoli), podle roku narození."""
        out = {}
        for i in sorted(dict.fromkeys(ids), key=lambda x: _by(recs[x]) or 9999):
            c = card(i)
            if skip_living and c["living"]:
                continue
            k = (c["name"], c["years"], c.pop("living"))
            if k in out:
                out[k]["url"] = out[k]["url"] or c["url"]
            else:
                out[k] = c
        return list(out.values())

    fams_of = lambda ids, key: [f for i in ids for f in recs[i].get(key, []) if f in recs]
    for n, _ in walk(tree):
        s = n.pop("_slug", None)
        if not s:
            continue
        ids = n.get("ids", [n["id"]])
        par = [p for f in fams_of(ids, "famc") for p in recs[f]["husb"] + recs[f]["wife"] if p in recs]
        sibs = [c for f in fams_of(par, "fams") if set(recs[f]["husb"] + recs[f]["wife"]) & set(par)
                for c in recs[f]["chil"] if c in recs and c not in ids]
        sps = [p for f in fams_of(ids, "fams") for p in recs[f]["husb"] + recs[f]["wife"] if p in recs and p not in ids]
        kids = [c for f in fams_of(ids, "fams") for c in recs[f]["chil"] if c in recs]
        parents = cards(par)
        parents.sort(key=lambda c: not c["male"])                     # otec první
        siblings = cards(sibs)
        if len(set(par)) == 2:                                        # nevlastní sourozenec: druhý rodič jako u Velké rodiny
            for c in siblings:
                other = [p for f in recs[c["id"]].get("famc", []) if f in recs
                         for p in recs[f]["husb"] + recs[f]["wife"] if p in recs and p not in par]
                if other and not alive.get(other[0]):
                    c["otherParent"], c["otherParentMale"] = recs[other[0]]["name"], recs[other[0]].get("sex") != "F"
        out[s] = dict(name=n["name"], years=n["years"], male=n["male"], birth=n["birth"], death=n["death"],
                      records=n["records"],
                      fullFamily=dict(parents=parents, siblings=siblings, spouses=cards(sps, skip_living=True), children=cards(kids)))
    return out


def attach(lines, people, data, recs, today_year, links=None, story_slugs=(), variants=(), ancestors=None):
    """Doplní lines[slug].branches (karty; první přímá linie) a vrátí stránky větví {"rod/větev": data}
    včetně stránek osob větve (persons). `ancestors` {rod: [id předků s příjmením rodu]} přidá automatické
    boční větve sourozenců předků (auto_branches) za ruční větve z data/vetve.json."""
    pages = {}
    alive = living_map(recs, today_year)
    for slug, l in lines.items():
        items = list((data or {}).get(slug, []))
        if ancestors and ancestors.get(slug):
            items += auto_branches(recs, ancestors[slug], items, today_year, variants)
        if not items:
            l["branches"] = []
            continue
        line_people = l.get("surnameLine") or l["people"]          # nositelé příjmení, aby čísla šla srovnat s větvemi
        ys = [int(y) for s in line_people for y in re.findall(r"\d{4}", people.get(s, {}).get("y", ""))]
        cards = [dict(slug=None, name="Tvoje linie", rel="linie", relText="tvoje linie", desc=l.get("desc", ""),
                      href=f"/rod/{slug}/#linie", people=len(line_people), gens=len(line_people) if l.get("surnameLine") else len(set(l["gens"].values())),
                      **{"from": min(ys) if ys else None, "to": None}, unlinked=False)]
        for b in items:
            if b.get("zakladatel") not in recs:
                continue
            tree = branch_tree(recs, b["zakladatel"], today_year, links, _alive=alive, variants=variants)
            persons = person_pages(tree, recs, f"/rod/{slug}/{b['slug']}/", alive, links)
            s = summary(tree)
            souv = b.get("souvislost")
            if not souv and b["vztah"] == "bocni":
                p = _parent_of(recs, b["zakladatel"])
                if p:
                    souv = (f"{'Otec' if recs[p].get('sex') != 'F' else 'Matka'} zakladatele větve, {recs[p]['name']}, "
                            f"je tv{'ůj předek' if recs[p].get('sex') != 'F' else 'á předkyně'}. Větev je tedy boční linií tvého rodu.")
            key = f"{slug}/{b['slug']}"
            card = dict(slug=b["slug"], name=b["nazev"], rel=b["vztah"], relText=VZTAHY[b["vztah"]], desc=b.get("popis", ""),
                        href=f"/rod/{slug}/{b['slug']}/", unlinked=b["vztah"] == "none", **s)
            cards.append(card)
            pages[key] = dict(card, line=slug, lineName=l["name"], color=l.get("color"), souvislost=souv or "",
                              tree=tree, persons=persons, story=f"/pribehy/{key}/" if key in story_slugs else None)
        l["branches"] = cards
    return pages


def branch_places(tree, mista, find_place):
    """Body pro mapu větve: narození a úmrtí s rokem a místem se souřadnicemi; formát jako lines[].map.points."""
    places = {n: e.get("re") for n, e in mista.items()}
    pts = []
    for n, _ in walk(tree):
        if n["living"]:
            continue
        for (d, pl), word in ((n["birth"], "narození"), (n["death"], "úmrtí")):
            y = _year(d)
            if not (y and pl):
                continue
            name, _ = find_place(pl, places, anywhere=False)
            if name and "lat" in mista[name] and "lon" in mista[name]:
                pts.append(dict(year=y, name=name, lat=mista[name]["lat"], lon=mista[name]["lon"], label=f"{n['name']}, {word}"))
    pts.sort(key=lambda x: x["year"])
    return [x for i, x in enumerate(pts) if i == 0 or x["name"] != pts[i - 1]["name"]]
