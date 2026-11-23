"""Společné výpočty pro nové pohledy na webu (výročí, časové osy, mapa v čase, přehled, kmotři).

Knihovna bez vstupu a výstupu: rozbor faktů z data/osoby.py („* 11. 3. 1864 Putim čp. 81“,
„nádeník ve Stožicích čp. 8 (1897)“) a pravidla, kdy je údaj doložen zápisem. Používá ji tools/export_web.py.
"""
import datetime, math, re, unicodedata

EVENT_RE = re.compile(r"^(\*|×|†|pokřtěna?)\s+")
# „11. 3. 1864“, „11. (?) 5. 1790“, „1. 1779“ (měsíc a rok), „1939“
DATE_RE = re.compile(r"(?:(\d{1,2})\.\s*(?:\(\?\)\s*)?)?(?:(\d{1,2})\.\s*(?:\(\?\)\s*)?)?(\d{4})\b")
SLASH_RE = re.compile(r"(\d{1,2})/(\d{4})\b")          # „12/1790“ (měsíc/rok)
HOUSE_RE = re.compile(r".*?čp\.\s*\d+")
FULL_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
OCC_RE =re.compile(r"^(.*\S)\s*\((asi )?(\d{4})\)$")         # „(1897)“, přibližně „(asi 1954)“
BURIAL_RE = re.compile(r"^pohřben[aoi]?\b")
KIND = {"*": "N", "×": "O", "†": "Z"}                    # značka události → druh zápisu


def parse_event(fact):
    """Událost z faktu: značka, den, měsíc, rok, místo a zbytek. Bez data (i „asi“, „před“) → None."""
    m = EVENT_RE.match(fact or "")
    if not m:
        return None
    sym = "pokřtěn" if m.group(1).startswith("pokřtěn") else m.group(1)
    after = fact[m.end():]
    d = SLASH_RE.match(after)
    if d:
        day, month, year = None, int(d.group(1)), int(d.group(2))
    else:
        d = DATE_RE.match(after)
        if not d:
            return None
        a, b = d.group(1), d.group(2)
        day, month = (int(a), int(b)) if b else (None, int(a) if a else None)
        year = int(d.group(3))
    rest = after[d.end():].strip()
    h = HOUSE_RE.match(rest)
    place = h.group(0) if h else (rest.split()[0] if rest else "")
    return dict(sym=sym, day=day, month=month, year=year, place=place, rest=rest)


def occupation_years(fact):
    """„nádeník ve Stožicích čp. 8 (1897)“ → („nádeník ve Stožicích čp. 8“, 1897), i „(asi 1954)“; jinak None."""
    if not fact or EVENT_RE.match(fact):
        return None
    m = OCC_RE.match(fact.strip())
    return (m.group(1), int(m.group(3))) if m else None


def _is_approx(fact):
    m = OCC_RE.match((fact or "").strip())
    return bool(m and m.group(2))


def is_uncertain(fact):
    """Údaj jen ze stromu nebo s otazníkem se do statistik a plných pruhů nepočítá."""
    return "(podle stromu)" in fact or "?" in fact


def is_living(p, today_year):
    """Žijící: poznámka „Žijící“, nebo bez † a narozen před méně než 100 lety."""
    if "Žijící" in p.get("note", ""):
        return True
    if any(f.startswith("†") for f in p.get("f", [])):
        return False
    ys = re.findall(r"\d{4}", p.get("y", "") or "")
    return bool(ys) and int(ys[0]) > today_year - 100


def _full_dates(text):
    """Všechna úplná data „d. m. rrrr“ v textu jako datetime.date (neplatná se přeskočí)."""
    out = []
    for d, m, y in FULL_DATE_RE.findall(text):
        try:
            out.append(datetime.date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return out


def _proves(e, date):
    """Sedí datum zápisu s událostí? Mají-li obě strany den i měsíc, nejvýš 31 dní rozdíl (křest/narození,
    pohřeb/úmrtí), jinak stačí rok. Datum zápisu s otazníkem nedokládá nic."""
    if "?" in date:
        return False
    rec_dates = _full_dates(date)
    if e["day"] and e["month"] and rec_dates:
        try:
            ev = datetime.date(e["year"], e["month"], e["day"])
        except ValueError:
            return False
        return any(abs((ev - d).days) <= 31 for d in rec_dates)
    return e["year"] in {int(y) for y in re.findall(r"\d{4}", date)}


def proven_events(p, recs):
    """Značka (*, ×, †) → první událost (parse_event), jejíž datum sedí s datem zápisu stejného druhu citovaného u osoby."""
    cited = [recs[k] for k in p.get("r", []) if k in recs]
    out = {}
    for f in p.get("f", []):
        e = parse_event(f)
        if not e or e["sym"] not in KIND or e["sym"] in out or is_uncertain(f):
            continue
        if any(r.get("kind") == KIND[e["sym"]] and _proves(e, r.get("date", "")) for r in cited):
            out[e["sym"]] = e
    return out


def proven_syms(p, recs):
    """Značky (*, ×, †), jejichž datum sedí s datem zápisu stejného druhu citovaného u osoby."""
    return set(proven_events(p, recs))


DATE_SPAN_RE = re.compile(r"^\S+\s+(?:\d{1,2}\.\s*(?:\(\?\)\s*)?){2}\d{4}(?:\s*\(\?\))?")   # datum i s „(?)“ za ním


def _find_place(text, places, anywhere=False):
    """Místo z data/mista.json (název → re) na začátku textu, s anywhere kdekoli (nejdřív stojící, při shodě
    delší název): (název, shoda), jinak (None, None)."""
    best = (None, None)
    for name, rx in sorted((places or {}).items(), key=lambda kv: -len(kv[0])):
        pat = re.compile(rf"(?:{re.escape(name)}{'|' + rx if rx else ''})\w*")
        m = pat.search(text) if anywhere else pat.match(text)
        if m and (best[1] is None or m.start() < best[1].start()):
            best = (name, m)
    return best


def _occ_place(text, places):
    """Místo povolání nebo bydliště kdekoli ve faktu; u stěhování „z X do Y“ cíl Y."""
    i = text.find(" do ")
    if i >= 0:
        name, _ = _find_place(text[i + 4:], places)
        if name:
            return name
    return _find_place(text, places, anywhere=True)[0]


def _anniv_place(e, places):
    """Místo z faktu, jen když začíná místem z data/mista.json (název nebo jeho re); jinak "". Bez toho by
    u sňatku bez místa bylo místem jméno nevěsty („× 9. 11. 1738 Rosina Buchtelová“ → „Rosina“).
    S čp. se místo bere, jak je zapsané; jinak celý známý název („Velká Bášť“), nebo shodné slovo."""
    rest = e["rest"]
    name, m = _find_place(rest, places)
    if not m:
        return ""
    return e["place"] if "čp." in e["place"] else name if rest.startswith(name) else m.group(0)


def placeholder(p):
    """Zástupce místo osoby („otec neuveden“, „?“)."""
    return p["n"].startswith(("otec neuveden", "matka neuvedena")) or p["n"] in ("", "?")


def fold(text):
    """Bez diakritiky, malými písmeny, bez „(?)“ a s jednou mezerou mezi slovy (porovnávání jmen)."""
    t = unicodedata.normalize("NFKD", (text or "").replace("(?)", " "))
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).lower().split())


def full_event(f):
    """Událost (*, ×, †) s platným úplným datem bez otazníku, jinak None."""
    e = parse_event(f)
    if not e or e["sym"] not in KIND or not (e["day"] and e["month"]) or "?" in DATE_SPAN_RE.match(f).group(0):
        return None
    try:
        datetime.date(e["year"], e["month"], e["day"])
    except ValueError:
        return None
    return e


def _stem(word):
    """Kmen příjmení: bez diakritiky a bez první shodné koncovky z „ova“, „a“, „y“ (Nováková, Novák → novak)."""
    w = fold(word)
    for end in ("ova", "a", "y"):
        if w.endswith(end):
            return w[:-len(end)]
    return w


def _named_in(p, text):
    """Stojí osoba ve faktu sňatku? Každá část křestního jména (Jan-Pavel: jan i pavel) jako celé slovo a celé
    slovo se stejným kmenem některé části příjmení (Nováková-Svobodová: novak nebo svobod). Jméno i fakt se
    dělí na slova stejně."""
    words = re.sub(r"\([^)]*\)", " ", p.get("n") or "").split()
    if len(words) < 2:
        return False
    split = lambda s: re.findall(r"[^\W\d_]+", fold(s))
    tokens, given, stems = split(text), split(" ".join(words[:-1])), {_stem(t) for t in split(words[-1])}
    return bool(given) and all(g in tokens for g in given) and any(_stem(t) in stems for t in tokens)


def _spouse(P, k, e, f):
    """Manžel na k ^ 1 je účastníkem sňatku, když je jménem ve faktu, nebo má vlastní sňatek se stejným datem."""
    sp = P.get(k ^ 1) if k > 1 else None
    if sp is None or placeholder(sp):
        return False
    date = (e["day"], e["month"], e["year"])
    own = [full_event(g) for g in sp.get("f", [])]
    return _named_in(sp, e["rest"]) or any(o and o["sym"] == "×" and (o["day"], o["month"], o["year"]) == date for o in own)


def anniversaries(P, slugs, today_year, places=None):
    """Výročí pro „Tento týden před lety“: každé narození (*), sňatek (×) a úmrtí (†) s platným dnem i měsícem.
    Sňatek: osoba s faktem a manžel na k ^ 1 (u aliasu na páru aliasu), jen pokud ho fakt jmenuje nebo má
    sňatek se stejným datem (_spouse). Záznam = datum + účastníci; záznamy téhož data se společným účastníkem
    se sloučí (alias nic nezdvojí), místo z nejdřív vzniklého záznamu (prázdné se doplní). Vynechá se událost s žijícím účastníkem a kvůli
    soukromí i sňatek, kde je žijící osoba na k ^ 1. places = data/mista.json (název → re). Týden vybírá prohlížeč."""
    who, blocked, entries = {}, set(), []
    for k, p in sorted(P.items()):
        if k not in slugs or placeholder(p):
            continue
        who[slugs[k]] = p
        seen = set()
        for f in p.get("f", []):
            e = full_event(f)
            if not e or e["sym"] != "×" and e["sym"] in seen:
                continue                                 # druhý údaj o narození či úmrtí (rozpor) se nebere
            seen.add(e["sym"])
            date = (e["month"], e["day"], e["year"], e["sym"])
            people = [slugs[k]]
            if e["sym"] == "×":
                sp = P.get(k ^ 1) if k > 1 else None
                if sp is not None and not placeholder(sp) and is_living(sp, today_year):
                    blocked.add((date, slugs[k]))
                if _spouse(P, k, e, f) and k ^ 1 in slugs:
                    people = [slugs[j] for j in sorted([k, k ^ 1])]
            entries.append(dict(date=date, people=list(dict.fromkeys(people)), place=_anniv_place(e, places)))
    merged = []                                          # slučování až do ustálení (alias spojí dva záznamy)
    for i, en in enumerate(entries):
        group = [m for m in merged if m["date"] == en["date"] and set(m["people"]) & set(en["people"])]
        group = sorted(group, key=lambda m: m["i"]) + [dict(en, i=i)]
        for m in group[:-1]:
            merged.remove(m)
        merged.append(dict(date=en["date"], i=group[0]["i"],              # místo z nejstaršího záznamu, prázdné se doplní
                           people=list(dict.fromkeys(s for m in group for s in m["people"])),
                           place=next((m["place"] for m in group if m["place"]), "")))
    out = [dict(m=en["date"][0], d=en["date"][1], y=en["date"][2], sym=en["date"][3], people=en["people"], place=en["place"])
           for en in merged
           if not any(s in who and is_living(who[s], today_year) or (en["date"], s) in blocked for s in en["people"])]
    return sorted(out, key=lambda a: (a["m"], a["d"], a["y"], "*×†".index(a["sym"])))


LIFE_WHAT = {"*": "narození", "×": "svatba", "†": "úmrtí"}
PREPS = {"v", "ve", "na", "u", "z", "ze", "do", "při"}     # povolání končí před první předložkou


def _occ_label(text):
    """Povolání z faktu: slova před první předložkou (a za čárkou už ne), nejvýš 3 („zednický pomocník“);
    fakt začínající předložkou celý, nejvýš 3 slova („v domácnosti“)."""
    words = text.split()
    if words and words[0].lower() in PREPS:
        return " ".join(words[:3])
    out = []
    for w in words:
        if w.lower() in PREPS or len(out) == 3:
            break
        out.append(w)
        if w.endswith(","):
            break
    return " ".join(out).strip(",.;:")


def _dated(p):
    """Události života s rokem podle roku: narození, sňatky, povolání s rokem, úmrtí. U * a † jen první údaj.
    text = kde hledat místo (u události zbytek za datem, u povolání celý fakt bez roku)."""
    out, seen = [], set()
    for f in p.get("f", []):
        e, oy = parse_event(f), occupation_years(f)
        if e and e["sym"] in KIND and not (e["sym"] != "×" and e["sym"] in seen):
            seen.add(e["sym"])
            out.append(dict(year=e["year"], rank="*×†".index(e["sym"]), sym=e["sym"], word=LIFE_WHAT[e["sym"]],
                            text=re.sub(r"^\(\?\)\s*", "", e["rest"]), e=e))   # „1863 (?) Břilice“
        elif oy:
            out.append(dict(year=oy[1], rank=1, sym="", word=_occ_label(oy[0]), text=oy[0], e=None,
                            approx=_is_approx(f)))
    return sorted(out, key=lambda x: (x["year"], x["rank"]))


def life_events(p, today_year, places=None, spouse=None):
    """Život na jedné čáře: {year, label, place, sym} podle roku. U povolání a sňatku je place název z
    data/mista.json (places: název → re), nebo nic; sňatek má navíc spouse = jméno manžela (spouse = osoba
    na k ^ 1), jen když ho fakt jmenuje (_named_in). Povolání má sym "". Bez † s rokem končí „† ?“;
    žijící a bez událostí s rokem nic."""
    if is_living(p, today_year):
        return []
    out = []
    for it in _dated(p):
        e = it["e"]
        if not e:
            year = f"asi {it['year']}" if it["approx"] else it["year"]
            out.append(dict(year=it["year"], label=f"{year} {it['word']}", place=_occ_place(it["text"], places) or "",
                            sym=""))
        elif e["sym"] == "×":
            name, _ = _find_place(it["text"], places)
            named = spouse is not None and not placeholder(spouse) and _named_in(spouse, e["rest"])
            out.append(dict(year=e["year"], label=f"× {e['year']}", place=name or "", sym="×",
                            spouse=spouse["n"] if named else ""))
        else:
            place = _anniv_place(e, places) or (e["place"] if e["place"][:1].isupper() else "")
            out.append(dict(year=e["year"], label=f"{e['sym']} {e['year']}", place=place, sym=e["sym"]))
    if out and not any(x["sym"] == "†" for x in out):        # i „† (podle stromu)“ bez roku = neznámé úmrtí
        out.append(dict(year=None, label="† ?", place="", sym="?"))
    return out


def person_places(p, mista):
    """Mapa na stránce osoby: místa z data/mista.json se souřadnicemi v pořadí života, {n, name, lat, lon,
    years: [od, do], what}. Místo události musí stát na začátku za datem (u sňatku by jinak bylo místem
    příjmení), u povolání kdekoli (u stěhování cíl). Hrob („pohřbena v Protivíně“) přijde nakonec s rokem
    z faktu, jinak s rokem úmrtí; bez roku se nekreslí. Stejné místo vícekrát = jeden špendlík."""
    places = {n: e.get("re") for n, e in mista.items()}
    pins = {}

    def pin(name, year, what):
        if not name or "lat" not in mista[name] or "lon" not in mista[name]:
            return
        x = pins.setdefault(name, dict(name=name, lat=mista[name]["lat"], lon=mista[name]["lon"],
                                       years=[year, year], what=[]))
        x["years"] = [min(x["years"][0], year), max(x["years"][1], year)]
        x["what"].append(what)

    dated = _dated(p)
    for it in dated:
        name = _occ_place(it["text"], places) if not it["e"] else _find_place(it["text"], places)[0]
        pin(name, it["year"], f"{it['word']} {'asi ' if it.get('approx') else ''}{it['year']}")
    death = next((it["year"] for it in dated if it["sym"] == "†"), None)
    for f in p.get("f", []):
        if BURIAL_RE.match(f):
            d = DATE_RE.search(f)
            year = int(d.group(3)) if d else death
            if year:
                pin(_find_place(f, places, anywhere=True)[0], year, f"hrob {year}")
    return [dict(pin, n=i, what=", ".join(pin["what"])) for i, pin in enumerate(pins.values(), 1)]


def places_with_houses(places, house_ids, houses, mista):
    """Mapa osoby + obce jejích domů (people[slug].houses), které na ní chybí: fakt bez roku („chalupník
    v Přechovicích čp. 3“) person_places vynechá. Doplní se na konec bez roku (years None, what „dům čp. 3, 5“);
    obec bez souřadnic ne."""
    out = list(places)
    have = {p["name"] for p in out}
    extra = {}
    for h in house_ids or []:
        x = houses.get(h) or {}
        obec = x.get("obec")
        if not obec or obec in have or "lat" not in mista.get(obec, {}):
            continue
        extra.setdefault(obec, []).append(x.get("label", "").rsplit("čp. ", 1)[-1])
    for obec, cps in extra.items():
        out.append(dict(name=obec, lat=mista[obec]["lat"], lon=mista[obec]["lon"], years=None,
                        what="dům čp. " + ", ".join(cps), n=len(out) + 1))
    return out


GODPARENT_RE = re.compile(r"^\[Kmot(?:r|ra|ři)\]\s*(.*)$", re.M)
NAME_LINE_RE = re.compile(r"^\[Jméno\]\s*(.*)$", re.M)


def godparent_names(orig):
    """Kmotři z přepisu (prepisy.json, orig): řádky [Kmotr], [Kmotra], [Kmotři]; jméno je text do první čárky,
    dvojice „X a Y“ se rozdělí."""
    out = []
    for line in GODPARENT_RE.findall(orig or ""):
        out += [n.strip() for n in line.split(",")[0].split(" a ") if n.strip()]
    return out


def _child_name(orig):
    """Křestní jméno pokřtěného z řádku [Jméno] („Marie Nováková (původně …)“ → „Marie“)."""
    m = NAME_LINE_RE.search(orig or "")
    words = re.split(r"[;,(]", m.group(1))[0].split() if m else []
    return words[0] if words else ""


def recurring_godparents(p, recs, prep):
    """Kmotr, který se vrací: kdo stál za kmotra aspoň u dvou křtů (druh N) citovaných u osoby, mimo její
    vlastní křest (datum sedí s jejím doloženým narozením; bez něj ji jmenuje řádek [Jméno]). Jména podle zápisu
    „kmotri“, jinak z přepisu; porovnává se bez diakritiky (fold). → [{name, records: [{key, child, year}], count}]."""
    birth = proven_events(p, recs).get("*")
    found = {}
    for k in dict.fromkeys(p.get("r", [])):
        r = recs.get(k)
        if not r or r.get("kind") != "N":
            continue
        orig = prep.get(k, {}).get("orig", "")
        m = NAME_LINE_RE.search(orig)
        named = m and _named_in(p, re.sub(r"\([^)]*\)", " ", m.group(1)))   # „(původně Straková)“ se nepočítá
        if _proves(birth, r.get("date", "")) if birth else named:
            continue                                     # dítě po rodiči: při doloženém narození rozhoduje datum
        ys = re.findall(r"\d{4}", r.get("date", ""))
        rec = dict(key=k, child=_child_name(orig), year=int(ys[0]) if ys else None)
        for name in r.get("kmotri") or godparent_names(orig):
            g = found.setdefault(fold(name), dict(name=name, records=[]))
            if k not in [x["key"] for x in g["records"]]:
                g["records"].append(rec)
    return [dict(g, records=sorted(g["records"], key=lambda x: x["year"] or 0), count=len(g["records"]))
            for g in found.values() if len(g["records"]) >= 2]


MIN_PEOPLE = 5                                           # přehled neukazuje zjištění z méně lidí
STATES = ("doc", "fam", "prob", "mh")
MONTHS = ["lednu", "únoru", "březnu", "dubnu", "květnu", "červnu", "červenci", "srpnu", "září", "říjnu",
          "listopadu", "prosinci"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
NOT_OCC = {"z", "ze", "v", "ve", "bez", "dcera", "syn", "vdova", "pohřben", "pohřbena", "pracoval", "pracovala",
           "legitimován", "legitimována", "manželství"}   # první slova faktů, která nejsou povolání


def gen_name(g):
    """Stejná slova jako genName ve web/src/lib/data.js."""
    return ["výchozí osoba", "rodiče", "prarodiče", "praprarodiče"][g] if g < 4 else f"{g}. generace ({'pra' * (g - 1)}rodiče)"


def positions(P, same):
    """Místo v rodokmenu → osoba; alias (předek vícekrát) ukazuje na tentýž slovník jako jeho kanonické číslo
    a citace z aliasu se k osobě přidají (jako u stránky osoby v export_web). P se nemění."""
    merged = {}
    for k, p in P.items():
        if k not in same:
            refs = p.get("r", []) + [r for a, c in same.items() if c == k and a in P for r in P[a].get("r", [])]
            merged[k] = dict(p, r=list(dict.fromkeys(refs)))
    return {k: merged[same[k]] if k in same and same[k] in merged else merged.get(k, P[k]) for k in P}


def coverage(P, ks=None, root_gen=0):
    """Stav doložení po generacích (od rodičů dál): kolik míst čekáme a kolik jich je doc/fam/prob/mh;
    known = známá místa (z matriky, od rodiny i ze stromu), unk = zbylá místa.
    ks omezí počítání na tato Kekulého čísla (rod: jeho členové a root_gen=3)."""
    rows = {}
    for k in (P if ks is None else [k for k in ks if k in P]):
        g = k.bit_length() - 1
        if g < 1:
            continue
        r = rows.setdefault(g, dict(gen=g, label=gen_name(g), expected=2 ** (g - root_gen), doc=0, fam=0, prob=0, mh=0, unk=0))
        st = P[k].get("st")
        if st in STATES:
            r[st] += 1
    for r in rows.values():
        r["known"] = sum(r[s] for s in STATES)
        r["unk"] = max(0, r["expected"] - r["known"])
    return [rows[g] for g in sorted(rows)]


def _doloz(P):
    rows = coverage(P)
    n = len({id(p) for k, p in P.items() if k > 1 and p.get("st") == "doc"})   # lidé, ne místa
    full = [r for r in rows if r["doc"] == r["expected"]]
    start = full[-1] if full else rows[0] if rows else None
    if not start:
        return None
    if start["doc"] == start["expected"]:
        s = (f"Všechny {start['label']} (**{start['expected']}**) známe z matrik." if start["gen"] < 4
             else f"Celou {start['gen']}. generaci (**{start['expected']} lidí**) známe z matrik.")
    else:
        s = f"Z matrik známe **{start['doc']} z {start['expected']}** ({start['label']})."
    nxt = [r for r in rows if r["gen"] > start["gen"]][:2]
    if nxt:
        s += f" O generaci dál je to **{nxt[0]['doc']} z {nxt[0]['expected']}**"
        if len(nxt) > 1:
            s += f", v {nxt[1]['gen']}. generaci **{nxt[1]['doc']} z {nxt[1]['expected']}**"
        s += ". Čím hlouběji, tím víc míst zůstává prázdných – a na ty se dá ještě přijít."
    chart = dict(labels=[str(r["gen"]) for r in rows], values=[r["doc"] for r in rows])
    return dict(id="doloz", title="Jak daleko sahá rodokmen", sentence=s, chart=chart, n=n)


def _age(b, d):
    """Věk v letech; měsíc a den se porovnávají, jen když jsou známé u obou dat."""
    age = d["year"] - b["year"]
    if b["month"] and d["month"]:
        if d["month"] < b["month"] or d["month"] == b["month"] and b["day"] and d["day"] and d["day"] < b["day"]:
            age -= 1
    return age


def _zivot(people, recs):
    cohorts = {}
    for p in people:
        ev = proven_events(p, recs)
        b, d = ev.get("*"), ev.get("†")
        if b and d and d["year"] >= b["year"]:
            cohorts.setdefault(b["year"] // 50 * 50, []).append(_age(b, d))
    cohorts = {c: a for c, a in sorted(cohorts.items()) if len(a) >= MIN_PEOPLE}
    if not cohorts:
        return None
    avg = {c: round(sum(a) / len(a)) for c, a in cohorts.items()}
    c1 = max(cohorts, key=lambda c: (len(cohorts[c]), -c))
    s = f"Předkové narození kolem roku {c1} se dožívali v průměru **{avg[c1]} let**"
    if c1 + 50 in cohorts:
        s += f", o padesát let později **{avg[c1 + 50]}** (z {len(cohorts[c1])} a {len(cohorts[c1 + 50])} lidí)."
    else:
        s += f" (z {len(cohorts[c1])} lidí)."
    return dict(id="zivot", title="Jak dlouho žili", sentence=s,
                chart=dict(labels=[str(c) for c in avg], values=list(avg.values())), n=sum(len(a) for a in cohorts.values()))


def _mesice(people, recs):
    counts = [0] * 12
    for p in people:
        e = proven_events(p, recs).get("*")
        if e and e["month"] and 1 <= e["month"] <= 12:
            counts[e["month"] - 1] += 1
    n = sum(counts)
    if not n:
        return None
    top = max(counts)
    lead = [m for m in range(12) if counts[m] == top]
    others = [m for m in range(12) if counts[m] < top]
    s = "Nejvíc dětí se narodilo v " + _and([f"**{MONTHS[m]}**" for m in lead])
    if others:
        low = min(counts[m] for m in others)
        lows = [m for m in others if counts[m] == low]
        if len(lows) == len(others):
            s += ", v ostatních měsících žádné" if low == 0 else ""
        elif len(lows) <= 3:
            s += (", v " + _and([MONTHS[m] for m in lows]) + " žádné") if low == 0 else ", nejméně v " + _and([MONTHS[m] for m in lows])
    s += f" (z {n} lidí)."
    return dict(id="mesice", title="Kdy přicházeli na svět", sentence=s, chart=dict(labels=ROMAN, values=counts), n=n)


def _and(words):
    """„a“, „a a b“, „a, b a c“."""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " a " + words[-1]


def _top(counter, n_people, sid, title, intro, min_count=1):
    top = sorted(((w, c) for w, c in counter.items() if c >= min_count), key=lambda kv: (-kv[1], kv[0]))[:6]
    if not top:
        return None
    s = intro + ", ".join(f"**{w}** ({c})" for w, c in top) + f" (z {n_people} lidí)."
    return dict(id=sid, title=title, sentence=s, chart=dict(labels=[w for w, _ in top], values=[c for _, c in top]), n=n_people)


def _jmena(people):
    c, n = {}, 0
    for p in people:
        parts = (p.get("n") or "").split()
        if not parts or "?" in p.get("n", "") or re.search(r"[()]", parts[0]):
            continue                                     # otazník kdekoli ve jméně: nevíme, která část je nejistá
        w = parts[0]
        if w:
            c[w] = c.get(w, 0) + 1
            n += 1
    return _top(c, n, "jmena", "Jak se jmenovali", "Nejčastěji ")


def _remesla(people, recs):
    """Povolání se počítá, jen když má rok a u osoby je citovaný zápis z téhož roku. Graf ukazuje jen povolání
    aspoň dvou lidí; n (práh pěti lidí) jsou všichni s doloženým povoláním."""
    c, n = {}, 0
    for p in people:
        years = {int(y) for k in p.get("r", []) if k in recs and "?" not in recs[k].get("date", "")
                 for y in re.findall(r"\d{4}", recs[k].get("date", ""))}
        words = set()
        for f in p.get("f", []):
            oy = occupation_years(f)
            if not oy or is_uncertain(f) or oy[1] not in years:
                continue
            w = (oy[0].split() or [""])[0].strip(",.;:").lower()
            if w and w not in NOT_OCC:
                words.add(w)
        for w in words:
            c[w] = c.get(w, 0) + 1
        n += bool(words)
    return _top(c, n, "remesla", "Čím se živili", "Nejčastěji ", min_count=2)


def overview(P, recs, today_year):
    """Oddíly stránky /prehled/: věta s tučnými čísly (**…**), data malého grafu a počet lidí n.
    Počítá jen s doloženými (doc) nežijícími předky a údaji, které stojí v citovaném zápisu (proven_syms).
    Výchozí osoba (číslo 1) mezi předky není. Předek v rodokmenu vícekrát (stejný slovník, viz positions)
    se počítá jednou; oddíl z méně než MIN_PEOPLE lidí vypadne."""
    people = list({id(p): p for k, p in sorted(P.items())
                   if k > 1 and p.get("st") == "doc" and not is_living(p, today_year)}.values())
    secs = [_doloz(P), _zivot(people, recs), _mesice(people, recs), _jmena(people), _remesla(people, recs)]
    return [s for s in secs if s and s["n"] >= MIN_PEOPLE]


# ---- celá rodina (z Velké rodiny) ------------------------------------------------------------------------------

SIDE_NAME_RE = re.compile(r"^(.*?)\s*\((?:\*\s*)?(\d{4})")   # „Marie Nováková (* 1888)“, „Johann Müller (1867–1868)“


def side_keys(side, recs):
    """Boční příbuzní z osoby.py SIDE, kteří mají zápis: fold(jméno) + "|" + rok narození → klíče zápisů."""
    out = {}
    for s in side:
        m = SIDE_NAME_RE.match(s.get("n", ""))
        rs = [r for r in s.get("r", []) if r in recs]
        if m and rs:
            out.setdefault(fold(m.group(1)) + "|" + m.group(2), []).extend(rs)
    return out


def _death_year(p):
    m = re.search(r"\d{4}", (p.get("death") or ["", ""])[0] or "")
    return int(m.group(0)) if m else None


def _card(vr, i, side, other=None):
    p = vr[i]
    dy = _death_year(p)
    return dict(id=i, name=p["name"], years=p.get("years", ""), rel=p.get("rel", ""), male=p.get("male", True),
                slug=p.get("slug") if p.get("k") else None, line=bool(p.get("k")),
                doc=p.get("st") == "doc" or f"{fold(p['name'])}|{p.get('by')}" in side,
                infant=bool(p.get("by") and dy is not None and 0 <= dy - p["by"] <= 1),
                otherParent=vr[other]["name"] if other else None,
                otherParentMale=vr[other].get("male", True) if other else None)


def _by_birth(cards, vr):
    return sorted(cards, key=lambda c: vr[c["id"]].get("by") or 9999)


def full_family(vr, vr_id, side_keys):
    """Rodiče, sourozenci, manželé a děti osoby z Velké rodiny jako karty pro stránku osoby.
    Nevlastní sourozenec (osoba má oba rodiče, on jednoho jiného) má otherParent. Rodiče otec první, ostatní podle roku narození."""
    P = vr["people"]
    p = P[vr_id]
    pars = p.get("parents", [])
    sibs = list(dict.fromkeys(c for x in pars for c in P[x].get("children", []) if c != vr_id))
    siblings = []
    for s in sibs:
        other = [x for x in P[s].get("parents", []) if x not in pars]
        siblings.append(_card(P, s, side_keys, other[0] if other and len(pars) == 2 else None))
    return dict(
        parents=sorted((_card(P, x, side_keys) for x in pars), key=lambda c: not c["male"]),
        siblings=_by_birth(siblings, P),
        spouses=_by_birth([_card(P, s["id"], side_keys) for s in p.get("spouses", [])], P),
        children=_by_birth([_card(P, c, side_keys) for c in dict.fromkeys(p.get("children", []))], P),
    )


# ---- kde jsme hledali (data/hledani.json) ----------------------------------------------------------------------

def searches_for(k, hledani):
    """Neúspěšná hledání u osoby k seskupená podle otázky „co“ (v pořadí výskytu): {co, books: [{kniha, svazek,
    od, do, proslo, snimky}], nalezeno} – nalezeno = první vyplněné {rok, text} ve skupině, jinak None."""
    groups = {}
    for h in hledani:
        if h.get("k") != k:
            continue
        g = groups.setdefault(h["co"], dict(co=h["co"], books=[], nalezeno=None))
        g["books"].append(dict(kniha=h["kniha"], svazek=h.get("svazek"), od=h["od"], do=h["do"],
                               proslo=h.get("proslo", []), snimky=h.get("snimky", "")))
        g["nalezeno"] = g["nalezeno"] or h.get("nalezeno")
    return list(groups.values())


# ---- stránka rodu: linie příjmení, časová osa, mapa v čase, podoby jména ---------------------------------------

DECL = ("ová", "á", "ý", "a")                            # koncovky příjmení: Nováková, Horská, Horský, Urban


def _surname(name):
    """Příjmení = poslední slovo jména bez závorek („Paul Otava (Wotava)“, „Magdalena Novotná (?)“)."""
    words = re.sub(r"\([^)]*\)", " ", name or "").split()
    return words[-1] if words else ""


def _decl(word):
    """Malými písmeny (s diakritikou) a bez první shodné koncovky z DECL."""
    w = word.lower()
    for end in DECL:
        if w.endswith(end):
            return w[:-len(end)]
    return w


def surname_group(name, variants):
    """Skupina rovnocenných podob (data/web.json varianty_prijmeni), do které patří příjmení osoby; jinak []."""
    key = _decl(_surname(name))
    return next((g for g in variants or [] if key in {_decl(v) for v in g}), [])


def surname_stem(name, variants):
    """Kmen příjmení: poslední slovo jména, podoba ze skupiny variant → první podoba skupiny, malými písmeny,
    bez první shodné koncovky z „ová“, „á“, „ý“, „a“ (Nováková, Novákj → novák; Urbanová → urban).
    Diakritika zůstává (Novák a Novak spojí jen skupina variant)."""
    group = surname_group(name, variants)
    return _decl(group[0] if group else _surname(name))


def surname_line(P, root, variants):
    """Linie příjmení rodu (Pavlovo rozhodnutí): od nejstaršího nositele po otcích (2k) nad root, dolů od root // 2
    každý, kdo se s příjmením narodil; dál se jde jen přes muže (sudé k), za ženou linie končí. Nejstarší první."""
    if root not in P or placeholder(P[root]):
        return []
    stem = surname_stem(P[root]["n"], variants)
    bears = lambda k: k in P and not placeholder(P[k]) and surname_stem(P[k]["n"], variants) == stem
    out, k = [root], root
    while bears(2 * k):
        k *= 2
        out.append(k)
    k = root
    while k > 1 and (k == root or k % 2 == 0) and bears(k // 2):
        k //= 2
        out.append(k)
    return sorted(out, reverse=True)


def _years_word(n):
    return "rok" if n == 1 else "roky" if 2 <= n <= 4 else "let"


def _hover(p, k, by, by_est, end, events):
    """Věty k dějinným událostem, které začaly za života (od narození do úmrtí, u neznámého úmrtí do posledního
    údaje). Cholera „přišla“, hladomor „přišel“, válka „začala“, jiná změna „v roce …: …“."""
    words = (p.get("n") or "").split()
    first = words[0] if words else ""
    male = p.get("sex", "M") == "M" if k == 1 else k % 2 == 0
    out = []
    for ev in events:
        if not by <= ev["od"] <= end:
            continue
        age = ev["od"] - by
        if age == 0:
            who = f"{first} ještě {'neměl' if male else 'neměla'} ani rok"
        else:
            who = f"{first} {'měl' if male else 'měla'} {'asi ' if by_est else ''}{age} {_years_word(age)}"
        name = ev["nazev"]
        if ev.get("veta"):
            out.append(f"{who}, {ev['veta']}.")
        elif re.match(r"hladomor|mor\b", name):
            out.append(f"{who}, když přišel {name}.")
        elif "cholera" in name:
            out.append(f"{who}, když přišla {name}.")
        elif "válk" in name:
            out.append(f"{who}, když začala {name}.")
        else:
            out.append(f"{who} v roce {ev['od']}: {name}.")
    return out


def _what(p):
    """Podtitul řádku časové osy: nejvýš dvě povolání z faktů bez otazníku a bez údaje ze stromu."""
    out = []
    for f in p.get("f", []):
        if EVENT_RE.match(f) or is_uncertain(f) or f.startswith(("pohřben", "TÁŽ OSOBA")):
            continue
        oy = occupation_years(f)
        label = _occ_label(oy[0] if oy else f)
        if label and label.split()[0].lower() not in NOT_OCC and label not in out:
            out.append(label)
    return ", ".join(out[:2])


def events_for_line(events, slug):
    """Dějinné události pro osu rodu: bez pole rody platí pro všechny rody, s ním jen pro vyjmenované (místní
    události, třeba otevření trati)."""
    return [e for e in events if "rody" not in e or slug in e["rody"]]


def line_timeline(P, ks, recs, events, today_year, slugs=None):
    """Časová osa linie příjmení (ks nejstarší první): řádek = život od narození do úmrtí. src = doc, jen když
    je narození doloženo zápisem (proven_syms), jinak fam (stav osoby od rodiny) nebo mh (ze stromu). byEst = rok
    narození odhadnutý („asi“, otazník, strom, nebo z prvního údaje); dyKnown = úmrtí s rokem bez otazníku a ne ze stromu, jinak je dy rok
    posledního údaje. hover = věty k událostem z data/udalosti.json. Žijící jen jménem, bez dat a vět."""
    rows = []
    for k in ks:
        p = P.get(k)
        if p is None or placeholder(p):
            continue
        row = dict(k=k, slug=(slugs or {}).get(k), name=p["n"], what="", by=None, dy=None, byEst=False,
                   dyKnown=False, src="fam", living=is_living(p, today_year), hover=[])
        if row["living"]:
            rows.append(row)
            continue
        facts = p.get("f", [])
        births = [f for f in facts if f.startswith("*")]
        # † s otazníkem nebo ze stromu není známé úmrtí: pruh vybledne a věty končí posledním jistým údajem
        unsure = [f for f in facts if f.startswith("†") and is_uncertain(f)]
        deaths = [f for f in facts if f.startswith("†") and re.search(r"\d{4}", f) and f not in unsure]
        e = parse_event(births[0]) if births else None
        by = e["year"] if e else next((int(y) for f in births for y in re.findall(r"\d{4}", f)), None)
        by_est = not e or is_uncertain(births[0])
        dated = [it["year"] for it in _dated(dict(p, f=[f for f in facts if f not in unsure]))]
        if by is None and dated:                         # bez roku narození: odhad z prvního údaje
            by = min(dated) - 25
        if by is None:
            continue
        dy = int(re.search(r"\d{4}", deaths[0]).group(0)) if deaths else None
        end = dy if dy is not None else max(dated + [by])
        src = "doc" if "*" in proven_syms(p, recs) else "fam" if p.get("st") == "fam" else "mh"
        row.update(what=_what(p), by=by, dy=end, byEst=by_est, dyKnown=dy is not None, src=src,
                   hover=_hover(p, k, by, by_est, end, events))
        rows.append(row)
    years = [r["by"] for r in rows if r["by"] is not None]
    return {"rows": rows, "events": events, "from": min(years) if years else today_year, "to": today_year}


def _km(a, b):
    """Vzdálenost dvou bodů {lat, lon} v km (haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def line_places(P, ks, mista, today_year=None):
    """Mapa rodu v čase: datovaná místa linie příjmení (narození, sňatek, povolání s rokem, úmrtí) se souřadnicemi
    z data/mista.json podle roku, {year, name, lat, lon, label}; stejné místo po sobě jen jednou (první údaj).
    Fakty s otazníkem a ze stromu a žijící se vynechají. km = vzdálenost prvního a posledního místa,
    summary = věta pod mapu (_moved)."""
    today_year = today_year or datetime.date.today().year
    places = {n: e.get("re") for n, e in mista.items()}
    pts = []
    for k in ks:
        p = P.get(k)
        if p is None or placeholder(p) or is_living(p, today_year):
            continue
        for it in _dated(dict(p, f=[f for f in p.get("f", []) if not is_uncertain(f)])):
            name, _ = _find_place(it["text"], places, anywhere=not it["e"])
            if name and "lat" in mista[name] and "lon" in mista[name]:
                pts.append(dict(year=it["year"], name=name, lat=mista[name]["lat"], lon=mista[name]["lon"],
                                label=f"{p['n']}, {it['word']}"))
    pts.sort(key=lambda x: x["year"])                    # stabilní: ve stejném roce starší generace první
    out = [x for i, x in enumerate(pts) if i == 0 or x["name"] != pts[i - 1]["name"]]
    km = round(_km(out[0], out[-1])) if out else None
    return dict(points=out, km=km, summary=_moved(out, km, mista))


def _moved(pts, km, mista):
    """Věta pod mapou rodu. „jen“ jen pod 50 km. 2. pád místa je v data/mista.json pod „druhy_pad“; když ho
    jedno z míst nemá, věta je bez skloňování („první místo Lhota, poslední Praha“)."""
    if not pts:
        return ""
    first, last = pts[0]["name"], pts[-1]["name"]
    if km < 5:
        return f"Rod zůstal na jednom místě: {first}."
    head = f"Za {pts[-1]['year'] - pts[0]['year']} let se rod posunul {'jen ' if km < 50 else ''}asi o {km} km"
    a, b = mista[first].get("druhy_pad"), mista[last].get("druhy_pad")
    return f"{head} – z {a} do {b}." if a and b else f"{head}, první místo {first}, poslední {last}."


def vr_points(vr, mista, extra=()):
    """Širší rodina na mapě: místa narození, pobytu (první RESI ze stromu) a úmrtí lidí z Velké rodiny
    (velka-rodina.json), kteří nejsou přímí předci (k je None) a nežijí. Místo musí v textu stát na začátku a mít
    v data/mista.json souřadnice. extra = lidé mimo Velkou rodinu (větve bez vazby na strom), dict(id, name, years,
    href, note, birth, death, resi); do popupu jdou i s odkazem href a poznámkou note.
    [{place, lat, lon, first, people: [{id, name, years[, href, note]}]}], first = nejdřívější rok události na místě
    (nebo None), nejvíc lidí první."""
    places = {n: e.get("re") for n, e in mista.items()}
    out = {}
    people = list((vr or {}).get("people", {}).items()) + [(e["id"], dict(e, k=None, living=False)) for e in extra]
    for i, p in people:
        if p.get("k") is not None or p.get("living"):
            continue
        for date, text in (p.get("birth") or ["", ""], p.get("resi") or ["", ""], p.get("death") or ["", ""]):
            name, _ = _find_place((text or "").strip(), places)
            if not name or "lat" not in mista[name] or "lon" not in mista[name]:
                continue
            pt = out.setdefault(name, dict(place=name, lat=mista[name]["lat"], lon=mista[name]["lon"], first=None, people=[]))
            y = re.search(r"\d{4}", date or "")
            if y and (pt["first"] is None or int(y.group(0)) < pt["first"]):
                pt["first"] = int(y.group(0))
            if all(q["id"] != i for q in pt["people"]):
                pt["people"].append(dict(id=i, name=p.get("name", ""), years=p.get("years", ""),
                                         **{k: p[k] for k in ("href", "note") if p.get(k)}))
    return sorted(out.values(), key=lambda pt: (-len(pt["people"]), pt["place"]))


def first_year_at(place_rx, people_facts):
    """Posuvník let na mapě rodiny: nejdřívější rok datované události (parse_event) nebo povolání s rokem
    (occupation_years), jejíž text odpovídá místu (place_rx = re z data/mista.json, jinak název). people_facts =
    seznam faktů každé osoby; žijící vynechá volající, fakty ze stromu a s otazníkem se nepočítají. Bez shody None."""
    years = []
    for facts in people_facts:
        for f in facts:
            if is_uncertain(f):
                continue
            e, oy = parse_event(f), occupation_years(f)
            if e and place_rx.search(e["rest"]):
                years.append(e["year"])
            elif oy and place_rx.search(oy[0]):
                years.append(oy[1])
    return min(years, default=None)


def _place_text(text, cut):
    """Místo z textu za datem: bez závorek („(fara …)“, „(?)“), do slova cut (jméno manžela). Vrací (název do
    „čp.“ nebo čárky, úsek do cut pro porovnání s data/mista.json)."""
    words = re.sub(r"\([^)]*\)", " ", text).split()
    words = words[:next((i for i, w in enumerate(words) if cut(w)), len(words))]
    name = []
    for w in words:
        if w.startswith("čp."):
            break
        name.append(w.rstrip(","))
        if w.endswith(","):
            break
    return " ".join(name), " ".join(words)


def unmatched_places(P, mista):
    """Kontrola: místa z datovaných událostí (*, ×, †, pokřtěn) a povolání s rokem, která data/mista.json nezná,
    v pořadí osob. U sňatku končí místo před jménem manžela (k ^ 1, _named_in) nebo křestním jménem kohokoli z P,
    u povolání začíná prvním slovem s velkým písmenem. Žijící a zástupci se vynechají."""
    today_year = datetime.date.today().year
    places = {n: e.get("re") for n, e in mista.items()}
    given = {fold(p["n"].split()[0]) for p in P.values() if p.get("n", "").split() and not placeholder(p)}
    out = []
    for k, p in sorted(P.items()):
        if placeholder(p) or is_living(p, today_year):
            continue
        sp = P.get(k ^ 1) if k > 1 else None
        for f in p.get("f", []):
            e, oy = parse_event(f), occupation_years(f)
            if e:
                text = re.sub(r"^\(\?\)\s*", "", e["rest"])
                names = set()
                if e["sym"] == "×":           # sňatek: místo končí před manželem nebo jakýmkoli křestním jménem z P
                    names = given | ({fold(sp["n"].split()[0])} if sp and not placeholder(sp) and _named_in(sp, text) else set())
                cut = lambda w, names=names: fold(w) in names
            elif oy:
                words = oy[0].split()
                i = next((i for i, w in enumerate(words) if i and w[:1].isupper()), None)
                if i is None:
                    continue
                text, cut = " ".join(words[i:]), lambda w: False
            else:
                continue
            name, seg = _place_text(text, cut)
            if name[:1].isupper() and not _find_place(seg, places, anywhere=True)[0] and name not in out:
                out.append(name)
    return out


def _form_key(word):
    """Slovo z přepisu bez koncovek -ovi/-em a pak DECL (Novákem, Nováková → novák)."""
    return _decl(re.sub(r"(?:ovi|em)$", "", word.lower()))


def surname_forms(ks, people_records, prep, variants):
    """Podoby příjmení ze skupiny variant (podle příjmení prvního z ks), které se opravdu vyskytují v přepisech
    (prepisy.json, orig) zápisů citovaných u osob ks. people_records = Kekulé → osoba s „n“ a „r“ (jako P).
    Slovo s velkým písmenem se porovná bez koncovek (_form_key) a počítá se za podobu ze skupiny v 1. pádě,
    takže Nováka i Nováková jsou Novák. Nejčastější první."""
    people = [people_records[k] for k in ks if k in people_records]
    if not people:
        return []
    group = surname_group(people[0]["n"], variants) or [_surname(people[0]["n"])]
    keys = {_form_key(g): g for g in reversed(group)}  # stejný klíč u dvou podob: vyhraje dřívější ve skupině
    counts = {}
    for key in dict.fromkeys(r for p in people for r in p.get("r", [])):
        for w in re.findall(r"[^\W\d_]+", prep.get(key, {}).get("orig", "")):
            g = keys.get(_form_key(w)) if w[:1].isupper() else None
            if g:
                counts[g] = counts.get(g, 0) + 1
    return sorted(counts, key=lambda g: (-counts[g], group.index(g)))
