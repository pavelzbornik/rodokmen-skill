#!/usr/bin/env python3
"""Kontrola verze na začátku konverzace: nainstalovaný skill × projekt × hlavní větev odnože.
Použití: python3 -I <skill>/tools/verze.py [<složka projektu>]

GitHubu se ptá nejvýš jednou za 24 hodin (mezipaměť ~/.cache/rodokmen_verze_forku.json, Windows %LOCALAPPDATA%),
bez sítě nebo při chybě se ho prostě nezeptá. Poslední řádek začíná „→“ a klíčovým slovem pro Clauda:
  NOVA_VERZE_SKILLU   odnož má na GitHubu novější verzi než nainstalovaný skill – ať uživatel aktualizuje skill
                      (projekt se pak aktualizuje z nového skillu, ne z GitHubu)
  AKTUALIZUJ_PROJEKT  skill je novější než projekt nebo v projektu chybí nástroje odnože – nabídni novy_projekt.py
  PROJEKT_NOVEJSI     projekt vznikl novějším skillem než ten nainstalovaný (stará kopie skillu) – projekt neměnit
  SKILL_NEZJISTEN     spuštěno z kopie v projektu a nainstalovaný skill se nenašel – verze skillu neověřena
  AKTUALNI            vše sedí
Kopie v tools/ projektu najde nainstalovaný skill sama (registr pluginů Claude Code, ~/.claude/skills/rodokmen).
Kód je vždy 0 (kontrola nesmí zastavit práci).
"""
import glob, json, os, re, sys, time, urllib.request
if sys.argv[1:2] in (["-h"], ["--help"]):   # nápověda místo kontroly (jinak by „--help“ bral jako složku projektu)
    print(__doc__.strip())
    sys.exit(0)   # kód vždy 0, viz výše
if len(sys.argv) > 1 and (sys.argv[1].startswith("-") or not os.path.isdir(sys.argv[1])):
    print(f"verze.py: „{sys.argv[1]}“ není složka projektu – zadej cestu ke složce projektu (nebo nic).")
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "pavelzbornik/rodokmen-skill"
URL = os.environ.get("RODOKMEN_VERZE_URL", f"https://raw.githubusercontent.com/{REPO}/main/skills/rodokmen/VERZE")
CACHE = os.path.join(os.environ.get("RODOKMEN_CACHE") or os.environ.get("LOCALAPPDATA")
                     or os.path.join(os.path.expanduser("~"), ".cache"), "rodokmen_verze_forku.json")
DEN = 24 * 3600


def cislo(v):
    """„v0.10.0“ → (0, 10, 0); nesrozumitelná verze → None."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def cti(cesta):
    try:
        with open(cesta, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def github():
    """Verze odnože na GitHubu nebo None; nejvýš jeden úspěšný dotaz za 24 hodin."""
    try:
        with open(CACHE, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("url") == URL and time.time() - c.get("cas", 0) < DEN and cislo(c.get("verze")):
            return c["verze"]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "rodokmen-skill"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8").strip()
        # RODOKMEN_VERZE_URL může stále ukazovat na GitHub Releases API.
        verze = text if cislo(text) else json.loads(text).get("tag_name", "")
        verze = verze.lstrip("v")
    except Exception:
        return None
    if not cislo(verze):
        return None
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"cas": time.time(), "verze": verze, "url": URL}, f)
    except OSError:
        pass
    return verze


def nainstalovany(projekt_dir):
    """Kopie v tools/ projektu nemá vedle sebe VERZE – najde nainstalovaný skill: plugin z registru Claude Code
    (pro tento projekt, jinak pro uživatele), nebo ručně nakopírovaný ~/.claude/skills/rodokmen. Vrátí (verze, cesta)."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    projekt = os.path.realpath(projekt_dir) if projekt_dir else None
    try:
        with open(os.path.join(cfg, "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            zaznamy = json.load(f).get("plugins", {}).get("rodokmen@rodokmen-skill", [])
    except (OSError, ValueError, AttributeError):
        zaznamy = []
    poradi = []
    for z in zaznamy if isinstance(zaznamy, list) else []:
        pp = z.get("projectPath")
        if pp and projekt and os.path.realpath(pp) == projekt:
            poradi.insert(0, z)                      # instalace pro tento projekt má přednost
        elif z.get("scope") == "user":
            poradi.append(z)
    for z in poradi:
        cesta = os.path.join(z.get("installPath", ""), "skills", "rodokmen")
        verze = cti(os.path.join(cesta, "VERZE")) or z.get("version")
        if cislo(verze):
            return verze, cesta
    rucne = os.path.join(cfg, "skills", "rodokmen")
    verze = cti(os.path.join(rucne, "VERZE"))
    if cislo(verze):
        return verze, rucne
    return desktop()


def desktop():
    """Skill u účtu v aplikaci Claude desktop (Windows %LOCALAPPDATA%\\Claude-Data\\claude_…\\rpm\\…\\plugin_…\\
    skills\\rodokmen, obdobně na macOSu) – nejvyšší nalezená verze, jinak (None, None)."""
    zaklady = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Claude-Data"),
               os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Claude-Data")]
    nalez = []
    for z in zaklady:
        if not os.path.isdir(z):
            continue
        for vzor in ("*/rpm/plugin_*", "*/rpm/*/plugin_*", "*/rpm/*/*/plugin_*"):
            for d in glob.glob(os.path.join(z, vzor, "skills", "rodokmen")):
                v = cti(os.path.join(d, "VERZE"))
                if cislo(v):
                    nalez.append((cislo(v), v, d))
    if not nalez:
        return None, None
    _, v, d = max(nalez)
    return v, d


def chybi_nastroje_odnoze(projekt):
    if not os.path.isfile(os.path.join(projekt, "data", "STAV.md")):
        return False
    # Soubor ve staré šabloně mohl uživatel záměrně smazat. Instalátor ho v tom případě neobnoví.
    return any(not os.path.isfile(os.path.join(projekt, "tools", name))
               and not os.path.isfile(os.path.join(projekt, ".skill_sablona", "tools", name))
               for name in ("fs_sync.py", "mailto.py", "pokryti.py"))


def main():
    global SKILL
    skill = cti(os.path.join(SKILL, "VERZE"))
    if skill is None:   # spuštěno z kopie v tools/ projektu
        skill, nalezeny = nainstalovany(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(SKILL))
        if nalezeny:
            SKILL = nalezeny
    projekt_dir = sys.argv[1] if len(sys.argv) > 1 else None
    projekt = cti(os.path.join(projekt_dir, ".skill_verze")) if projekt_dir else None
    gh = github()

    print(f"Skill (nainstalovaný): {skill}")
    if projekt_dir:
        print(f"Projekt: {projekt or 'bez .skill_verze (starší než 0.4)'}")
    print(f"GitHub (verze odnože): {gh or 'nezjištěno (bez sítě nebo GitHub neodpověděl)'}")

    s, p, g = cislo(skill), cislo(projekt), cislo(gh)
    if g and s and g > s:
        if os.sep + "plugins" + os.sep in SKILL:   # nainstalovaný jako plugin (…/.claude/plugins/…)
            jak = ("jako plugin: `claude plugin marketplace update rodokmen-skill` a `claude plugin update\n"
                   "  rodokmen@rodokmen-skill`, pak restart Claude Code (natrvalo: v /plugin zapnout automatické aktualizace;\n"
                   "  když příkaz `claude` nejde spustit, stejné příkazy jdou v Claude Code přes /plugin)")
        else:                                       # nakopírovaný ručně (~/.claude/skills/rodokmen …)
            jak = (f"ručně nakopírovaný skill ({SKILL}): stáhnout novou verzi z https://github.com/{REPO}\n"
                   "  (Code → Download ZIP), složkou skills/rodokmen nahradit tu stávající a restartovat Claude")
        print(f"→ NOVA_VERZE_SKILLU: odnož má verzi {gh}, nainstalovaný skill je {skill}. Řekni to uživateli jednou větou a poraď,\n"
              f"  jak skill aktualizovat – {jak}. Projekt aktualizuj až z nového skillu.")
    elif projekt_dir and p and s and p > s:
        print(f"→ PROJEKT_NOVEJSI: projekt je z verze {projekt}, nainstalovaný skill je starší ({skill}). Projekt neaktualizuj\n"
              "  (vrátil bys ho ke starší verzi); ať uživatel aktualizuje skill (viz README, část Instalace).")
    elif projekt_dir and s and (not p or s > p or (s == p and chybi_nastroje_odnoze(projekt_dir))):
        duvod = f"skill {skill} je novější než projekt" if s != p else "v projektu chybí nástroje odnože"
        print(f"→ AKTUALIZUJ_PROJEKT: {duvod}. Nabídni aktualizaci projektu:\n"
              f"  python3 -I {os.path.join(SKILL, 'tools', 'novy_projekt.py')} <složka projektu>")
    elif not s:
        print("→ SKILL_NEZJISTEN: nainstalovaný skill jsem nenašel, verzi skillu neporovnávám. Spusť kontrolu ze složky\n"
              "  skillu: python3 -I SKILL_DIR/tools/verze.py <složka projektu>")
    else:
        print("→ AKTUALNI")


if __name__ == "__main__":
    main()
