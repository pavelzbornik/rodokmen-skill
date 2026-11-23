"""Vlastní stránky ověřených příbuzných mimo přímou linii (/pribuzny/<slug>/).

Bere osoby z Velké rodiny (web/public/velka-rodina.json), které nejsou přímí předci, nežijí a jsou ověřené
(st „doc“ z web.json → velka_rodina.overeno), nebo je zmiňuje osoby.py SIDE (zapisuje se jen to, co bylo čteno
v matrice nebo sčítání).
Ke každé najde zmínky v SIDE: vlastní záznam „Jméno (* rok)“, nebo skupinový záznam u sourozence či rodiče z linie, kde je
křestní jméno i rok narození. Rozšíření projektu, ve skillu rodokmen zatím není.
"""
import re, unicodedata

from web_pohledy import SIDE_NAME_RE, fold

# Záznam pojmenovaný osobou, který popisuje i její rodinu: „Matěj Procházka (1812–před 1887) a jeho synové“
GROUP_TITLE_RE = re.compile(r"\)\s+a\s+(?:jeho|její|jejich)\b")


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _key(p):
    return f"{fold(p['name'])}|{p.get('by')}"


# české a německé (latinské) podoby křestních jmen: matrika a strom je píšou různě
NAME_GROUPS = [g.split() for g in (
    "jan johann johannes joannes hans", "josef joseph josephus", "frantisek franz franciscus", "marie maria",
    "marianna mariana", "anna", "antonin anton antonius", "antonie antonia", "karel karl carl carolus",
    "matej mathias matthias matthaeus", "katerina katharina katherina catharina", "alzbeta elisabeth elisabetha",
    "vaclav wenzel wenzl wenceslaus", "jakub jakob jacob jacobus", "terezie theresia therese", "barbora barbara",
    "bartolomej bartholomaus bartholomaeus", "johana johanna jana", "filip philipp filipp", "pavel paul paulus",
    "tomas thomas", "vojtech adalbert", "rozalie rosalie rosalia", "ludmila ludmilla lidmila", "magdalena", "anezka agnes", "juliana julianna",
    "albina albine", "pavlina pauline paulina", "valburga walburga walburka", "lorenc lorenz vavrinec", "simon",
    "martin", "leonard leonhard", "mikulas nikolaus", "jiri georg", "petr peter", "ondrej andreas", "ignac ignaz", "augustin augustyn augustinus")]
_CANON = {v: g[0] for g in NAME_GROUPS for v in g}


def first_key(name):
    """Křestní jméno bez diakritiky v jednotné podobě: Maria → marie, Johann → jan."""
    words = fold(name).split()
    return _CANON.get(words[0], words[0]) if words else ""


def _surname(word):
    """Příjmení bez ženské a přídavné koncovky a bez přídechu W: Šimáková = Simák, Horská = Horský, Wotava = Otava
    (SIDE píše česky, strom rakouských rodů německy)."""
    x = re.sub(r"^w(?=o)", "", word)
    x = re.sub(r"ova$", "", x) if len(x) > 5 else x
    return re.sub(r"[ayi]$", "", x) if len(x) > 4 else x


def _loose(name, year):
    """Klíč vlastního záznamu: jednotné křestní jméno + zbytek jména (příjmení bez koncovky) + rok narození."""
    rest = fold(name).split()[1:]
    if rest:
        rest[-1] = _surname(rest[-1])
    return f"{first_key(name)} {' '.join(rest)}|{year}"


def _record_of(key, vr_p):
    """Zápis ze skupinového záznamu patří osobě: klíč bez křestního jména (arch sčítání) patří všem, jinak musí
    obsahovat její jméno (kterákoli podoba) a rok narození nebo úmrtí – „rapsach_krest_mariana_otava_1798“."""
    tokens = key.split("_")
    names = [t for t in tokens if t in _CANON]
    if not names:
        return True
    key_first = first_key(vr_p["name"])
    years = {str(vr_p["by"])} if vr_p.get("by") else set()
    if "umrti" in tokens:                                  # zápis o úmrtí nese v klíči rok úmrtí
        years |= set(re.findall(r"\d{4}", (vr_p.get("death") or [""])[0] or ""))
    if "snatek" in tokens and vr_p.get("by"):              # zápis o sňatku nese rok svatby (14 až 80 let po narození)
        years |= {t for t in tokens if t.isdigit() and vr_p["by"] + 14 <= int(t) <= vr_p["by"] + 80}
    return any(_CANON[t] == key_first for t in names) and (not years or bool(years & set(tokens)))


def _mentions(vr_p, entry):
    """Skupinový záznam SIDE zmiňuje osobu: křestní jméno (kterákoli podoba) jako slovo a rok narození, je-li známý."""
    key = first_key(vr_p["name"])
    if not key:
        return False
    forms = next((g for g in NAME_GROUPS if g[0] == key), [key])
    text = fold(entry.get("n", "") + " " + entry.get("t", ""))
    if not any(re.search(r"\b" + re.escape(f) + r"\b", text) for f in forms):
        return False
    return not vr_p.get("by") or str(vr_p["by"]) in text


def pages(vr, side, recs, side_keys):
    """Stránky příbuzných {slug: data}; do vr["people"][id]["page"] zapíše slug, ať na ně jde odkazovat."""
    P = vr["people"]
    out, used = {}, set()
    for i, p in sorted(P.items(), key=lambda x: (x[1].get("by") or 9999, x[1]["name"])):
        if p.get("k") or p.get("living"):
            continue
        # SIDE k = předek, ke kterému záznam patří: sourozenec z linie (pravidlo z osoby.py), u starších záznamů rodič;
        # u dětí sourozence předka (synovci, neteře) strýc nebo teta z linie, případně prarodič
        pars = set(p.get("parents", []))
        grand = {g for x in pars for g in P.get(x, {}).get("parents", [])}
        near = pars | grand | {c for x in pars | grand for c in P.get(x, {}).get("children", [])}
        parent_ks = {P[x]["k"] for x in near if P.get(x, {}).get("k")}
        own, group = [], []
        for s in side:
            m = SIDE_NAME_RE.match(s.get("n", ""))
            if m and _loose(m.group(1), m.group(2)) == _loose(p["name"], p.get("by")):
                own.append(s)
            elif s.get("k") in parent_ks and _mentions(p, s) and (not m or (
                    GROUP_TITLE_RE.search(s["n"])             # „X (roky) a jeho synové“ platí jen pro děti X
                    and any(_loose(P[x]["name"], P[x].get("by")) == _loose(m.group(1), m.group(2)) for x in pars if x in P))):
                group.append(s)
        if not (own or group or p.get("st") == "doc" or _key(p) in side_keys or p.get("records")):
            continue                                       # jen ze stromu, v matrikách jsme ho nečetli
        sources = [dict(name=s["n"], text=s.get("t", ""), records=[r for r in s.get("r", []) if r in recs]) for s in own]
        sources += [dict(name=s["n"], text=s.get("t", ""), records=[r for r in s.get("r", []) if r in recs and _record_of(r, p)])
                    for s in group]
        records = list(dict.fromkeys([r for s in sources for r in s["records"]] + side_keys.get(_key(p), [])
                                     + [r for r in p.get("records", []) if r in recs]))   # _ZAZNAM z doplňků stromu
        base = slugify(p["name"] + (f" {p['by']}" if p.get("by") else ""))
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        via = P.get(p.get("via")) if p.get("via") else None
        # doloženo: vlastní zápis, ověřený ve stromu, nebo zmínka z matrik či sčítání 1921 (narození do 1921);
        # u mladších je zmínka v SIDE údaj od rodiny
        doc = bool(records) or p.get("st") == "doc" or bool(p.get("by") and p["by"] <= 1921)
        out[slug] = dict(id=i, slug=slug, doc=doc, name=p["name"], years=p.get("years", ""), rel=p.get("rel", ""), male=p.get("male", True),
                         birth=p.get("birth", ["", ""]), death=p.get("death", ["", ""]), sources=sources, records=records,
                         facts=[f for s in own for f in s.get("f", [])],   # ověřená fakta z vlastního záznamu SIDE
                         via=dict(name=via["name"], years=via.get("years", ""), slug=via.get("slug")) if via else None,
                         fs=p.get("fs"))
        p["page"] = slug
        p["pageDoc"] = doc
    return out


def life_facts(r, vr):
    """Fakta pro osu a mapu stránky příbuzného: narození a úmrtí z Velké rodiny, fakta z vlastního záznamu SIDE,
    sňatky ze stromu (MARR rodiny i bez manžela ve stromu, „× datum místo“; rok, který už má × v SIDE, se nezdvojí)
    a pobyty a povolání s datem (RESI „bydliště, místo (rok)“, OCCU „povolání, místo (rok)“, EMIG „vystěhování,
    místo (rok)“; starší export má jen
    první pobyt resi)."""
    out = [f"{sym} {d} {pl}".strip() for sym, (d, pl) in (("*", r["birth"]), ("†", r["death"])) if d or pl]
    out += r.get("facts", [])
    vp = vr["people"].get(r["id"], {})
    have = {y for f in out if f.startswith("×") for y in re.findall(r"\d{4}", f)[:1]}
    for marr, place in [(s.get("marr"), s.get("place")) for s in vp.get("spouses", [])] + list(map(tuple, vp.get("snatky", []))):
        y = re.findall(r"\d{4}", marr or "")
        if y and y[0] not in have:
            have.add(y[0])
            out.append(f"× {marr} {place or ''}".strip())
    pobyty = vp.get("pobyty") or [["RESI", ""] + list((vp.get("resi") or ["", ""])[:2])]
    for tag, text, d, pl in pobyty:
        y = re.findall(r"\d{4}", d or "")
        what = (text or "").strip() if tag == "OCCU" else "vystěhování" if tag == "EMIG" else "bydliště"
        if y and (pl or what != "bydliště"):
            out.append(f"{what}, {pl} ({y[0]})" if pl else f"{what} ({y[0]})")
    return out


def link_cards(families, vr):
    """Karty v blocích Celá rodina dostanou page, když má osoba vlastní stránku příbuzného."""
    P = vr["people"]
    for ff in families:
        if not ff:
            continue
        for g in ("parents", "siblings", "spouses", "children"):
            for c in ff.get(g, []):
                if P.get(c["id"], {}).get("page"):
                    c["page"] = P[c["id"]]["page"]
                    if P[c["id"]].get("pageDoc"):
                        c["doc"] = True                    # doložená stránka → štítek „matrika“
