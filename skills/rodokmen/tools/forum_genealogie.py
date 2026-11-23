#!/usr/bin/env python3
"""Genealogické fórum (https://genealogie.taby.cz, phpBB 3.0) bez prohlížeče: hledání, čtení témat, návrhy dotazů.

  python -I -X utf8 tools/forum_genealogie.py navrhy
  python -I -X utf8 tools/forum_genealogie.py hledej "Příjmení*" [--nazvy] [--rubrika 16] [--autor X]
  python -I -X utf8 tools/forum_genealogie.py tema <číslo nebo odkaz>
  python -I -X utf8 tools/forum_genealogie.py hledano

Hledání a čtení veřejných témat jde bez účtu přes tools/slusne.py. Výsledky zůstanou v pracovni/forum/.
Příspěvek ber jako stopu k původnímu prameni. Návrhy hledání a deník se čtou pouze z místních souborů.
"""
import argparse, hashlib, html as _html, json, math, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://genealogie.taby.cz/"
SLOZKA = os.path.join(ROOT, "pracovni", "forum")

_A = re.compile(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.S)


# ---------------------------------------------------------------- čištění textu

def _bez_znacek(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", s))


def html_na_text(s):
    """Obsah příspěvku phpBB → čitelný text (řádky, citace „> “, celé adresy odkazů)."""
    def odkaz(m):
        href = _html.unescape(m.group(1))
        if href.startswith("./"):
            href = BASE + href[2:]
        text = _bez_znacek(m.group(2)).strip()
        if not text or text.startswith(("http", "www.")) or text == href:
            return href
        return f"{text} ({href})"
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = _A.sub(odkaz, s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    while True:   # citace od nejvnitřnější: „> Kdo napsal: text“
        m = re.search(r"<blockquote[^>]*>((?:(?!<blockquote).)*?)</blockquote>", s, re.S)
        if not m:
            break
        vnitrek = re.sub(r"</cite>", " ", m.group(1))
        radky = [r.strip() for r in _bez_znacek(vnitrek).split("\n") if r.strip()]
        s = s[:m.start()] + "\n" + "\n".join("> " + r for r in radky) + "\n" + s[m.end():]
    s = _bez_znacek(s).replace("\xa0", " ")
    radky = [re.sub(r"[ \t]+", " ", r).strip() for r in s.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(radky)).strip()


def _param(url, jmeno):
    m = re.search(r"[?&;]" + jmeno + r"=(\d+)", _html.unescape(url))
    return int(m.group(1)) if m else None


def _dalsi_start(html, start, script, topic=None):
    """Pro pokračování použij jen stránkování tohoto vyhledávání nebo tématu."""
    offsets = []
    for m in _A.finditer(html):
        url = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, _html.unescape(m[1])))
        if url.hostname != "genealogie.taby.cz" or url.path != "/" + script:
            continue
        dalsi = _param(url.query and "?" + url.query, "start")
        if dalsi is not None and dalsi > start and (topic is None or _param("?" + url.query, "t") == topic):
            offsets.append(dalsi)
    return min(offsets, default=None)


# ---------------------------------------------------------------- rozbor stránek

def je_flood(html):
    """Fórum hostovi hledání odmítlo (limit četnosti hledání)."""
    return bool(re.search(r"nemůžete\s+(?:teď\s+)?(?:vy)?hledat|nemůžete\s+vyhledávat|tak\s+brzy", html, re.I))


def parse_hledani(html, start=0):
    m = re.search(r"Vyhledáváním bylo nalezeno\s+([\d\s]+)\s+výsledk", html)
    celkem = int(re.sub(r"\D", "", m.group(1))) if m else 0
    vysledky = []
    for blok in re.split(r'<div class="search post', html)[1:]:
        h3 = re.search(r"<h3>\s*<a href=\"([^\"]+)\">(.*?)</a>", blok, re.S)
        if not h3:
            continue
        obsah = re.search(r'<div class="content">(.*?)</div>', blok, re.S)
        autor = re.search(r'<dt class="author">.*?<a [^>]*>(.*?)</a>', blok, re.S)
        dd = re.findall(r"<dd>(.*?)</dd>", blok, re.S)
        rubrika = re.search(r'Fórum:\s*<a [^>]*>(.*?)</a>', blok)
        tema = re.search(r'Téma:\s*<a href="([^"]+)">(.*?)</a>', blok)
        odpovedi = re.search(r"Odpovědi:\s*<strong>(\d+)</strong>", blok)
        p = _param(h3.group(1), "p")
        vysledky.append(dict(
            prispevek=p,
            tema=_param(tema.group(1), "t") if tema else _param(h3.group(1), "t"),
            predmet=_bez_znacek(h3.group(2)).strip(),
            nazev_tematu=_bez_znacek(tema.group(2)).strip() if tema else "",
            rubrika=_bez_znacek(rubrika.group(1)).strip() if rubrika else "",
            autor=_bez_znacek(autor.group(1)).strip() if autor else "",
            datum=_bez_znacek(dd[0]).strip() if dd else "",
            odpovedi=int(odpovedi.group(1)) if odpovedi else None,
            ukazka=re.sub(r"\s+", " ", html_na_text(obsah.group(1))) if obsah else "",
            odkaz=f"{BASE}viewtopic.php?p={p}#p{p}",
        ))
    if vysledky and not celkem:
        celkem = len(vysledky)
    return dict(celkem=celkem, vysledky=vysledky, dalsi=_dalsi_start(html, start, "search.php") if celkem else None)


def parse_tema(html, start=0, topic=None):
    nazev = re.search(r'<h2><a href="[^"]*">(.*?)</a></h2>', html, re.S)
    strana = re.search(r"Stránka <strong>(\d+)</strong> z <strong>(\d+)</strong>", html)
    prispevky = []
    for m in re.finditer(r'<div id="p(\d+)" class="post ', html):
        konec = html.find('<div id="p', m.end())
        blok = html[m.start():konec if konec > 0 else len(html)]
        h3 = re.search(r"<h3[^>]*>\s*<a [^>]*>(.*?)</a>", blok, re.S)
        autor = re.search(r'<p class="author">.*?od <strong>(?:<a [^>]*>)?(.*?)(?:</a>)?</strong>\s*&raquo;\s*([^<]*)',
                          blok, re.S)
        obsah = re.search(r'<div class="content">(.*?)</div>\s*(?:<div class="notice"|<div id="sig|</div>\s*<dl)',
                          blok, re.S)
        prispevky.append(dict(
            id=int(m.group(1)),
            predmet=_bez_znacek(h3.group(1)).strip() if h3 else "",
            autor=_bez_znacek(autor.group(1)).strip() if autor else "",
            datum=_html.unescape(autor.group(2)).strip() if autor else "",
            text=html_na_text(obsah.group(1)) if obsah else "",
        ))
    if nazev:
        nazev_s = _bez_znacek(nazev.group(1)).strip()
    else:
        nazev_s = prispevky[0]["predmet"] if prispevky else ""
    akt, z = (int(strana.group(1)), int(strana.group(2))) if strana else (1, 1)
    return dict(nazev=nazev_s, strana=(akt, z), prispevky=prispevky,
                dalsi=_dalsi_start(html, start, "viewtopic.php", topic) if akt < z else None)


# ---------------------------------------------------------------- návrhy z dat

def koren(slovo):
    """Kmen pro hledání s hvězdičkou: Opelka → Opelk*, Straková → Strak*, Dunovský → Dunovsk*."""
    s = slovo.strip()
    for konc in ("ová", "á", "ý", "a", "é"):
        if s.endswith(konc) and len(s) - len(konc) >= 4:
            s = s[: -len(konc)]
            break
    return s + "*"


def _prijmeni(n):
    n = re.sub(r"\([^)]*\)", "", n or "").strip()
    casti = n.split()
    return casti[-1] if len(casti) >= 2 else None


def _zijici(o):
    from datetime import date
    from web_pohledy import is_living
    if is_living(o, date.today().year):
        return True
    return not (re.search(r"\d{4}", o.get("y") or "") or any(f.startswith("†") for f in o.get("f", [])))


def navrhy(P, mista):
    """Příjmení předků (bez žijících) a obce z jejich faktů, seřazené podle počtu předků."""
    rody = {}
    for k, o in P.items():
        if o.get("st") == "unk" or _zijici(o):
            continue
        pr = _prijmeni(o.get("n"))
        if not pr or pr.lower() in ("neuveden", "neznámý", "neznámá"):
            continue
        h = koren(pr)
        r = rody.setdefault(h, dict(hledat=h, podoby=set(), predku=0, nejblizsi=k))
        r["podoby"].add(pr)
        r["predku"] += 1
        r["nejblizsi"] = min(r["nejblizsi"], k)
    prijmeni = sorted(rody.values(), key=lambda r: (-r["predku"], r["nejblizsi"]))
    for r in prijmeni:
        r["podoby"] = sorted(r["podoby"])
        r["generace"] = int(math.log2(r["nejblizsi"]))
    historicke = {k: o for k, o in P.items() if o.get("st") != "unk" and not _zijici(o)}
    obce = []
    for obec, m in mista.items():
        vzor = re.compile(m.get("re") or re.escape(obec))
        kdo = [k for k, o in historicke.items() if vzor.search(" ".join(o.get("f") or []))]
        if kdo:
            obce.append(dict(obec=obec, hledat=koren(obec), predku=len(kdo), nejblizsi=min(kdo)))
    obce.sort(key=lambda r: (-r["predku"], r["nejblizsi"]))
    return dict(prijmeni=prijmeni, obce=obce)


def _nacti_data():
    from runpy import run_path
    ns = run_path(os.path.join(ROOT, "data", "osoby.py"))
    with open(os.path.join(ROOT, "data", "mista.json"), encoding="utf-8") as f:
        mista = json.load(f)
    return ns["P"], mista


# ---------------------------------------------------------------- síť

def _stahni(url):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import slusne  # noqa: F401 – brzda proti zablokování (společný limit dotazů)
    req = urllib.request.Request(url, headers={"User-Agent": slusne.UA, "Accept-Language": "cs"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _zapis(cesta, text):
    import zamek
    with zamek.zamceno(cesta):
        zamek.zapis_text(cesta, text)


def hledej(slova, nazvy=False, rubrika=None, autor=None, max_stran=1):
    vysledky, start, celkem = [], 0, 0
    for _ in range(max_stran):
        q = [("keywords", slova), ("terms", "all"), ("sf", "titleonly" if nazvy else "all"), ("sr", "posts"),
             ("sk", "t"), ("sd", "d")]
        if rubrika:
            q.append(("fid[]", str(rubrika)))
        if autor:
            q.append(("author", autor))
        if start:
            q.append(("start", str(start)))
        html = _stahni(BASE + "search.php?" + urllib.parse.urlencode(q))
        if je_flood(html):
            raise ValueError("Fórum teď hledání odmítlo (limit pro hosty). Vyčkej několik minut.")
        h = parse_hledani(html, start)
        if not h["vysledky"] and not re.search(r"žádné (?:výsledky|vhodné výsledky|příspěvky|téma)|0\s+výsledk", html, re.I):
            raise ValueError("Výsledky fóra se nepodařilo přečíst. Zkontroluj stránku v prohlížeči.")
        celkem = max(celkem, h["celkem"])
        vysledky += h["vysledky"]
        if h["dalsi"] is None:
            break
        start = h["dalsi"]
    return dict(dotaz=slova, nazvy=nazvy, rubrika=rubrika, autor=autor, celkem=celkem,
                kdy=time.strftime("%Y-%m-%d %H:%M"), vysledky=vysledky)


def tema(t, max_stran=1):
    stranky, start, nazev = [], 0, ""
    for _ in range(max_stran):
        html = _stahni(f"{BASE}viewtopic.php?t={t}" + (f"&start={start}" if start else ""))
        d = parse_tema(html, start, t)
        if not d["prispevky"]:
            raise ValueError("Příspěvky se nepodařilo přečíst. Otevři téma v prohlížeči.")
        nazev = nazev or d["nazev"]
        stranky += d["prispevky"]
        if d["dalsi"] is None:
            break
        start = d["dalsi"]
    return dict(tema=t, nazev=nazev, prispevky=stranky, celkem_stran=d["strana"][1])


def tema_md(d):
    out = [f"# {d['nazev']}", "", f"Téma {d['tema']}: {BASE}viewtopic.php?t={d['tema']}",
           f"Staženo {time.strftime('%Y-%m-%d')}, příspěvků {len(d['prispevky'])}.", ""]
    for p in d["prispevky"]:
        out += [f"## {p['autor']} – {p['datum']} (p{p['id']}: {BASE}viewtopic.php?p={p['id']}#p{p['id']})", "",
                p["text"], ""]
    return "\n".join(out)


# ---------------------------------------------------------------- příkazy

def _cmd_hledej(a):
    volby = [a.slova, a.nazvy, a.rubrika, a.autor, a.max_stran]
    klic = hashlib.sha256(json.dumps(volby, ensure_ascii=False).encode()).hexdigest()
    cesta = os.path.join(SLOZKA, "hledani", klic + ".json")
    if os.path.exists(cesta) and not a.znovu:
        with open(cesta, encoding="utf-8") as f:
            d = json.load(f)
        print(f"(už hledáno {d['kdy']}, beru z disku; --znovu hledá znovu)")
    else:
        d = hledej(a.slova, a.nazvy, a.rubrika, a.autor, a.max_stran)
        os.makedirs(os.path.dirname(cesta), exist_ok=True)
        _zapis(cesta, json.dumps(d, ensure_ascii=False, indent=1) + "\n")
        import zamek
        denik = os.path.join(SLOZKA, "hledano.tsv")
        with zamek.zamceno(denik):
            with open(denik, "a", encoding="utf-8", newline="\n") as f:
                slova = re.sub(r"[\t\r\n]+", " ", a.slova)
                autor = re.sub(r"[\t\r\n]+", " ", a.autor or "")
                f.write(f"{d['kdy']}\t{slova}\t{'nazvy' if a.nazvy else 'vse'}\t{a.rubrika or ''}\t"
                        f"{autor}\t{d['celkem']}\t{len(d['vysledky'])}\n")
    print(f"„{d['dotaz']}“: nalezeno {d['celkem']}, načteno {len(d['vysledky'])} → {os.path.relpath(cesta, ROOT)}")
    for v in d["vysledky"]:
        print(f"- t={v['tema']} p={v['prispevek']} [{v['rubrika']}] {v['nazev_tematu']} | {v['autor']}, "
              f"{v['datum']}\n    {v['ukazka'][:300]}")


def _cmd_tema(a):
    t = _param(a.tema, "t") if not a.tema.isdigit() else int(a.tema)
    if not t:
        raise ValueError("Zadej kladné číslo tématu nebo adresu s t=…")
    cesta = os.path.join(SLOZKA, "temata", f"{t}-{a.max_stran}.md")
    if os.path.exists(cesta) and not a.znovu:
        print(f"(už staženo: {os.path.relpath(cesta, ROOT)}; --znovu stáhne znovu)")
        return
    d = tema(t, a.max_stran)
    os.makedirs(os.path.dirname(cesta), exist_ok=True)
    _zapis(cesta, tema_md(d))
    print(f"{d['nazev']}: {len(d['prispevky'])} příspěvků → {os.path.relpath(cesta, ROOT)}")
    if d["celkem_stran"] > a.max_stran:
        print(f"Téma má {d['celkem_stran']} stran. Další přečti ve fóru.")


def _cmd_navrhy(a):
    n = navrhy(*_nacti_data())
    print("Příjmení (hledat | podoby | předků | nejbližší generace):")
    for r in n["prijmeni"][: a.kolik]:
        print(f"  {r['hledat']:<16} {', '.join(r['podoby']):<40} {r['predku']:>3}  gen. {r['generace']}")
    print("Obce (hledat | obec | předků):")
    for r in n["obce"][: a.kolik]:
        print(f"  {r['hledat']:<16} {r['obec']:<40} {r['predku']:>3}")


def _cmd_hledano(a):
    p = os.path.join(SLOZKA, "hledano.tsv")
    print(open(p, encoding="utf-8").read() if os.path.exists(p) else "(zatím nic)")


def main(argv=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hledej", help="hledat ve fóru (hvězdička = libovolná koncovka)")
    h.add_argument("slova")
    h.add_argument("--nazvy", action="store_true", help="jen v názvech témat")
    h.add_argument("--rubrika", type=int, help="číslo rubriky (f=…)")
    h.add_argument("--autor")
    h.add_argument("--znovu", action="store_true")
    h.add_argument("--max-stran", type=int, choices=range(1, 11), default=1, help="nejvýše tolik stran, výchozí 1")
    h.set_defaults(f=_cmd_hledej)
    t = sub.add_parser("tema", help="přečíst veřejné téma do pracovni/forum/temata/")
    t.add_argument("tema", help="číslo tématu nebo adresa")
    t.add_argument("--znovu", action="store_true")
    t.add_argument("--max-stran", type=int, choices=range(1, 11), default=1, help="nejvýše tolik stran, výchozí 1")
    t.set_defaults(f=_cmd_tema)
    n = sub.add_parser("navrhy", help="co hledat: příjmení a obce z data/osoby.py")
    n.add_argument("--kolik", type=int, default=40)
    n.set_defaults(f=_cmd_navrhy)
    s = sub.add_parser("hledano", help="deník dotazů")
    s.set_defaults(f=_cmd_hledano)
    a = ap.parse_args(argv)
    if a.cmd == "hledej" and not a.slova.strip():
        ap.error("Zadej neprázdný dotaz.")
    try:
        a.f(a)
    except (ValueError, OSError) as e:
        ap.exit(2, f"Chyba: {e}\n")


if __name__ == "__main__":
    main()
