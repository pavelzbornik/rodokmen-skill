#!/usr/bin/env python3
"""Kramerius 7: hledání, metadata a OCR přes veřejné API digitálních knihoven.

  python -I -X utf8 tools/kramerius7.py hledej "Příjmení" [--od 1800 --do 1920] [--jen-volne]
  python -I -X utf8 tools/kramerius7.py hledej "Název obce" --model map
  python -I -X utf8 tools/kramerius7.py titul "Název obce" [--radku 30]
  python -I -X utf8 tools/kramerius7.py polozka uuid:...
  python -I -X utf8 tools/kramerius7.py ocr uuid:...

Každý příkaz přijímá --knihovna jvk a --json (i před podpříkazem).
Více slov hledá jako frázi. Bez --model hledá hledej v OCR stran; jiný model než
page hledá v názvu. titul hledá v názvech všech modelů. Roky zahrnují i dokumenty,
jejichž datace zasahuje do zadaného období. Úryvek zvýrazní shodu [závorkami].
OCR se stahuje jen pro stranu s accessibility:public, licence sama nestačí.
Síť jde přes společnou brzdu tools/slusne.py, bez opakování chybného dotazu.
Klient pro NK v5 zůstává v kramerius.py.
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

KNIHOVNY = {"jvk": "https://kramerius.cbvk.cz"}
POLE = ("pid,model,title.search,root.title,root.pid,date.str,accessibility,"
        "licenses,licenses_of_ancestors")


# ---------------------------------------------------------------- rozbor odpovědí bez sítě

def _text(hodnota):
    if isinstance(hodnota, list):
        hodnota = hodnota[0] if hodnota else ""
    return str(hodnota) if hodnota is not None else ""


def parse_polozka(d, knihovna="jvk"):
    """Záznam ze search převede na metadata s českými klíči."""
    if not isinstance(d, dict) or not isinstance(d.get("pid"), str) or not d["pid"]:
        raise ValueError("Neplatná odpověď API: položka nemá pid.")
    licence = []
    # Licence potomků (contains_licenses) se nevztahují na tuto položku.
    for pole in ("licenses", "licenses_of_ancestors"):
        hodnoty = d.get(pole) or []
        if isinstance(hodnoty, str):
            hodnoty = [hodnoty]
        for hodnota in hodnoty:
            if hodnota not in licence:
                licence.append(hodnota)
    return dict(pid=d["pid"], nazev=_text(d.get("title.search")),
                rok=_text(d.get("date.str")), model=_text(d.get("model")),
                dostupnost=_text(d.get("accessibility")), licence=licence,
                koren_nazev=_text(d.get("root.title")), koren_pid=_text(d.get("root.pid")),
                odkaz=KNIHOVNY[knihovna] + "/uuid/" + urllib.parse.quote(d["pid"], safe=":"))


def _uryvek(text):
    text = re.sub(r"<strong>", "[", text, flags=re.I)
    text = re.sub(r"</strong>", "]", text, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_hledani(d, knihovna="jvk"):
    """Solr JSON včetně zvýraznění pod pid nebo složeným klíčem kořen!pid."""
    odpoved = d.get("response") if isinstance(d, dict) else None
    if (not isinstance(odpoved, dict) or not isinstance(odpoved.get("docs"), list)
            or not isinstance(odpoved.get("numFound"), int)):
        raise ValueError("Neplatná odpověď API: chybí výsledky hledání.")
    zvyrazneni = d.get("highlighting") or {}
    vysledky = []
    for zaznam in odpoved["docs"]:
        v = parse_polozka(zaznam, knihovna)
        hl = zvyrazneni.get(v["pid"]) or zvyrazneni.get(v["koren_pid"] + "!" + v["pid"]) or {}
        uryvky = hl.get("text_ocr") or []
        v["uryvek"] = (" | ".join(_uryvek(s) for s in uryvky)
                       if v["dostupnost"] == "public" else "")
        vysledky.append(v)
    return dict(celkem=odpoved["numFound"], vysledky=vysledky)


# ---------------------------------------------------------------- dotazy a síť

def _citace(slova):
    return '"' + slova.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parametry_hledani(slova, model=None, od=None, do=None, radku=30, jen_volne=False, nazvy=False):
    """Sestaví Solr dotaz s výslovným polem a nezávislými filtry."""
    if not slova.strip():
        raise ValueError("Zadej neprázdný dotaz.")
    if not 1 <= radku <= 100:
        raise ValueError("Počet řádků musí být od 1 do 100.")
    if any(rok is not None and rok < 1 for rok in (od, do)):
        raise ValueError("Rok musí být kladný.")
    if od is not None and do is not None and od > do:
        raise ValueError("Počáteční rok nesmí být větší než koncový.")
    if model is not None and not re.fullmatch(r"[a-z][a-z0-9_-]*", model):
        raise ValueError("Neplatný model dokumentu.")
    ocr = not nazvy and (model is None or model == "page")
    pole = "text_ocr" if ocr else "title.search"
    p = dict(q=pole + ":" + _citace(slova.strip()), rows=radku, fl=POLE)
    filtry = []
    if model or not nazvy:
        filtry.append("model:" + (model or "page"))
    if jen_volne:
        filtry.append("accessibility:public")
    # Překryv datace dokumentu s obdobím, stejně jako v klientu JVK.
    if do is not None:
        filtry.append(f"date_range_start.year:[* TO {do}]")
    if od is not None:
        filtry.append(f"date_range_end.year:[{od} TO *]")
    if filtry:
        p["fq"] = " AND ".join(filtry)
    if ocr:
        # JVK odmítá hl.fragsize > 120 kódem HTTP 400.
        p.update({"hl": "true", "hl.fl": "text_ocr", "hl.method": "original",
                  "hl.snippets": 1, "hl.fragsize": 120,
                  "hl.simple.pre": "<strong>", "hl.simple.post": "</strong>"})
    return p


def _api(knihovna):
    if knihovna not in KNIHOVNY:
        raise ValueError("Neznámá knihovna: " + knihovna)
    return KNIHOVNY[knihovna] + "/search/api/client/v7.0"


def _stahni(url):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import slusne  # noqa: F401 – společná brzda proti zablokování archivem
    req = urllib.request.Request(url, headers={"User-Agent": slusne.UA, "Accept-Language": "cs"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def _hledani(p, knihovna):
    url = _api(knihovna) + "/search?" + urllib.parse.urlencode(p)
    try:
        d = json.loads(_stahni(url))
    except json.JSONDecodeError as e:
        raise ValueError("Neplatná odpověď API: nelze přečíst JSON.") from e
    return parse_hledani(d, knihovna)


def hledej(slova, knihovna="jvk", **volby):
    return _hledani(parametry_hledani(slova, **volby), knihovna)


def polozka(pid, knihovna="jvk"):
    """Metadata se v K7 čtou ze search, samotné /items/<pid> u JVK vrací 405."""
    pid = pid.strip()
    if not re.fullmatch(r"uuid:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", pid):
        raise ValueError("Zadej platný identifikátor uuid:.")
    h = _hledani(dict(q="pid:" + _citace(pid), rows=1, fl=POLE), knihovna)
    for v in h["vysledky"]:
        if v["pid"] == pid:
            return v
    raise ValueError("Položka nenalezena: " + pid)


def ocr(pid, knihovna="jvk"):
    d = polozka(pid, knihovna)
    if d["dostupnost"] != "public":
        raise ValueError("OCR se čte jen u výslovně veřejné položky (accessibility:public). "
                         "Prohlížeč knihovny: " + d["odkaz"])
    if d["model"] != "page":
        raise ValueError("OCR lze číst jen u jednotlivé strany (model page).")
    pid = d["pid"]
    url = _api(knihovna) + "/items/" + urllib.parse.quote(pid, safe="") + "/ocr/text"
    text = _stahni(url).lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return dict(pid=pid, text=text, odkaz=d["odkaz"])


# ---------------------------------------------------------------- příkazy a výpis

def _dostupnost(v):
    return {"public": "veřejná", "private": "neveřejná"}.get(v, v or "nezjištěná")


def _vypis_polozku(v):
    print(f"Název: {v['nazev'] or '(neuveden)'}")
    print(f"Rok / datace: {v['rok'] or '(neuvedena)'} | Model: {v['model']}")
    print(f"PID: {v['pid']}")
    print(f"Dostupnost: {_dostupnost(v['dostupnost'])} | Licence: {', '.join(v['licence']) or '(neuvedeny)'}")
    print(f"Kořen: {v['koren_nazev']} | {v['koren_pid']}")
    print(v["odkaz"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--knihovna", choices=KNIHOVNY, default="jvk", help="digitální knihovna (výchozí jvk)")
    ap.add_argument("--json", action="store_true", help="výstup jako JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, popis in (("hledej", "hledat v OCR stran, u jiných modelů v názvu"),
                       ("titul", "hledat v názvech všech modelů"),
                       ("polozka", "metadata položky"), ("ocr", "OCR veřejné strany")):
        p = sub.add_parser(cmd, help=popis)
        p.add_argument("--knihovna", choices=KNIHOVNY, default=argparse.SUPPRESS, help="digitální knihovna")
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="výstup jako JSON")
        if cmd in ("hledej", "titul"):
            p.add_argument("slova", help="slovo nebo fráze")
            p.add_argument("--od", type=int, help="od roku včetně")
            p.add_argument("--do", type=int, help="do roku včetně")
            p.add_argument("--model", help="např. page, map, monograph, periodical")
            p.add_argument("--radku", type=int, default=30, help="počet výsledků (výchozí 30)")
            p.add_argument("--jen-volne", action="store_true", help="jen accessibility:public")
        else:
            p.add_argument("pid", help="identifikátor včetně uuid:")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("hledej", "titul"):
            d = hledej(a.slova, a.knihovna, model=a.model, od=a.od, do=a.do, radku=a.radku,
                       jen_volne=a.jen_volne, nazvy=a.cmd == "titul")
        elif a.cmd == "polozka":
            d = polozka(a.pid, a.knihovna)
        else:
            d = ocr(a.pid, a.knihovna)
    except urllib.error.HTTPError as e:
        print(f"Chyba: knihovna vrátila HTTP {e.code}.", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"Chyba: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    elif a.cmd in ("hledej", "titul"):
        print(f"Nalezeno {d['celkem']}, vypsáno {len(d['vysledky'])}.")
        for v in d["vysledky"]:
            print(f"- {v['rok'] or '?'} | {v['koren_nazev'] or v['nazev']} | {v['model']} | {v['pid']}")
            if v["nazev"] and v["nazev"] != v["koren_nazev"]:
                print("    Název / strana: " + v["nazev"])
            print(f"    {_dostupnost(v['dostupnost'])} | Licence: {', '.join(v['licence']) or '(neuvedeny)'}")
            if v["uryvek"]:
                print("    " + v["uryvek"])
    elif a.cmd == "polozka":
        _vypis_polozku(d)
    else:
        print(d["text"], end="" if d["text"].endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
