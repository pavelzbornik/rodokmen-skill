#!/usr/bin/env python3
"""Rozcestník Bádáme.cz (https://badame.cz, WordPress) bez prohlížeče: seznam odkazů ze stránky a co z nich už známe.

Bádáme.cz je katalog odkazů pro genealogy (databáze, matriky, mapy, slovníky, hřbitovy…). Každá stránka výpisu má
asi 10 položek: název, odkaz na cizí web a kategorii. Popisy tam nejsou, co zdroj umí, se zjišťuje na jeho webu.

  python -I -X utf8 tools/badame.py stranka 1 [--znovu]   -> pracovni/badame/stranka_8.json + tabulka
  python -I -X utf8 tools/badame.py stranka 8 --json      -> totéž jako JSON na výstup
  python -I -X utf8 tools/badame.py vse [--od 1 --max-stran 20]           -> všechny strany, jen odkazy mimo katalog

U každé položky nástroj vypíše, kde v projektu (CLAUDE.md, docs/, deník, archivní dotazy, nástroje)
se už objevuje její web. Do volitelného `docs/zdroje_badame.md` patří celé adresy posouzených zdrojů.

Šetrnost: síť jde přes brzdu tools/slusne.py; stažená stránka zůstane v pracovni/badame/ a bez --znovu se
znovu nestahuje.
"""
import argparse, glob, hashlib, html as _html, json, os, re, sys, urllib.parse, urllib.request
from urllib.error import HTTPError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://badame.cz/"
SLOZKA = os.path.join(ROOT, "pracovni", "badame")
KATALOG = "docs/zdroje_badame.md"

KATEGORIE = {
    "databaze": "Databáze",
    "digitalizovane-matriky": "Digitalizované matriky",
    "digitalni-knihovny": "Digitální knihovny",
    "fora-a-weby": "Fóra a weby",
    "genealogicky-software": "Genealogický software",
    "hrbitovy": "Hřbitovy",
    "osobni-stranky": "Osobní stránky",
    "slovniky": "Slovníky",
    "stare-fotografie": "Staré fotografie",
    "stare-mapy": "Staré mapy",
    "stare-pismo": "Staré písmo",
    "zide": "Židé",
}

_ARTICLE = re.compile(r'<article\b([^>]*)>(.*?)</article>', re.S)
_TITUL = re.compile(r'<h\d[^>]*class="[^"]*preview-title[^"]*"[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def kategorie_nazev(slug):
    return KATEGORIE.get(slug, slug)


def cisty_odkaz(url):
    """Odkaz bez značky „#new_tab“, kterou si web přidává pro otevření v nové záložce."""
    url = _html.unescape(url).strip()
    url = url[:-len("#new_tab")] if url.endswith("#new_tab") else url
    if not url or url.startswith("#"):
        return ""
    try:
        url = urllib.parse.urljoin(BASE, url)
        p = urllib.parse.urlsplit(url)
        if p.scheme in ("http", "https") and p.hostname and not p.username and not p.password:
            return url
    except ValueError:
        pass
    return ""


def host(url):
    h = (urllib.parse.urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def parse_stranka(text, n=None):
    """HTML stránky výpisu → {"polozky": [{post, nazev, odkaz, host, kategorie}], "predchozi", "dalsi"}.

    `n` = číslo stránky, když ho titulek neuvádí (úvodní stránka https://badame.cz/ je strana 1)."""
    polozky = []
    for m in _ARTICLE.finditer(text):
        atributy, telo = m.group(1), m.group(2)
        t = _TITUL.search(telo)
        if not t:
            continue
        odkaz = cisty_odkaz(t.group(1))
        if not odkaz:
            continue
        post = re.search(r'\bpost-(\d+)\b', atributy)
        polozky.append({
            "post": int(post.group(1)) if post else None,
            "nazev": re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", t.group(2)))).strip(),
            "odkaz": odkaz,
            "host": host(odkaz),
            "kategorie": re.findall(r'\bcategory-([a-z0-9-]+)', atributy),
            # Položka bez cizího odkazu vede na příspěvek přímo na Bádáme; cíl je až v jeho textu (nebo nikde).
            "vnitrni": host(odkaz) == "badame.cz",
        })
    cisla = sorted({int(c) for c in re.findall(r'href="(?:https?://(?:www\.)?badame\.cz)?/page/(\d+)/', text)})
    aktualni = re.search(r'&#8211; (\d+)\. stránka', text)
    n = int(aktualni.group(1)) if aktualni else n
    predchozi = max((c for c in cisla if n is None or c < n), default=None) if n else None
    dalsi = min((c for c in cisla if n is not None and c > n), default=None)
    if n == 2 and predchozi is None:
        predchozi = 1   # první stránka je https://badame.cz/ bez /page/1/
    return {"strana": n, "polozky": polozky, "predchozi": predchozi, "dalsi": dalsi}


def odkazy_prispevku(text):
    """Cizí odkazy z textu příspěvku na Bádáme (`entry-content`), bez odkazů na Bádáme samotné."""
    m = re.search(r'<div class="entry-content">(.*?)</div>', text, re.S)
    if not m:
        return []
    odkazy = [cisty_odkaz(h) for h in re.findall(r'<a\b[^>]*href="([^"]+)"', m.group(1))]
    return list(dict.fromkeys(o for o in odkazy if o and host(o) != "badame.cz"))


def zhodnoceno(polozka, katalog_text):
    """V katalogu hledej celou adresu zdroje, včetně cesty."""
    url = re.escape(polozka["odkaz"].rstrip("/"))
    return bool(re.search(r"(?<![\w/])" + url + r"/?(?=$|[\s|>)\]])", katalog_text))


def _vzor(h):
    return re.compile(r"(?<![\w.-])(?:www\.)?" + re.escape(h) + r"(?![\w-]|\.[a-z0-9])", re.I)


def zname(polozky, texty):
    """Pro každý web (host) seznam souborů z `texty` ({cesta: text}), kde se objevuje."""
    vysledek = {}
    for p in polozky:
        h = p["host"]
        if h in vysledek:
            continue
        if p.get("vnitrni") or h == "badame.cz":
            vysledek[h] = []   # adresu Bádáme zmiňuje každý katalog, o cíli příspěvku nic neříká
            continue
        v = _vzor(h)
        vysledek[h] = sorted(cesta for cesta, text in texty.items() if v.search(text))
    return vysledek


# ---------------------------------------------------------------- projekt

def texty_projektu():
    cesty = ["CLAUDE.md", "data/STAV.md", "data/research_log.md", "data/archivni_dotazy.md",
             "data/zadosti.md", "poznamky_pro_skill.md", KATALOG]
    cesty += [os.path.relpath(p, ROOT).replace(os.sep, "/") for p in glob.glob(os.path.join(ROOT, "docs", "**", "*.md"),
                                                                                 recursive=True)]
    for pripona in ("py", "js", "sh"):
        cesty += [f"tools/{os.path.basename(p)}" for p in glob.glob(os.path.join(ROOT, "tools", f"*.{pripona}"))]
    texty = {}
    for c in dict.fromkeys(cesty):
        p = os.path.join(ROOT, c)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                texty[c] = f.read()
    return texty


class PresmerovaniBadame(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        dst = urllib.parse.urlsplit(newurl)
        if dst.scheme != "https" or dst.netloc.lower() not in ("badame.cz", "www.badame.cz"):
            raise HTTPError(req.full_url, code, "Přesměrování mimo Bádáme.cz", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _stahni(url):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import slusne  # noqa: F401 – brzda proti zablokování (společný limit dotazů)
    req = urllib.request.Request(url, headers={"User-Agent": slusne.UA, "Accept-Language": "cs"})
    opener = urllib.request.build_opener(PresmerovaniBadame())
    with opener.open(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _zapis(cesta, text):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import zamek
    with zamek.zamceno(cesta):
        zamek.zapis_text(cesta, text)


def adresa_stranky(n):
    return BASE if n == 1 else f"{BASE}page/{n}/"


def _prispevek(url, znovu=False):
    """Text příspěvku na Bádáme (uložený v pracovni/badame/prispevky/, stáhne se jen jednou)."""
    slozka = os.path.join(SLOZKA, "prispevky")
    os.makedirs(slozka, exist_ok=True)
    casti = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(("https", "badame.cz", casti.path, casti.query, ""))
    cesta = os.path.join(slozka, hashlib.sha256(url.encode()).hexdigest() + ".html")
    if znovu or not os.path.isfile(cesta):
        _zapis(cesta, _stahni(url))
    with open(cesta, encoding="utf-8") as f:
        return f.read()


def stranka(n, znovu=False):
    if n < 1:
        raise ValueError("Číslo stránky musí být kladné.")
    os.makedirs(SLOZKA, exist_ok=True)
    cesta = os.path.join(SLOZKA, f"stranka_{n}.html")
    if znovu or not os.path.isfile(cesta):
        text = _stahni(adresa_stranky(n))
        if not parse_stranka(text, n=n)["polozky"]:
            raise ValueError(f"Na straně {n} se nepodařilo najít položky rozcestníku.")
        _zapis(cesta, text)
    with open(cesta, encoding="utf-8") as f:
        s = parse_stranka(f.read(), n=n)
    if not s["polozky"]:
        raise ValueError(f"Na uložené straně {n} nejsou položky. Zkus --znovu.")
    s["adresa"] = adresa_stranky(n)
    for p in s["polozky"]:
        if p["vnitrni"]:
            p["odkazy_prispevku"] = odkazy_prispevku(_prispevek(p["odkaz"], znovu))
    texty = texty_projektu()
    z = zname(s["polozky"], texty)
    for p in s["polozky"]:
        p["kategorie_nazvy"] = [kategorie_nazev(k) for k in p["kategorie"]]
        p["zname_v"] = z[p["host"]]
        p["zhodnoceno"] = zhodnoceno(p, texty.get(KATALOG, ""))
    _zapis(os.path.join(SLOZKA, f"stranka_{n}.json"), json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    return s


def vse(od=1, znovu=False, nejvys=20):
    """Projde strany od `od`, dokud stránka uvádí další. Souhrn do pracovni/badame/vse.json."""
    if od < 1 or nejvys < 1:
        raise ValueError("Počáteční stránka a počet stran musí být kladné.")
    strany, n = [], od
    while n and len(strany) < nejvys:
        s = stranka(n, znovu=znovu)
        strany.append(s)
        n = s["dalsi"] if s["dalsi"] and s["dalsi"] > n else None
    polozky = [dict(p, strana=s["strana"]) for s in strany for p in s["polozky"]]
    souhrn = {"strany": [s["strana"] for s in strany], "polozky": polozky, "dalsi": n}
    _zapis(os.path.join(SLOZKA, "vse.json"), json.dumps(souhrn, ensure_ascii=False, indent=2) + "\n")
    return souhrn


def _tabulka(s):
    radky = [f"Bádáme.cz, strana {s['strana']} ({s['adresa']}), {len(s['polozky'])} odkazů; "
             f"předchozí {s['predchozi']}, další {s['dalsi']}"]
    for p in s["polozky"]:
        stav = "ZHODNOCENO" if p["zhodnoceno"] else ("známe: " + ", ".join(p["zname_v"]) if p["zname_v"] else "NOVÉ")
        if p["vnitrni"] and not p["zhodnoceno"]:
            cil = ", ".join(p["odkazy_prispevku"]) or "bez odkazu, cíl dohledat podle názvu"
            stav = f"PŘÍSPĚVEK NA BÁDÁME ({cil})"
        radky.append(f"- {p['nazev']} [{', '.join(p['kategorie_nazvy'])}] {p['odkaz']}\n    {stav}")
    return "\n".join(radky)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("stranka", help="odkazy ze stránky výpisu a co z nich už známe")
    a.add_argument("n", type=int)
    a.add_argument("--znovu", action="store_true", help="stáhnout znovu, i když stránka už je v pracovni/badame/")
    a.add_argument("--json", action="store_true")
    b = sub.add_parser("vse", help="všechny strany za sebou; vypíše jen odkazy, které ještě nejsou v katalogu")
    b.add_argument("--od", type=int, default=1)
    b.add_argument("--max-stran", type=int, default=20, help="nejvýš tolik stran v jednom běhu (výchozí 20)")
    b.add_argument("--znovu", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "vse":
        v = vse(od=args.od, znovu=args.znovu, nejvys=args.max_stran)
        zbyva = [p for p in v["polozky"] if not p["zhodnoceno"]]
        print(f"Strany {v['strany'][0]}–{v['strany'][-1]}: {len(v['polozky'])} odkazů, "
              f"nezhodnoceno {len(zbyva)} (pracovni/badame/vse.json)")
        if v["dalsi"]:
            print(f"Další strana: {v['dalsi']} (pokračuj přes --od).")
        for p in zbyva:
            print(f"- s. {p['strana']}: {p['nazev']} [{', '.join(p['kategorie_nazvy'])}] {p['odkaz']}"
                  + (f"  (známe: {', '.join(p['zname_v'])})" if p["zname_v"] else ""))
        return
    s = stranka(args.n, znovu=args.znovu)
    print(json.dumps(s, ensure_ascii=False, indent=2) if args.json else _tabulka(s))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as e:
        sys.exit(f"Chyba: {e}")
