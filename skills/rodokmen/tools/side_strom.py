"""Sourozenci a děti předků ze SIDE ve stromu Velké rodiny.

Stránka předka (rámečky „Děti“ a „Sourozenci“), stránky příbuzných, větve i synchronizace FamilySearch berou osoby
ze stromu, ne ze SIDE v osoby.py. `pridej` proto při načtení stromu (velka_rodina.load_tree) doplní do rodiny předka
každého sourozence nebo dítě, které tam ještě není. Bere jen vlastní záznamy se zápisem (r), s rokem v názvu
(„Anna Nováková (* 1892)“) a s textem, který vztah říká přímo („Sestra Jana …“, „Starší bratr Josefa (č. 16) …“). Osoba dostane
stálé ID @IS<k>-<jméno>-<rok>@, do souborů se nic nezapisuje. Když se k ní najde manžel nebo děti, přesune se do
data/doplnky_rodiny.ged se stejným ID. Funkce `chybi` na to upozorní.
"""
import copy
import re
import unicodedata
from collections import deque

from pribuzni import first_key
from velka_rodina import year_of

# Jen vlastní sourozenec předka. „Syn / Dcera X a Y“ v SIDE jmenuje rodiče té osoby, ne předka k (sourozenci,
# synovci, bratranci), a nevlastní sourozenec patří do jiné rodiny (druhé manželství), proto se nezařazují.
SOUROZENEC = re.compile(r"^(?:(?:starší|mladší)\s+)?(sestra|bratr)\s+(\S+)", re.I)
# „(* 1892)“, „(1892)“, „(1820–1828)“; závorka bez roku před ním patří ke jménu („Katharina (Karolina) …“)
JMENO = re.compile(r"^(\S+)(?:[^(]|\((?!\*?\s*\d{4})[^)]*\))*\((?:\*\s*)?(\d{4})(?:\s*[–-]\s*\d{4})?\)")
DATUM = re.compile(r"^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\s*(.*)$")
MESICE = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def kekule(recs, root="@I1@"):
    """{Kekulého číslo: id osoby} po rodičích z FAMC, od kořene stromu."""
    out, seen, q = {}, set(), deque([(root, 1)])
    while q:
        i, k = q.popleft()
        if i in seen or i not in recs:
            continue
        seen.add(i)
        out[k] = i
        fam = next((recs[f] for f in recs[i].get("famc", []) if f in recs), None)
        if fam:
            for x, kk in ((fam.get("husb"), 2 * k), (fam.get("wife"), 2 * k + 1)):
                if x:
                    q.append((x[0], kk))
    return out


def jmena(d):
    """Všechna křestní jména osoby ve stromu jednotně („Maria Anna/Marianna“ → marie, anna, marianna)."""
    jmeno = d.get("name", "").split()
    slova = f"{d.get('givn', '')} {' '.join(jmeno[:-1] or jmeno)}".replace("/", " ").split()
    return {first_key(w) for w in slova}


def narozen(d):
    """Rok narození, u doplňku jen z křestního zápisu rok křtu (CHR)."""
    ev = d.get("ev", {})
    return year_of((ev.get("BIRT") or [""])[0]) or year_of((ev.get("CHR") or [""])[0])


def _slug(text):
    t = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _udalost(fakta, znak, rok=None):
    """[datum GEDCOM, místo] z faktu „* 12. 2. 1892 Heřmaň čp. 48“ (nebo „† …“); bez faktu jen rok, jinak None."""
    for f in fakta:
        f = f.strip()
        if f.startswith(znak):
            text = f[1:].strip()
            sporny = "(?)" in text.split(" ", 2)[1] if text.count(" ") >= 2 else False   # „7. (?) 3. 1820“
            m = DATUM.match(text.replace(" (?)", "", 1) if sporny else text)
            if m and 1 <= int(m.group(2)) <= 12:
                misto = re.sub(r"\s*\([^)]*\)$", "", m.group(4).strip())        # „Rynholec čp. 55 (7 let)“
                den = "" if sporny else f"{int(m.group(1))} "
                return [f"{den}{MESICE[int(m.group(2)) - 1]} {m.group(3)}", misto]
            y = year_of(f)
            if y:
                return [str(y), ""]
    return [str(rok), ""] if rok else None


def _prvni_pad(slovo):
    """Možné 1. pády jména ve 2. pádě nebo přivlastňovací podobě: Jana, Janův → Jan; Anny → Anna; Karla → Karel;
    Františka → František; Josefova → Josef."""
    w = _slug(slovo)
    tvary = {w}
    for konc, nahr in (("uv", ""), ("ova", ""), ("ovi", ""), ("ovo", ""), ("a", ""), ("y", "a"), ("e", "a"), ("i", "a"),
                       ("la", "el"), ("ka", "ek"), ("ce", "ec"), ("ny", "na")):
        if w.endswith(konc) and len(w) - len(konc) >= 2:
            tvary.add(w[: len(w) - len(konc)] + nahr)
    return {first_key(t) for t in tvary}


def _sourozenec(text, k, predek):
    """Pohlaví 'F' | 'M', když text začíná „Sestra / Bratr / Starší … / Mladší …“ a jmenuje předka: „(č. k)“
    hned u vztahu (před první čárkou) nebo jeho křestní jméno za vztahem („Sestra Vladislava“, „Bratr Janův“).
    „Sestra Marie, manželky Josefa (č. 2)“ je sestra Marie, ne Josefa. Jinak None."""
    m = SOUROZENEC.match(text.strip())
    if not m:
        return None
    hlava = re.split(r"[,;]", text.strip(), maxsplit=1)[0]
    jmena_predka = {first_key(w) for w in (predek.get("givn") or predek.get("name", "")).replace("/", " ").split()}
    if not (re.search(rf"\(č\.\s*{k}\)", hlava) or _prvni_pad(m.group(2)) & jmena_predka):
        return None
    return "F" if m.group(1).lower() == "sestra" else "M"


ZEMREL = re.compile(r"(?<![\w])(?:zemřel[ao]?|zemř\.|†)(?![\w])", re.I)   # ne „zemřelého otce“
# podmět jiné smrti ve stejné větě: „otec zemřel“, „manžel zemřel 1915“, „syn † 1920“, „zemřel jí otec“
JINY = re.compile(r"(?<![\w])(?:otec|matka|rodiče|manžel(?:ka)?|muž|žena|syn|dcera|bratr|sestra|děti|vnuk|vnučka|"
                  r"tchán|tchyně|kmotr|kmotra)(?![\w])", re.I)


def _zemrel_sam(text):
    """Text sourozence říká, že zemřel on sám: slovo o smrti ve větě (mezi , ; . :), kde podmětem není jiný člověk.
    Úvodní „Sestra Josefa (č. 2)“ se z první věty vynechá."""
    text = SOUROZENEC.sub("", text.strip(), count=1)
    return any(ZEMREL.search(v) and not JINY.search(v) for v in re.split(r"[,;.:](?!\d)", text))


def pridej(recs, side, root="@I1@"):
    """Doplní do `recs` (na místě) sourozence a děti předků ze SIDE, kteří v rodině chybí.
    Vrací (vytvořená ID, [(záznam SIDE, důvod)] pro záznamy, které zařadit nešlo)."""
    by_k = kekule(recs, root)
    vytvoreno, nezarazeno, pouzite = [], [], set()
    for s in sorted(side, key=lambda e: (str(e.get("k")), e.get("n", ""), e.get("t", ""), tuple(e.get("r", [])))):
        m = JMENO.match(s.get("n", ""))
        if not s.get("r") or not SOUROZENEC.match(s.get("t", "").strip()):
            continue
        anc = by_k.get(s.get("k"))
        if not anc:
            if m:
                nezarazeno.append((s, "předek ve stromu chybí"))
            continue
        pohlavi = _sourozenec(s.get("t", ""), s["k"], recs[anc])
        if not pohlavi:
            continue
        if not m:                                      # sourozenec předka podle textu, ale bez roku nejde spárovat
            nezarazeno.append((s, "v n chybí rok narození, např. „(* 1890)“"))
            continue
        fam = next((f for f in recs[anc].get("famc", []) if f in recs), None)
        if not fam:
            nezarazeno.append((s, "rodina předka ve stromu chybí"))
            continue
        jmeno, rok = first_key(m.group(1)), int(m.group(2))
        shoda = next((c for c in recs[fam].get("chil", []) if c in recs and c != anc and c not in pouzite
                      and jmeno in jmena(recs[c]) and (narozen(recs[c]) or -9) in (rok - 1, rok, rok + 1)), None)
        if shoda:
            pouzite.add(shoda)
            continue
        jmeno_cele = s["n"][:m.start(2)].rsplit("(", 1)[0].strip()
        base = f"@IS{s['k']}-{_slug(jmeno_cele)}-{rok}"
        i, n = base + "@", 2
        while i in recs:
            i, n = f"{base}-{n}@", n + 1
        ev = {"BIRT": _udalost(s.get("f", []), "*", rok)}
        smrt = _udalost(s.get("f", []), "†")
        if smrt:
            ev["DEAT"] = smrt
        elif any(f.strip().startswith("†") for f in s.get("f", [])) or _zemrel_sam(s.get("t", "")):
            ev["DEAT"] = ["", ""]                      # zemřel, den neznámý (strom ho pak nebere jako žijícího)
        slova = jmeno_cele.split()
        recs[i] = dict(tag="INDI", id=i, name=jmeno_cele, givn=" ".join(slova[:-1]) or jmeno_cele,
                       surn=slova[-1] if len(slova) > 1 else "", sex=pohlavi, ev=ev, famc=[fam], fams=[],
                       husb=[], wife=[], chil=[], zaz=list(s.get("r", [])), side=True)
        recs[fam]["chil"].append(i)
        pouzite.add(i)
        vytvoreno.append(i)
    return vytvoreno, nezarazeno


def chybi(side, recs, root="@I1@"):
    """Upozornění pro kontrola.py: záznamy, které `pridej` nezařadil, přestože předek ve stromu je, a osoby @IS…@,
    na které v doplňcích odkazuje manžel nebo rodina (potřebují stálý záznam v doplnky_rodiny.ged). Strom nemění."""
    work = copy.deepcopy(recs)
    _, nezarazeno = pridej(work, side, root)
    out = [f"boční příbuzný {s['n']} (k={s['k']}): do stromu ho nešlo zařadit ({d}) – oprav text v SIDE "
           f"nebo osobu přidej do data/doplnky_rodiny.ged" for s, d in nezarazeno if d != "předek ve stromu chybí"]
    for i, r in sorted(work.items()):
        if r.get("side") and (r.get("fams") or any(i in f.get("husb", []) + f.get("wife", [])
                                                   for f in work.values() if f.get("tag") == "FAM")):
            out.append(f"boční příbuzný {r['name']} (* {narozen(r)}) ({i}): v doplňcích na něj odkazuje manžel nebo rodina – přesuň "
                       f"osobu ze SIDE do data/doplnky_rodiny.ged se stejným ID {i}")
    return out
