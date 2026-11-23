# Rodokmen – skill pro Claude Code

![Rodokmen z matrik a rodinný web – vějíř předků, mapa a zajímavosti](docs/banner.jpg)

Claude vás provede tvorbou rodokmenu **od rodinných vzpomínek přes digitalizované matriky až k hezkému rodinnému webu**
s vějířem předků, mapou, příběhem rodu a výřezy původních zápisů s přepisem a překladem.
Je určený pro lidi, kteří genealogii nikdy nedělali a neprogramují – technickou práci dělá Claude, vy dodáváte
znalost rodiny a rozhodujete.

Vznikl při skutečném hledání předků jedné rodiny.

Autorem původního skillu je Jindřich Šaršon ([sarsonj@gmail.com](mailto:sarsonj@gmail.com), [GitHub](https://github.com/sarsonj)).

**Aktuální verze odnože je 0.10.2 (srovnána s původním skillem 23. 11. 2026).** Obsahuje [přehled úkolů pro výzkum](skills/rodokmen/reference/vyzkum.md),
pomůcky pro Matriculu, Kramerius 7, Bádáme.cz a genealogické fórum,
[synchronizaci s FamilySearch](skills/rodokmen/reference/fs-sync.md) a [odkazy na předvyplněné e-maily](skills/rodokmen/reference/zadosti.md).
Postup najdete v části [Instalace](#instalace) a přehled změn v [CHANGELOG.md](CHANGELOG.md).

Pro Rakousko použijte [Matriculu](skills/rodokmen/reference/portaly.md#matricula)
na matriky a jejich rejstříky a [ANNO](skills/rodokmen/reference/portaly.md#noviny-a-ročenky) na noviny a vojenské seznamy ztrát.

> **Než začnete**
>
> Tento skill **nenahrazuje genealoga** ani zkušeného badatele. Je to pomůcka, která umí rychle projít hodně matrik.
> Umělá inteligence ale dělá chyby: špatně přečte jméno, splete si dva Jany ze stejné vsi nebo spojí rodiny, které
> k sobě nepatří. Skill se tomu snaží bránit – u každého údaje je zdroj a výřez původního zápisu, údaje se navzájem
> kontrolují a nejisté věci jsou označené. Za správnost rodokmenu ale ručíte vy. Používáte ho na vlastní odpovědnost.
>
> Projekt vznikl i jako **test toho, kam současná AI dosáhne**. Chtěl jsem zkusit úkol, který je opravdu těžký:
> kurrent, latina, zkratky farářů, stejná jména a dlouhé řetězce závěrů. Výsledky mě překvapily, ale nejsou to
> výsledky profesionála.
>
> Kdo potřebuje rodokmen, na který se dá spolehnout (dědictví, publikace, sporné případy), nebo se zasekne na místě,
> kam matriky nestačí, ať se obrátí na genealoga. Začít můžete u
> [České genealogické a heraldické společnosti](https://www.genealogie.cz) (Praha a pobočky po Čechách) nebo
> u [Moravské genealogické a heraldické společnosti](https://www.mghs.cz) (Brno). Obě pořádají kurzy a přednášky
> a mají knihovnu. Rodokmen ze skillu, kde je u každého údaje zdroj a snímek, může genealogovi posloužit jako dobrý
> podklad.

**Přečetla AI něco špatně, něco nefunguje nebo jste narazili na jiný problém?**
Postup najdete v části [Zpětná vazba](#zpětná-vazba-a-vaše-zkušenosti).

## Jak vypadá web
Ukázkový web s vymyšlenou rodinou Novákových (260 předků v 11 generacích) má na úvodní stránce příběh rodu, zajímavosti,
mapu, kde předci žili, osm rodů a vějíř předků. Další stránky: rodokmen po rodinách, karty osob, výřezy zápisů
s přepisem a překladem, „Co hledáme“ a deník hledání. **[Podívejte se na celou úvodní stránku ukázky →](docs/ukazka-web.png)**

## Co budete potřebovat
- **Claude Code** (aplikace pro Mac/Windows nebo příkazová řádka) a placené předplatné Claude. Rodokmen je
  dlouhá práce – počítejte s několika večery a s tím, že spotřebuje dost kreditů. Nejlevnější tarif **Pro bude
  nejspíš málo** (stačí na vyzkoušení), na celý rodokmen počítejte aspoň s nejnižším tarifem **Max**.
  Po dokončení můžete předplatné zase snížit nebo zrušit, web i data vám zůstanou.
- **Počítač s macOS nebo Windows** (obojí vyzkoušeno; Windows 11 s Pythonem z python.org a Git Bashem).
  Linux by měl fungovat, ale vyzkoušený není.
- Programy **Python 3, Node.js, ImageMagick a git**. Nemusíte je instalovat předem – Claude zkontroluje, co chybí,
  a pomůže s instalací (na Macu přes [Homebrew](https://brew.sh), na Windows přes winget).
- Pro střední a jižní Čechy a Moravu (SOA Praha, SOA Třeboň, MZA Brno, ZA Opava) **prohlížeč pro Clauda** –
  doplněk Playwright.
  Tyto archivy stahovací nástroje nepouštějí, Claude proto čte matriky přímo v jejich prohlížeči. Instalace
  v Claude Code: `/plugin install playwright@claude-plugins-official`, pak restart. Bez něj můžete Claudovi
  posílat snímky obrazovky sami.
- Volitelně účet na [Cloudflare](https://www.cloudflare.com) (zdarma, založíte ho při zveřejnění), pokud chcete web zveřejnit pro rodinu.

## S jakými modely to vzniklo
AI se vyvíjí rychle a za pár měsíců může skill dávat lepší, nebo jen jiné výsledky. Proto je tu uvedeno, s čím byl
vyzkoušený.

- **Stav původního skillu k 16. 11. 2026 (verze 0.10.2):** Claude Code s hlavním modelem **Claude Opus 5.5**. Pomocníci, kteří hledají
  a čtou matriky jako první, běží na **Claude Sonnet 5.5**. Každý jejich nález pak hlavní model ověřuje na snímku.
- Nástroje odnože pro výzkum vyžadují jen Python.
- Vyzkoušeno na několika skutečných rodokmenech (největší má 243 předků v 11 generacích a 192 matričních zápisů).
  Výsledek se porovnával s větví, kterou jsme léta dělali ručně.

S jiným nebo slabším modelem počítejte s víc chybami ve čtení starého písma.

## Instalace

### Varianta A – jako plugin (doporučeno)
V Claude Code napište:
```
/plugin marketplace add pavelzbornik/rodokmen-skill
/plugin install rodokmen@rodokmen-skill
```
Pak Claude Code restartujte (do běžící relace se nový plugin nenačte). Pokud už máte přidaný původní
marketplace `sarsonj/rodokmen-skill`, v `/plugin` ho nejprve odeberte nebo zvolte ruční instalaci níže.
**Aktualizace.** Claude Code u pluginů od jiných autorů než Anthropic nové verze sám nehlídá. Máte dvě možnosti:
- **Automaticky (doporučuji):** jednou v `/plugin` na kartě **Marketplaces** vyberte `rodokmen-skill` a zapněte
  automatické aktualizace (Enable auto-update). Nová verze se pak stáhne při spuštění Claude Code.
- **Ručně:** v terminálu (nebo v Claude Code s `!` na začátku)
  ```
  claude plugin marketplace update rodokmen-skill
  claude plugin update rodokmen@rodokmen-skill
  ```

Po aktualizaci Claude Code restartujte. Rozpracovaný projekt pak Claude při další práci sám nabídne aktualizovat
na novou verzi (vaše data i vlastní úpravy webu a nástrojů zůstanou, změny šablony se do nich sloučí).
Při přechodu z původního skillu stejné verze Claude nabídne aktualizaci, pokud v projektu chybí nástroje odnože.

### Varianta B – ručně
Stáhněte repozitář (zelené tlačítko **Code → Download ZIP** na GitHubu, nebo `git clone`) a zkopírujte složku
`skills/rodokmen` do `~/.claude/skills/` (na Windows `C:\Users\<jméno>\.claude\skills\`). Výsledek:
`~/.claude/skills/rodokmen/SKILL.md`.

Pak Claude Code restartujte.

## První spuštění
1. Spusťte Claude Code (klidně v domovské složce) a napište třeba:
   > Chci udělat rodokmen své rodiny.

   nebo přímo `/rodokmen`.
2. Claude zkontroluje programy, založí složku projektu (např. `~/Rodokmen`) a začne se ptát na rodinu.
   Připravte si, co víte o rodičích, prarodičích a pradědečcích, a rodinné dokumenty (rodné a oddací listy, parte,
   fotky, kroniky) – stačí vyfotit mobilem.
3. **Příště otevírejte Claude Code přímo ve složce projektu** (`cd ~/Rodokmen && claude`, nebo v aplikaci
   vyberte tuto složku). Claude si přečte, kde jste skončili, a naváže.

Chcete nejdřív vidět, jak web vypadá? Řekněte: *„Ukaž mi ukázkový web.“* Claude založí ukázkový projekt
s vymyšlenou rodinou a spustí náhled.

## Jak to probíhá
| Fáze | Co děláte vy | Co dělá Claude |
|---|---|---|
| 0. Příprava | potvrdíte instalaci programů | založí projekt |
| 1. Rozhovor | vyprávíte, dodáte dokumenty, zeptáte se příbuzných | zapisuje, čte dokumenty, navrhuje otázky |
| 2. Matriky | rozhodujete sporná místa | hledá svazky, stahuje a čte zápisy, dělá výřezy, přepisy a překlady, vede deník hledání |
| 3. Příběhy | doplníte rodinné historky, schválíte texty | průběžně sbírá zajímavosti, napíše „Příběh <vašeho rodu>“ |
| 4. Web | díváte se a říkáte, co upravit | staví web a ukazuje náhled |
| 5. Zveřejnění | založíte účet na Cloudflare (nebo Netlify), schválíte obsah | nasadí web s přihlášením rodinnou otázkou |

Matriky jsou online jen do určitého data: narození starší než 100 let, sňatky 75 a úmrtí 30 let.
O mladší údaje se žádá na matričním úřadě. Claude vám řekne, kdy to je potřeba.

## Co je v repozitáři
```
skills/rodokmen/
  SKILL.md           průvodce pro Clauda (fáze, pravidla)
  reference/         podrobné návody: příprava počítače, čtení matrik, portály archivů, metodika
                     (spojování záznamů, mrtvé body, prameny mimo ČR), formát dat, web, soukromí
  tools/             nástroje v Pythonu (ARON, výřezy, rámečky, mapa, kontrola dat, export do webu, vějíř)
  template/          šablona projektu: prázdná data, ukázková rodina, web (Astro)
.claude-plugin/      instalace jako plugin
```

## Co umí a co ne
- **Hotové nástroje** (bez prohlížeče) mají: východní Čechy (SOA Zámrsk, ARON), západní Čechy (SOA Plzeň,
  Porta fontium) a Prahu (AHMP a policejní přihlášky 1850–1914). Pro severní Čechy (SOA Litoměřice) stahuje
  snímky nástrojem, knihu ale najde přes prohlížeč. Pro Rakousko je postup přes Matriculu.
- **Jen přes prohlížeč:** střední Čechy (SOA Praha, eBadatelna – i urbáře a gruntovní knihy), jižní Čechy
  (SOA Třeboň) a Morava (MZA Brno) – tyto archivy od listopadu 2026 stahovací nástroje odmítají, Claude proto
  zápis přiblíží v jejich prohlížeči a uloží snímek obrazovky. Opava taky přes prohlížeč. Funguje to, ale je to
  pomalejší.
- U úředníků, vojáků a lékařů hledá i v **dobových novinách** (ANNO, Kramerius) – kariéra, vyznamenání, parte.
- Umí načíst **rodinný strom z MyHeritage** a dalších služeb (export GEDCOM, z MyHeritage i zálohu stromu z programu
  Family Tree Builder) a udělat z něj plán hledání.
- Průběžně sbírá **zajímavosti** (svatby na poslední chvíli, rod sto let v jednom domě…) a s vámi napíše
  **Příběh vašeho rodu** – hlavní článek webu.
- Claude čte staré písmo dobře, ale ne bezchybně. Proto ke každému zápisu ukládá výřez s vyznačeným místem,
  aby se to dalo zkontrolovat, a nejistá místa označuje otazníkem.
- Placené služby (MyHeritage, Ancestry) Claude hromadně neprochází – vede to k zablokování účtu.

## Soukromí
Projekt obsahuje osobní údaje vaší rodiny. Zůstává na vašem počítači. Web je chráněný rodinnou otázkou
a není indexovaný vyhledávači; bez nastavené otázky ho nástroj nenasadí. Je to lehká ochrana proti náhodným
návštěvníkům, ne trezor: kdo zná odpověď, vidí všechno, co na web dáte. Claude má pokyn psát o žijících lidech
jen jméno a rok narození a před zveřejněním s vámi projít, co o nich web říká – kód to ale nevynucuje,
rozhodnutí je na vás.
Pokud projekt chcete zálohovat na GitHub, použijte **soukromý** repozitář.

## Zpětná vazba a vaše zkušenosti
Děkuji všem, kdo mi poslali připomínky – jen verze 0.5.0 zapracovala přes čtyřicet podnětů od šesti lidí (podpora
Windows a staršího ImageMagicku, postupy pro MZA Brno a ZA Opava, bezpečná úprava dat a další). Každou připomínku čtu
a průběžně zapracovávám – ne každou hned a ne každou doslova, aby skill zůstal jednoduchý pro všechny.

Chyby v synchronizaci s FamilySearch, přehledu úkolů, e-mailových konceptech a dalších nástrojích odnože předejte
jejímu správci, pokud na něj máte kontakt. Jinak si je ponechte v poznámkách projektu.
Chyby, které se projeví také v původním skillu, můžete zapsat do [jeho GitHub Issues](https://github.com/sarsonj/rodokmen-skill/issues/new).
Popište, co se stalo. U chyby ve čtení můžete přidat odkaz na veřejný snímek z archivu. Rodinné údaje do hlášení nedávejte.

Nemusíte nic sepisovat sami. Claude si během práce zapisuje do `poznamky_pro_skill.md` (v projektu), co by šlo zlepšit:
chyby, nové archivy, postupy a nápady, bez údajů o vaší rodině. Občas vám je nabídne k odeslání. Nic se neposílá samo:
když budete chtít, zkopírujte je do zprávy.

## Bezpečnost
Skill obsahuje návody pro Clauda, skripty v Pythonu a JavaScript pro přihlášený prohlížeč FamilySearch.
Kód si můžete před instalací prohlédnout v repozitáři.
- **Žádný automaticky spouštěný kód.** Plugin nemá hooky ani MCP servery. Skripty spouští jen Claude, když je
  při práci potřebuje, a Claude Code se vás na ně zeptá.
  Jediná výjimka je volitelný **hlídač sítě**. Claude se na něj zeptá při zakládání projektu a bez vašeho souhlasu
  se nezapne. Je to malý skript v projektu (`tools/hlidac_site.py`, hook v `.claude/settings.json` projektu). Před
  každým příkazem zkontroluje, jestli nejde na web archivu mimo brzdu, a takový příkaz zamítne. Sám nic nestahuje
  ani nikam neposílá. Vypnete ho příkazem `novy_projekt.py <projekt> --bez-hlidace`.
- **Brzda proti zablokování archivem.** Archivy blokují IP adresu po sérii rychlých dotazů. Nástroje proto mají
  společný limit pro každý web (`tools/slusne.py`) a po varování archivu se na 30 minut zastaví. Projekt má
  v `.claude/settings.json` zakázané přímé `curl` a `wget`, stahuje se jen přes brzdu.
- **Kam skripty sahají:** zapisují do složky projektu rodokmenu (stažené snímky, mezivýsledky, web).
  Výjimkou jsou dočasné soubory systému, stav brzdy (pár malých souborů v `~/.cache/rodokmen_slusne`, na Windows
  v `%LOCALAPPDATA%`), mezipaměť stažených snímků (`~/.cache/rodokmen_snimky`, nejvýš 5 GB, lze kdykoli smazat),
  npm při instalaci webu a přihlášení nástroje pro nasazení (Cloudflare, Netlify, CapRover), pokud web zveřejňujete. Mimo
  projekt nic nemažou ani nepřepisují – kromě nejdéle nepoužitých snímků ve vlastní mezipaměti nad limitem.
- **Na které servery chodí:** archivní portály (ARON SOA Zámrsk, SOA Třeboň, SOA Plzeň – Porta fontium, SOA Praha –
  eBadatelna, AHMP, Národní archiv, SOA Litoměřice, Matricula), noviny (ANNO, Kramerius), OpenStreetMap (mapa
  a souřadnice obcí) a při instalaci webu registr npm. Nové nástroje čtou veřejné stránky Bádáme.cz a fóra
  genealogie.taby.cz a veřejné API Krameria Jihočeské vědecké knihovny. Hledání na fóru a v knihovně předává zadaný dotaz.
  Na Cloudflare nebo Netlify jde obsah webu jen při zveřejnění. Kontrola verze čte číslo verze z GitHubu.
- **FamilySearch a pošta.** Synchronizace používá váš přihlášený prohlížeč. Před zápisem do veřejného stromu Claude
  ukáže plán a počká na výslovný souhlas. Koncept se předá Gmailu, Outlooku, Seznamu nebo místní poště při otevření
  příslušného odkazu. Odesíláte ho sami.
- **Doporučení:** nechte v Claude Code zapnuté schvalování příkazů, aspoň dokud si nezvyknete, co Claude dělá.
  Obecně instalujte skilly a pluginy jen od lidí, kterým věříte. Skill nikdo předem nekontroluje a Claude se
  jeho návodem řídí.

## Licence
Skill je pod licencí [MIT](LICENSE): smíte ho volně používat, upravovat a šířit dál, jen zachovejte uvedení autora (Jindřich Šaršon).
