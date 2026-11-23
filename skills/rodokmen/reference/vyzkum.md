# Přehled úkolů pro výzkum

Spusť příkazy v kořeni nainstalovaného projektu. Na Windows použij `python -I -X utf8`, na macOS `python3 -I -X utf8`.

## Místní rodokmen a FamilySearch

```sh
python -I -X utf8 tools/pokryti.py ukoly
python -I -X utf8 tools/pokryti.py ukoly --krok 3 --obec "<obec>" --max 20
python -I -X utf8 tools/pokryti.py ukoly --ged pracovni/strom.ged --koren "@I1@"
python -I -X utf8 tools/pokryti.py rozdil "<starší výstup JSON>"
```

Nástroj běží bez sítě. Vychází z `data/osoby.py`, `data/zaznamy.json` a mapování FamilySearch.
Když je v `data/web.json` nastavené `velka_rodina.ged`, načte i tento GEDCOM. Příkaz `--ged` umožní zadat soubor
přímo, bez změny nastavení. Kořen je z nastavení projektu nebo `@I1@`. Jiný zadej pomocí `--koren`. Pro porovnání
`rozdil` použij stejný strom a kořen jako u staršího výstupu.

Výstupy jsou v `pracovni/pokryti/`. Markdown shrne pokrytí a vypíše úkoly. Přepínače `--prijmeni`, `--obec`,
`--krok` a `--max` omezí tento seznam. JSON obsahuje celý přehled pro příští porovnání. Výstupy mohou obsahovat
rodinná data, proto je nech v `pracovni/`.

1. U osoby bez mapování prověř její totožnost na FamilySearch. Rozporná mapování zkontroluj ručně.
2. U mapované osoby zkontroluj připojené zdroje a případné nepřečtené shody. Použij
   [import snapshotu](fs-sync.md) a pak znovu spusť `ukoly`. Čtení z více importů se sčítá. Úspěšný dotaz
   bez výsledků se počítá jako přečtený. Volitelné kanály shod se sledují, když některý import obsahuje jejich čtení.
   Po sloučení osob se zohlední i čtení pod cílovým ID. Místní mapování se tím nepřepisuje.
3. Prověř sčítání, pokud známá událost nebo domácnost ukazuje, kde osoba mohla v daném roce žít. Nástroj používá
   roky 1869, 1880, 1890, 1900, 1910 a 1921 pro české země. Dostupnost ověř pro konkrétní obec a archiv.
   Mimo toto území můžeš návrhy vypnout pomocí `--bez-scitani`.
4. Jestli chybí zápis k narození, zkus křest. Nástroj ho navrhne u známého místa a roku narození, pokud je v
   místním `data/fary.json` ověřená fara. Soubor je volitelný. Pro tuto funkci stačí tvar
   `{"Název obce": {"fara": "Název fary"}}`.

Když u osoby zbývá více kroků, objeví se v několika oddílech. Každý návrh ověř v původním prameni.

## Rozcestník a genealogické fórum

Při čtení přes nástroje dodržuj podmínky portálu. Stažené stránky a příspěvky nech v `pracovni/`.

- `python -I -X utf8 tools/badame.py stranka 1` vypíše odkazy z [Bádáme.cz](https://badame.cz/) a uloží stránku
  a výsledky do `pracovni/badame/`. Další stranu zadej číslem. `vse --od N --max-stran 5` projde omezený počet
  stran a vypíše dosud nezhodnocené položky. `--znovu` obnoví stažené stránky.
- U zajímavého zdroje si poznamenej, jaké území, období a druhy dokladů pokrývá a jestli vyžaduje účet.
  Do volitelného `docs/zdroje_badame.md` zapiš celou adresu z rozcestníku. Podle ní nástroj pozná posouzenou položku,
  i když se zdroj přestěhoval. Odkazy z jiných webů nástroj uvádí ve výstupu.
- `python -I -X utf8 tools/forum_genealogie.py hledej "Příjmení*"` hledá ve veřejné části
  [genealogického fóra](https://genealogie.taby.cz/). Zkus jedno příjmení najednou. `--nazvy` omezí hledání na
  názvy témat, `--rubrika <číslo>` na jednu rubriku. `tema <číslo nebo odkaz>` uloží veřejné příspěvky do
  `pracovni/forum/temata/`. Oba příkazy čtou první stranu, `--max-stran N` dovolí načíst víc, nejvýš deset.
  Pokud fórum požádá o pauzu nebo zablokuje požadavek, skonči a pokračuj později.
- `navrhy` vypíše místní nápady na hledání podle historických osob a obcí, `hledano` zobrazí místní deník dotazů.
  Do hledání zadávej jen údaje, které můžeš předat veřejnému webu. Příspěvky jsou vodítka, která ověř na snímku.
  Případný dotaz posílá uživatel sám.

Pro rakouské prameny otevři [Matriculu a ANNO](portaly.md#matricula).
