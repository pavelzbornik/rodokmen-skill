#!/usr/bin/env python3
"""Najdi popisky snímků a rejstříky v uloženém zdrojovém HTML Matriculy."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit


def popisky(text):
    """Pole labels je v pořadí snímků. Prázdný popisek nesmí posunout číslování."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"labels"\s*:\s*(?=\[)', text):
        try:
            labels, _ = decoder.raw_decode(text, match.end())
        except ValueError:
            continue
        if labels and all(label is None or isinstance(label, str) for label in labels):
            return [label or "" for label in labels]
    raise ValueError("Chybí pole labels. Ulož zdrojové HTML stránky knihy.")


def strany(text, url, jen_rejstriky=False):
    adresa = urlsplit(url)
    if adresa.scheme != "https" or adresa.netloc.lower() != "data.matricula-online.eu" or not adresa.path.strip("/"):
        raise ValueError("Zadej HTTPS adresu knihy na data.matricula-online.eu.")
    for n, label in enumerate(popisky(text), 1):
        if jen_rejstriky and not re.search(r"index|register|rejstřík|abeced", label, re.I):
            continue
        yield n, label, urlunsplit(adresa._replace(query=f"pg={n}", fragment=""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path, help="uložené zdrojové HTML knihy")
    parser.add_argument("url", help="adresa téže knihy z prohlížeče")
    parser.add_argument("--rejstriky", action="store_true", help="vypiš jen snímky označené jako rejstřík")
    args = parser.parse_args(argv)
    try:
        text = args.html.read_text(encoding="utf-8-sig")
        for n, label, odkaz in strany(text, args.url, args.rejstriky):
            print(f"{n}\t{label}\t{odkaz}")
    except (ValueError, OSError) as e:
        parser.exit(2, f"Chyba: {e}\n")


if __name__ == "__main__":
    main()
