"""Načítání širšího rodinného stromu z GEDCOMu a místních doplňků.

Konfigurace v data/web.json → "velka_rodina": {"ged": "...", "koren": "@I1@"}.

Co dělá:
- Kekulého čísla přiřadí podle rodičů ve stromu od kořene; u přímých předků z data/osoby.py vezme jméno, roky,
  stav a odkaz na stránku osoby (doklady z matrik mají přednost před stromem).
- Předky, kteří jsou v osoby.py „ODPOJENO“ (nebo v seznamu "vyradit_k"), i s jejich předky vyřadí; lidi, kteří pak
  nejsou s kořenem spojení, na web nedá.
- Duplicity (stejné křestní jméno, příjmení a celé datum narození) sloučí do jedné osoby; dvojníky s neúplným
  datem lze sloučit ručně (data/web.json → velka_rodina.sloucit: [["@Iponechat@", "@Isloučit@"], ...]).
- Příbuzné mimo přímou linii, ověřené zápisem v matrice, označí jako doložené (velka_rodina.overeno: ["@I…@", ...]).
- Žijícím (bez úmrtí a narozeným v posledních 100 letech, nebo bez dat vedle žijících) nechá jen jméno a rok narození.
- Každé osobě spočítá vztah ke kořeni („bratranec“, „sestra dědečka“, „příbuzná přes sňatek“).
"""
import datetime, json, os, re, sys, unicodedata
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # s -I není složka skriptu v sys.path
import gedcom_export

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
EVENTS = ("BIRT", "CHR", "DEAT", "BURI", "MARR", "RESI")   # RESI: první pobyt (vystěhovalci na mapě)


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]", "", s)


def parse(path):
    recs, cur, sub = {}, None, None
    for line in open(path, encoding="utf-8-sig", errors="replace"):
        m = re.match(r"^(\d+)\s+(@[^@]+@\s+)?(\S+)\s?(.*)$", line.rstrip("\r\n"))
        if not m:
            continue
        lvl, xref, tag, val = int(m.group(1)), (m.group(2) or "").strip(), m.group(3), m.group(4).strip()
        if lvl == 0:
            cur = dict(tag=tag, id=xref, name="", givn="", surn="", sex="", ev={}, fams=[], famc=[], husb=[], wife=[], chil=[])
            if xref:
                recs[xref] = cur
            sub = None
            continue
        if cur is None:
            continue
        if lvl == 1:
            sub = tag
            if tag == "NAME" and not cur["name"]:
                cur["name"] = re.sub(r"\s+", " ", val.replace("/", " ")).strip()
                sm = re.search(r"/([^/]*)/", val)
                cur["surn"] = sm.group(1).strip() if sm else ""
                cur["givn"] = val.split("/")[0].strip()
            elif tag == "SEX":
                cur["sex"] = val
            elif tag in ("FAMS", "FAMC", "HUSB", "WIFE", "CHIL"):
                cur[tag.lower()].append(val)
            elif tag == "_ZAZNAM":                         # klíč zápisu z data/zaznamy.json (doplňky z matrik)
                cur.setdefault("zaz", []).append(val)
            elif tag in EVENTS:
                cur["ev"].setdefault(tag, ["", ""])
        elif lvl == 2 and sub in EVENTS and tag in ("DATE", "PLAC"):
            e = cur["ev"][sub]
            i = 0 if tag == "DATE" else 1
            e[i] = e[i] or val
    return recs


def cz_date(d):
    """GEDCOM datum → česky ('27 JUN 1908' → '27. 6. 1908', 'ABT 1776' → 'asi 1776')."""
    d = (d or "").strip()
    if not d:
        return ""
    pre = ""
    for k, v in (("ABT", "asi "), ("EST", "asi "), ("CAL", "asi "), ("BEF", "před "), ("AFT", "po ")):
        if d.startswith(k + " "):
            pre, d = v, d[len(k) + 1:]
    m = re.match(r"^(\d{1,2}) ([A-Z]{3}) (\d{4})$", d)
    if m and m.group(2) in MONTHS:
        return f"{pre}{int(m.group(1))}. {MONTHS[m.group(2)]}. {m.group(3)}"
    m = re.match(r"^([A-Z]{3}) (\d{4})$", d)
    if m and m.group(1) in MONTHS:
        return f"{pre}{MONTHS[m.group(1)]}/{m.group(2)}"
    m = re.search(r"\d{4}", d)
    return pre + (m.group(0) if m else d)


def year_of(d):
    m = re.search(r"\d{4}", d or "")
    return int(m.group(0)) if m else None


def exact_year(d):
    """Rok pro kontroly chronologie: rozmezí a meze (BEF, AFT, BET … AND …, FROM, TO) přesný rok nejsou → None."""
    if re.match(r"\s*(BEF|AFT|BET|FROM|TO)\b", d or ""):
        return None
    return year_of(d)


def apply_corrections(recs, opravy):
    """Opravy chyb stromu (data/web.json → velka_rodina.opravy), hlavní soubor stromu se nemění. Každá má `proc`:
      {"dite": "@I…@", "z": "@F…@", "do": "@F…@"}   dítě patří do jiné rodiny ("do" vynechat = jen odpojit)
      {"rodina": "@F…@", "odebrat": "@I…@"}          manžel či manželka do rodiny nepatří
      {"osoba": "@I…@", "udalost": "DEAT", "datum": ""}   jiné datum události, prázdné = událost pryč
      {"osoba": "@I…@", "udalost": "BIRT", "misto": "Rapšach 46"}   jiné místo (i spolu s "datum"), prázdné = místo pryč
    Vrací hlášky k opravám, které se nedají použít (neexistující id, dítě v rodině není, prázdné datum s místem)."""
    pozor = []
    for o in opravy:
        ids = [o.get(k) for k in ("dite", "z", "do", "rodina", "odebrat", "osoba") if o.get(k)]
        if missing := [x for x in ids if x not in recs]:
            pozor.append(f"oprava {o} odkazuje na {', '.join(missing)}, které ve stromu nejsou")
            continue
        if "dite" in o:
            c, z, do = recs[o["dite"]], recs[o["z"]], o.get("do")
            if o["dite"] not in z["chil"] and o["z"] not in c["famc"]:
                pozor.append(f"oprava {o}: {o['dite']} v rodině {o['z']} není")
                continue
            z["chil"] = [x for x in z["chil"] if x != o["dite"]]
            c["famc"] = [x for x in c["famc"] if x != o["z"]]
            if do:
                recs[do]["chil"] = list(dict.fromkeys(recs[do]["chil"] + [o["dite"]]))
                c["famc"] = list(dict.fromkeys(c["famc"] + [do]))
        elif "rodina" in o:
            f, x = recs[o["rodina"]], o["odebrat"]
            f["husb"], f["wife"] = [p for p in f["husb"] if p != x], [p for p in f["wife"] if p != x]
            recs[x]["fams"] = [g for g in recs[x]["fams"] if g != o["rodina"]]
        elif "osoba" in o:
            ev, u = recs[o["osoba"]]["ev"], o["udalost"]
            if "datum" not in o and "misto" not in o:
                pozor.append(f"oprava {o}: chybí datum i místo")
            elif o.get("datum") == "" and "misto" in o:
                pozor.append(f"oprava {o}: prázdné datum odebírá celou událost {u}, místo k ní nejde opravit")
            elif o.get("datum") == "":
                ev.pop(u, None)
            else:
                e = ev.setdefault(u, ["", ""])
                if "datum" in o:
                    e[0] = o["datum"]
                if "misto" in o:
                    e[1] = o["misto"]
    return pozor


def place_short(p):
    return (p or "").split(",")[0].strip()


def load_osoby():
    ns = {}
    exec(open(os.path.join(ROOT, "data", "osoby.py"), encoding="utf-8").read(), ns)
    return ns.get("P", {}), ns.get("SAME", {})


def site_slugs():
    """Slugy osob z web/src/data/site.json (podle Kekulého čísla), pokud už web data má."""
    path = os.path.join(ROOT, "web", "src", "data", "site.json")
    if not os.path.exists(path):
        return {}
    people = json.load(open(path, encoding="utf-8")).get("people", {})
    return {p["k"]: slug for slug, p in people.items() if "k" in p}


# ---- vztahy -------------------------------------------------------------------------------------------------

def pra(n):
    return "pra" * n


def blood_label(a, b, male):
    """a = generací od kořene nahoru ke společnému předkovi, b = generací od něj dolů k osobě.
    Nejvýš tři „pra“; dál popisně (společného předka ukáže web zvlášť)."""
    if a == 0 and b == 0:
        return "výchozí osoba rodokmenu"
    if a == 0:
        if b <= 5:
            base = ("syn", "dcera") if b == 1 else ("vnuk", "vnučka")
            return pra(max(0, b - 2)) + base[0 if male else 1]
        return f"{'potomek' if male else 'potomkyně'} v {b}. generaci"
    if b == 0:
        if a == 1:
            return "otec" if male else "matka"
        if a <= 5:
            return pra(a - 2) + ("dědeček" if male else "babička")
        return f"{'předek' if male else 'předkyně'} v {a}. generaci"
    if a == 1 and b == 1:
        return "bratr" if male else "sestra"
    if a == 1:
        return pra(b - 2) + ("synovec" if male else "neteř") if b <= 4 else f"{'potomek' if male else 'potomkyně'} sourozence"
    if b == 1:
        if a <= 4:
            return pra(a - 2) + ("strýc" if male else "teta")
        return f"{'bratr' if male else 'sestra'} předka v {a - 1}. generaci"
    if a - b >= 3:
        return f"{'potomek' if male else 'potomkyně'} sourozence předka v {a - 1}. generaci"
    if b - a >= 3:
        return f"{'vzdálený příbuzný' if male else 'vzdálená příbuzná'}, o {b - a} generace níž"
    word = "bratranec" if male else "sestřenice"
    k = min(a, b) - 1
    label = word if k == 1 else f"{word} z {k}. kolene"
    if a != b:
        d = abs(a - b)
        label += f", o {d} {'generaci' if d == 1 else 'generace'} {'výš' if a > b else 'níž'}"
    return label


def load_tree(cfg, ged=None, side=None):
    """Hlavní GEDCOM (data/web.json → velka_rodina.ged) sloučený s doplňky z matrik a se sourozenci předků ze SIDE;
    vrací záznamy {id: záznam}. side=None: SIDE z data/osoby.py (jen bez `ged`), side=[]: bez SIDE."""
    ged_arg = ged
    ged = ged or os.path.join(ROOT, cfg.get("ged", ""))
    if not os.path.isfile(ged):
        sys.exit(f"Strom nenalezen: {ged} (nastavte data/web.json → velka_rodina.ged)")
    recs = parse(ged)
    # doplňky z matrik (data/web.json → velka_rodina.doplnky: GEDCOM s osobami @I9xxxxx@ a rodinami @F9xxxxx@, které
    # odkazují i na osoby hlavního stromu); vazby z FAM se dopíšou i k osobám hlavního stromu (FAMS/FAMC)
    dopl = cfg.get("doplnky")
    if dopl and os.path.isfile(os.path.join(ROOT, dopl)):
        extra = parse(os.path.join(ROOT, dopl))
        for x, r in list(extra.items()):               # rodina/osoba hlavního stromu v doplňcích = jen přidané vazby
            if x in recs and recs[x]["tag"] == r["tag"]:
                for t in ("fams", "famc", "husb", "wife", "chil"):
                    recs[x][t] = list(dict.fromkeys(recs[x][t] + r[t]))
                recs[x].setdefault("zaz", []).extend(r.get("zaz", []))
                extra[x] = recs[x]
        recs.update(extra)
        for x, r in extra.items():
            if r["tag"] == "FAM":
                for t, members in (("fams", r["husb"] + r["wife"]), ("famc", r["chil"])):
                    for i in members:
                        if i in recs and x not in recs[i][t]:
                            recs[i][t].append(x)
    # sourozenci a děti předků zapsaní jen v osoby.py SIDE → osoby v rodině předka (side_strom.py, jen v paměti)
    if side is None and ged_arg is None:            # jen skutečný strom; testovací strom (ged=…) bez SIDE projektu
        ns = {}
        exec(open(os.path.join(ROOT, "data", "osoby.py"), encoding="utf-8").read(), ns)
        side = ns.get("SIDE", [])
    if side:
        import side_strom                                  # tady, ne nahoře: side_strom importuje tento modul
        side_strom.pridej(recs, side, cfg.get("koren", "@I1@"))
    for msg in apply_corrections(recs, cfg.get("opravy", [])):   # chyby stromu doložené jinde (web.json)
        print("POZOR:", msg)
    return recs


def merge_duplicates(indi, fams, cfg, report=None):
    """Sloučí zdvojené osoby (stejné jméno, příjmení a celé datum narození; ruční velka_rodina.sloucit) a zdvojené
    rodiny (stejní manželé), pak každé osobě nechá jednu rodinu původu (one_family_of_origin, rozhodnutí do `report`).
    Mění indi a fams na místě, vrací alias {zrušené id: ponechané id}."""
    # 1) duplicity: stejné jméno, příjmení a celé datum narození → jedna osoba
    alias, groups = {}, {}
    for i, r in indi.items():
        d = r["ev"].get("BIRT", ["", ""])[0]
        if re.match(r"^\d{1,2} [A-Z]{3} \d{4}$", d):
            key = (norm(r["givn"]), norm(r["surn"]).lstrip("w"), d)
            groups.setdefault(key, []).append(i)
    for ids in groups.values():
        if len(ids) > 1:
            keep = sorted(ids, key=lambda x: int(re.sub(r"\D", "", x) or 0))[0]
            for x in ids:
                if x != keep:
                    alias[x] = keep
    # ruční sloučení dvojníků s neúplným datem (data/web.json → velka_rodina.sloucit: [["@I1@", "@I2@"], ...]; druhý → první)
    for keep, x in cfg.get("sloucit", []):
        if keep in indi and x in indi and x != keep:
            alias[x] = alias.get(keep, keep)
    A = lambda x: alias.get(x, x)
    for f in fams.values():
        f["husb"], f["wife"], f["chil"] = [A(x) for x in f["husb"]], [A(x) for x in f["wife"]], list(dict.fromkeys(A(x) for x in f["chil"]))
    for x, keep in alias.items():
        k = indi[keep]
        for t in ("fams", "famc"):
            k[t] = list(dict.fromkeys(k[t] + indi[x][t]))
        for e, v in indi[x]["ev"].items():
            k["ev"].setdefault(e, v)
    for x in alias:
        del indi[x]
    # rodina, kde jsou oba manželé tytéž osoby (sloučené duplicitní rodiny) → spojit
    by_pair = {}
    for fid, f in list(fams.items()):
        key = (tuple(f["husb"]), tuple(f["wife"]))
        if key in by_pair and key != ((), ()):
            g = fams[by_pair[key]]
            g["chil"] = list(dict.fromkeys(g["chil"] + f["chil"]))
            for e, v in f["ev"].items():
                g["ev"].setdefault(e, v)
            del fams[fid]
            for p in indi.values():
                p["fams"] = list(dict.fromkeys(by_pair[key] if x == fid else x for x in p["fams"]))
                p["famc"] = list(dict.fromkeys(by_pair[key] if x == fid else x for x in p["famc"]))
        else:
            by_pair[key] = fid

    one_family_of_origin(indi, fams, report)
    return alias


def _parents(f):
    return f["husb"][:1] + f["wife"][:1]


def _plausible(indi, fam, child):
    """Mohli být rodiče rodiny `fam` rodiči dítěte podle roků narození a úmrtí? (Neznámý rok = možné.)"""
    ev = indi[child]["ev"]
    yc = exact_year(ev.get("BIRT", ["", ""])[0] or ev.get("CHR", ["", ""])[0])
    if not yc:
        return True
    for p in _parents(fam):
        if p not in indi:
            continue
        e = indi[p]["ev"]
        yb = exact_year(e.get("BIRT", ["", ""])[0] or e.get("CHR", ["", ""])[0])
        yd = exact_year(e.get("DEAT", ["", ""])[0] or e.get("BURI", ["", ""])[0])
        mother = p in fam["wife"][:1]
        if yb and not (14 <= yc - yb <= (52 if mother else 80)):
            return False
        if yd and yc > yd + (0 if mother else 1):      # otec smí zemřít před narozením (do roka)
            return False
    return True


def one_family_of_origin(indi, fams, report=None):
    """Osoba ve více rodinách původu (dvojník u obou manželek otce, rodina z doplňků vedle rodiny ze stromu) by na webu
    měla tři a více rodičů. Rodiny původu bere z FAMC i z CHIL. Zahodí chronologicky nemožnou rodinu, pak rodinu,
    jejíž rodiče jsou podmnožinou jiné, pak rodinu s rodičem bez jména. Když zbudou dvě poloviny téhož páru (jen otec,
    jen matka), nechá obě. Jinak ponechá první (rodina ponechané osoby) a hlásí „nerozhodnuto“.
    Rozhodnutí přidá do `report` (osoba, ponecháno, zahozeno, důvod)."""
    in_chil = {}
    for fid, f in fams.items():
        for c in f["chil"]:
            in_chil.setdefault(c, []).append(fid)
    for i, r in indi.items():
        famc = [f for f in dict.fromkeys(r["famc"] + in_chil.get(i, [])) if f in fams]
        if len(famc) < 2:
            continue
        keep, dropped, reasons = list(famc), [], []
        sets = {f: set(_parents(fams[f])) for f in famc}

        def subset_free(f):        # rodiče nejsou podmnožinou jiné ponechané rodiny (u shodných ustoupí pozdější)
            return not any(g != f and (sets[f] < sets[g] or (sets[f] == sets[g] and keep.index(g) < keep.index(f)))
                           for g in keep)
        for why, ok in (("chronologie", lambda f: _plausible(indi, fams[f], i)),
                        ("podmnožina", subset_free),
                        ("bez jména", lambda f: all(indi.get(p, {}).get("name") for p in _parents(fams[f])))):
            good = [f for f in keep if ok(f)]
            if good and len(good) < len(keep):
                dropped += [f for f in keep if f not in good]
                keep = good
                reasons.append(why)
        halves = (len({h for f in keep for h in fams[f]["husb"][:1]}) <= 1
                  and len({w for f in keep for w in fams[f]["wife"][:1]}) <= 1)
        if len(keep) > 1 and not halves:
            dropped += keep[1:]
            keep = keep[:1]
            reasons.append("nerozhodnuto")
        if not dropped:
            continue
        reason = next((x for x in reversed(reasons) if x != "podmnožina"), "podmnožina")
        r["famc"] = keep
        for f in dropped:
            fams[f]["chil"] = [c for c in fams[f]["chil"] if c != i]
        if report is not None and reason != "podmnožina":
            report.append(dict(osoba=i, ponechano=keep[0], zahozeno=dropped, duvod=reason))


def build(cfg, ged=None, side=None, stats=None):
    """Velká rodina jako data {root, people} (obsah web/public/velka-rodina.json). `stats` (dict) dostane počty
    a podklady pro souhrn kontroly grafu; zápis a výpis dělá main()."""
    fs_path = os.path.join(ROOT, "data", "familysearch.json")
    fsmap = json.load(open(fs_path, encoding="utf-8")) if os.path.exists(fs_path) else {}
    root_id = cfg.get("koren", "@I1@")
    vyradit_k = set(cfg.get("vyradit_k", []))
    recs = load_tree(cfg, ged, side)
    indi = {i: r for i, r in recs.items() if r["tag"] == "INDI"}
    fams = {i: r for i, r in recs.items() if r["tag"] == "FAM"}
    P, SAME = load_osoby()
    slugs = site_slugs()

    report = []
    alias = merge_duplicates(indi, fams, cfg, report=report)
    A = lambda x: alias.get(x, x)
    # příbuzní mimo přímou linii, ověření zápisem v matrice (velka_rodina.overeno: ["@I…@", ...]) → stav doc
    overeno = {A(x) for x in cfg.get("overeno", [])}
    def parents_of(i):
        for f in indi[i]["famc"]:
            if f in fams:
                return fams[f]
        return None

    # 2) Kekulé podle stromu
    kek, q = {}, deque([(root_id, 1)])
    while q:
        i, k = q.popleft()
        if i in kek or i not in indi:
            continue
        kek[i] = k
        fam = parents_of(i)
        if fam:
            for x, kk in ((fam["husb"], 2 * k), (fam["wife"], 2 * k + 1)):
                if x:
                    q.append((x[0], kk))
    by_k = {k: i for i, k in kek.items()}

    # 3) vyřazení odpojených předků (i s jejich předky) – osoba zůstane, jen bez vazby na rodiče
    for k, p in P.items():
        if p.get("st") == "unk" and str(p.get("note", "")).startswith("ODPOJENO"):
            vyradit_k.add(k)
    banned = set()
    for k in vyradit_k:
        stack = [k]
        while stack:
            kk = stack.pop()
            if kk in by_k:
                banned.add(by_k[kk])
                stack += [2 * kk, 2 * kk + 1]

    # 4) graf vazeb (rodiče, manželé, děti) bez vyřazených
    def ok(x):
        return x in indi and x not in banned

    people = {}
    for i in indi:
        if not ok(i):
            continue
        people[i] = dict(parents=[], spouses=[], children=[])
    for fid, f in fams.items():
        hs, ws = [x for x in f["husb"] if ok(x)], [x for x in f["wife"] if ok(x)]
        kids = [c for c in f["chil"] if ok(c)]
        par = hs[:1] + ws[:1]
        # chybný sňatek předka ze stromu (data/web.json → velka_rodina.vyradit_snatky: [[k, "část jména manžela"]])
        for k, jm in cfg.get("vyradit_snatky", []):
            if k in by_k and by_k[k] in par and any(jm in indi[x]["name"] for x in par if x != by_k[k]):
                par = [x for x in par if x == by_k[k]] if not kids else [x for x in par if x != by_k[k]]
        marr = cz_date(f["ev"].get("MARR", ["", ""])[0])
        mplace = place_short(f["ev"].get("MARR", ["", ""])[1])
        if len(par) == 2:
            a, b = par
            people[a]["spouses"].append(dict(id=b, marr=marr, place=mplace))
            people[b]["spouses"].append(dict(id=a, marr=marr, place=mplace))
        for c in kids:
            for x in par:
                if c not in people[x]["children"]:
                    people[x]["children"].append(c)
                if x not in people[c]["parents"]:
                    people[c]["parents"].append(x)

    # 5) jen lidé spojení s kořenem
    seen, q = {root_id}, deque([root_id])
    while q:
        i = q.popleft()
        e = people[i]
        for x in e["parents"] + e["children"] + [s["id"] for s in e["spouses"]]:
            if x not in seen:
                seen.add(x)
                q.append(x)
    people = {i: e for i, e in people.items() if i in seen}

    # 6) vztah ke kořeni: pokrevní (nejbližší společný předek), jinak přes sňatek
    up = {root_id: 0}
    q = deque([root_id])
    while q:
        i = q.popleft()
        for p in people[i]["parents"]:
            if p not in up:
                up[p] = up[i] + 1
                q.append(p)
    blood = {}
    for anc, a in sorted(up.items(), key=lambda t: t[1]):
        q = deque([(anc, 0)])
        while q:
            i, b = q.popleft()
            if i not in blood or a + b < sum(blood[i][:2]):
                blood[i] = (a, b, anc)
                for c in people[i]["children"]:
                    q.append((c, b + 1))

    this_year = datetime.date.today().year
    out_people = {}
    ids = {i: f"p{n}" for n, i in enumerate(sorted(people, key=lambda x: int(re.sub(r"\D", "", x) or 0)), 1)}

    def male(i):
        k = kek.get(i)
        if k and k > 1:
            return k % 2 == 0
        return indi[i]["sex"] != "F"

    for i, e in people.items():
        r = indi[i]
        k = kek.get(i) if i not in banned else None
        osoba = P.get(SAME.get(k, k)) if k else None
        if osoba and osoba.get("n", "").startswith(("otec neuveden", "matka neuvedena")):
            osoba = None
        by = year_of(r["ev"].get("BIRT", ["", ""])[0] or r["ev"].get("CHR", ["", ""])[0])
        birth = [cz_date(r["ev"].get("BIRT", ["", ""])[0]), place_short(r["ev"].get("BIRT", ["", ""])[1])]
        death = [cz_date(r["ev"].get("DEAT", ["", ""])[0]), place_short(r["ev"].get("DEAT", ["", ""])[1])]
        if osoba:   # ověřené údaje z osoby.py mají přednost před stromem
            for f in osoba.get("f", []):
                m = re.match(r"^([*†])\s*(.+)$", f)
                if m:
                    if m.group(1) == "*":
                        birth = [m.group(2), ""]
                    else:
                        death = [m.group(2), ""]
            by = by or year_of(birth[0])
        dead = "DEAT" in r["ev"] or "BURI" in r["ev"]
        out_people[ids[i]] = dict(
            name=(osoba or {}).get("n") or r["name"] or "?",
            male=male(i), by=by, dead=dead, k=k if osoba else None,
            slug=slugs.get(SAME.get(k, k)) if osoba else None,
            st=(osoba or {}).get("st", "doc" if i in overeno else "strom"),
            years=(osoba or {}).get("y", ""),
            birth=birth, death=death,
            resi=[cz_date(r["ev"].get("RESI", ["", ""])[0]), place_short(r["ev"].get("RESI", ["", ""])[1])],
            parents=[ids[x] for x in e["parents"]],
            spouses=[dict(id=ids[s["id"]], marr=s["marr"], place=s["place"]) for s in e["spouses"]],
            children=[ids[x] for x in e["children"]],
            records=r.get("zaz", []),
            # ID ve stromu FamilySearch: data/familysearch.json (podle čísla předka nebo id ve stromu), pak poznámka v osoby.py
            fs=gedcom_export.fs_id(fsmap, k=k if osoba else None, gid=i, note=(osoba or {}).get("note"))
            or next((fsmap.get("ged", {})[x] for x, y in alias.items() if y == i and x in fsmap.get("ged", {})), None),
            _gid=i,
        )

    # žijící: bez úmrtí a narozen v posledních 100 letech; bez roku → podle nejbližších příbuzných
    def living(p):
        if p["dead"] or p["death"][0]:
            return False
        if p["by"]:
            return p["by"] > this_year - 100
        near = [out_people[x]["by"] for x in p["parents"] + p["children"] + [s["id"] for s in p["spouses"]] if out_people[x]["by"]]
        return not near or max(near) > this_year - 110
    for pid, p in out_people.items():
        p["living"] = living(p)
    # osoba bez dat, jejíž rodič žije, také žije (děti žijících)
    for _ in range(3):
        for p in out_people.values():
            if not p["living"] and not p["by"] and not p["dead"] and any(out_people[x]["living"] for x in p["parents"]):
                p["living"] = True

    gid2pid = {p["_gid"]: pid for pid, p in out_people.items()}
    pid2gid = {pid: g for g, pid in gid2pid.items()}
    for pid, p in out_people.items():
        i = pid2gid[pid]
        if i in blood:
            a, b, anc = blood[i]
            p["rel"] = blood_label(a, b, p["male"])
            p["blood"] = True
            if a >= 1 and b >= 1:
                p["via"] = gid2pid[anc]
        else:
            # přes sňatek: manžel/ka pokrevního příbuzného, nebo příbuzný takového manžela
            rel = ""
            for s in p["spouses"]:
                sp = out_people[s["id"]]
                if pid2gid[s["id"]] in blood:
                    rel = ("manžel" if p["male"] else "manželka") + ": " + sp["name"]
                    break
            p["rel"] = rel or ("příbuzný přes sňatek" if p["male"] else "příbuzná přes sňatek")
            p["blood"] = False
        if p["living"]:
            p["birth"] = ["", ""]
            p["death"] = ["", ""]
            p["resi"] = ["", ""]
            p["spouses"] =[dict(id=s["id"], marr="", place="") for s in p["spouses"]]
            p["years"] = f"* {p['by']}" if p["by"] else ""
        elif not p["years"]:
            dy = year_of(p["death"][0])
            p["years"] = f"{p['by'] or '?'}–{dy}" if dy else (f"* {p['by']}" if p["by"] else ("† ?" if p["dead"] else ""))
            if p["dead"] and p["by"] and not dy:
                p["years"] = f"{p['by']}–?"

    for p in out_people.values():
        p["gid"] = p.pop("_gid")                           # id ve stromu (klíč data/familysearch.json → ged)
        del p["dead"]
        if p["living"]:
            p["fs"] = None                                 # žijící: jen jméno a rok, bez odkazu ven
    if stats is not None:
        stats.update(alias=len(alias), banned=len(banned), outside=len(indi) - len(banned) - len(out_people),
                     indi=indi, fams=fams, report=report, P=P, SAME=SAME)
    return dict(root=gid2pid[root_id], people=out_people)
