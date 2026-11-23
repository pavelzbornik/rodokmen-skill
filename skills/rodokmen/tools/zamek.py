"""Zámek pro souběžné přepisy celého data/*.json (mista, fary, svazky).

Při souběhu zápisů drží `uprav_json` zámek <soubor>.lock, stejný jako `zapis.py`,
od čtení po přepsání a zapisuje přes dočasný soubor s číslem procesu.

    zamek.uprav_json(cesta, lambda d: d.update({klic: zaznam}))

Nástroj, který mezi načtením a zápisem dlouho čeká na síť, si soubor načte bez zámku a změny přenese až
při zápisu: `uprav_json(cesta, prenes_zmeny(puvodni, nove))` – jen přidané, změněné a smazané klíče.
"""
import contextlib, copy, json, os, time

CEKAT_S = 120   # zámek starší než 2 minuty zůstal po spadlém procesu


@contextlib.contextmanager
def zamceno(path):
    zamek = path + ".lock"
    for _ in range(CEKAT_S * 10):
        try:
            os.close(os.open(zamek, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(zamek) > CEKAT_S:
                    os.remove(zamek)
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    else:
        raise SystemExit(f"{zamek} drží jiný zápis přes 2 minuty – zkontroluj, jestli neběží, a zámek smaž.")
    try:
        yield
    finally:
        os.remove(zamek)


def zapis_text(path, text):
    """Celý soubor naráz přes vlastní dočasný soubor (bez zámku; volá se pod `zamceno`)."""
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    for pokus in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:   # OneDrive soubor na chvíli zamkne, když ho synchronizuje
            if pokus == 9:
                raise
            time.sleep(0.5)


def vychozi(d):
    return json.dumps(d, ensure_ascii=False, indent=1)


def uprav_json(path, zmena, serializuj=vychozi):
    """Načte path pod zámkem, zavolá zmena(d) (mění d na místě) a soubor přepíše. Vrací upravený slovník."""
    with zamceno(path):
        d = json.load(open(path, encoding="utf-8-sig")) if os.path.exists(path) else {}
        zmena(d)
        zapis_text(path, serializuj(d))
        return d


def prenes_zmeny(puvodni, nove):
    """Změna pro uprav_json: na disk přenese jen klíče přidané, změněné nebo smazané proti `puvodni`."""
    puvodni = copy.deepcopy(puvodni)

    def zmena(d):
        for k, v in nove.items():
            if k not in puvodni or puvodni[k] != v:
                d[k] = v
        for k in puvodni:
            if k not in nove:
                d.pop(k, None)
    return zmena
