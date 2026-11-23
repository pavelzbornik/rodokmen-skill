# Opakovaná synchronizace s FamilySearch

`tools/fs_sync.py` připravuje plán bez sítě. `tools/fs_prohlizec.js` čte a zapisuje v přihlášené záložce
FamilySearch pod účtem uživatele. Přihlašovací údaje zůstanou v prohlížeči.

## První porovnání

1. Založ nebo aktualizuj projekt příkazem `novy_projekt.py` z tohoto skillu. Pro první pokus najdi na
   FamilySearch jednoho zesnulého předka a ulož jeho ID do `data/familysearch.json`. Například
   `{"kekule": {"8": "AAAA-BBB"}, "ged": {}}` přiřadí ID předkovi č. 8. Nahraď číslo i ID vlastními údaji.
   GEDCOM je volitelný. Pokud ho máš, nastav v `data/web.json` položku
   `"velka_rodina": {"ged": "data/strom.ged", "koren": "@I1@"}`. Použij cestu a ID výchozí osoby ze
   svého GEDCOMu. Sekce `ged` v mapě přiřazuje FS ID podle klíčů jako `@I2@`.
2. Z kořene projektu spusť `python -I -X utf8 tools/fs_sync.py scope --max-persons 5 --no-myheritage`.
   Na macOS použij `python3`. Přepínač `--root <FS ID>` přidá předky z FamilySearch. Bez něj se použije
   FS ID místní osoby č. 1, pokud je známé.
3. Přihlas se na `https://www.familysearch.org/`. V téže záložce spusť celý soubor
   `tools/fs_prohlizec.js` pomocí nástroje pro spuštění JavaScriptu v prohlížeči nebo jako snippet
   v DevTools. V konzoli zavolej `fs.syncSnapshotNaPozadi(await fs.syncSoubor())` a vyber
   `pracovni/fs_sync/scope.json`. Průběh ukáže `fs.syncStav()`. Nech záložku otevřenou, dokud se
   nestáhne výsledek. Když ovládání prohlížeče překročí časový limit, nejdřív zkontroluj stav dávky.
4. Spusť `python -I -X utf8 tools/fs_sync.py snapshot-import <stažený soubor>` a potom
   `python -I -X utf8 tools/fs_sync.py diff`. Výsledek je v souborech `plan-*.md` a `plan-*.json`
   v `pracovni/fs_sync/`. Tím končí porovnání pouze pro čtení.
5. Přečti přehled v Markdownu i položky v JSON. Rozpory nahlas a shody ověř na původním snímku.
   V kopii plánu ponech jen zkontrolované položky se zdůvodněním a odkazem na snímek. Zachovej ID a
   nastav `reviewed: true`. Pokud přes `map` uložíš zkontrolovaná ID, spusť nové `diff`. Pro nově
   namapované osoby, které ještě nemají načtené údaje, pořiď nový snapshot.
6. Změny veřejného stromu proveď až po výslovném souhlasu uživatele s konkrétními položkami z aktuálního plánu.
   Při zadání jen pro čtení skonči u porovnání. Po `fs.syncApplyNaPozadi(plan)` ulož stažený výsledek přes
   `log <výsledek> --plan <schválený plán>`. Při přerušení se řiď stavem v souboru s výsledkem.
   Potvrzené změny ověř novým snapshotem a porovnáním.

Snapshoty, plány a výsledky nech v ignorované složce `pracovni/`. Po importu můžeš původní snapshot
odstranit ze Stažených souborů. Výsledek zápisu přesuň do `pracovni/`. GEDCOM, mapu ID a deník sdílej
pouze tam, kam patří rodinná data. Při HTTP 401, 403, 429 nebo 503 skript dávku zastaví.

## Příkazy

Z kořene projektu ve Windows používej `python -I -X utf8 tools/fs_sync.py` s dílčím příkazem:

| Příkaz | Výsledek |
|---|---|
| `scope [--root <FS ID>] [--max-persons 5] [--since <snapshot>] [--matches-max-age-days 7] [--myheritage-max-age-days 7] [--no-myheritage] [--no-neighbours] [--pace 2000]` | `pracovni/fs_sync/scope.json`. Bez omezení zahrne všechna známá FS ID nežijících osob. Tempo je 2 s mezi požadavky. |
| `snapshot-import <soubor>` | `snapshot-YYYY-MM-DD.json`, při jiném obsahu téhož dne nový soubor s otiskem. |
| `diff [snapshot] [--task-closeness N]` | `plan-YYYY-MM-DD.json` a `.md`, při jiném obsahu nový soubor s otiskem. Bez argumentu vezme poslední import. |
| `map <plán>` | Zkontrolovaná ID do `data/familysearch.json`, jen chybějící klíče, existující jiné ID odmítne. |
| `log <výsledek> --plan <plán>` | Potvrzené položky do `data/fs_sync_stav.json` a souhrn s odkazy do deníku. |

Browserové `fs.syncSnapshotNaPozadi(config)` a `fs.syncApplyNaPozadi(plan)` vrátí ihned stav spuštění.
`fs.syncStav()` vrací průběh bez citlivých přihlašovacích údajů. Výsledek se stáhne jako JSON i po chybě.
Objekt lze načíst výběrem souboru přes `await fs.syncSoubor()`, případně předat JSON přes evaluate.
Nenahrávej neschválený plán do zapisovací funkce.

Jednotlivý pomocný dotaz čti přes `await fs.syncCti('/platform/…')`, případně cestu `/service/…`.
Používá stejné přihlášení, tempo a trvalou stopku jako snapshot a apply. Za běhu dávky čtení odmítne.
Stejnou brzdu sdílejí také `fs.zdroje`, `fs.film`, `fs.stahni` a `fs.snimek`; blokace snímků zastaví i zápisy do stromu.
Pro přehled všech připojených zdrojů jedné osoby použij `await fs.zdroje([id], true)`. Snímek vybírej podle
ověřené stránky knihy. Pokud nástroj vrátí `NEVEŘEJNÝ SNÍMEK HTTP 403`, přeskoč omezený snímek a poznamenej
to do deníku. Při `STOP HTTP …` ukonči práci v záložce a postupuj podle pravidel pro přerušení níže.
Pro indexy pod `/platform/records/` požaduje GEDCOM X JSON, pro strom FS JSON a pro `/service/` běžný JSON.
Nevkládej vlastní `fetch` ani vlastní čtení cookie. Výsledek může obsahovat rodinné údaje a patří do `pracovni/`.

Výchozí snapshot znovu čte i všechny shody záznamů. `scope --since <snapshot>` převezme pouze shody
čtené před méně než sedmi dny; stáří změní `--matches-max-age-days N`. U převzatých shod zachová původní
čas `record_matches_read`, takže další běh neobnoví jejich stáří. Starší snapshot bez těchto časů používá
`captured_at`, ale pouze u osob se skutečně uloženými shodami. Osoby, vztahy a zdroje čte vždy znovu.

Snapshot čte u každé nežijící osoby také shody MyHeritage, které FamilySearch ukazuje na stránce osoby
(`GET /service/external/hints/myheritage/persons/<PID>/hints`, stejné přihlášení, tempo a stopka 401/403/429/503).
Do `myheritage` ukládá `totalHints`, `hintDetails`, `factorsDescription` a `link`, do `myheritage_read` čas čtení.
Odpověď 204 nebo 404 znamená 0 shod. Osoba, která v `myheritage` chybí, je nečtená (jiná chyba HTTP, neznámý tvar
odpovědi, nebo vypnuté čtení). `scope --no-myheritage` nastaví `myheritage: false` a snapshot shody nečte vůbec.
`scope --since <snapshot>` převezme shody MyHeritage mladší než sedm dní (`--myheritage-max-age-days N`) stejně
jako record-matches i s původním časem čtení.
Tempo zůstává nejméně 1,1 s mezi požadavky. Čekání běží přes Web Worker (`window.fsSpanek`), protože skrytá
záložka náhledu po 5 minutách brzdí `setTimeout` stránky na jedno probuzení za minutu (19. 11. 2026 tak dávka
jela položku za minutu). Záložku načtenou se starší verzí nástroje je třeba nahrát znovu.

## Co se porovnává

Vstupem jsou `data/osoby.py` a mapa FS ID. Je-li nastavený zdrojový GEDCOM, zahrne i jeho strom, opravy
a sloučení dvojníků podle `data/web.json` a případné doplňky z `data/doplnky_rodiny.ged`.
Zahrne i osoby ve větvích bez spojení s výchozí osobou a vlastní záznamy SIDE.
Příbuzní převzatí pouze z cizího stromu zůstávají `mh`.

GEDCOM doplňků může obsahovat samostatné rodiny, u kterých vztah k výchozí osobě není doložený.
Snapshot i diff je berou jako ostatní osoby mimo komponentu. K existující osobě na
FamilySearch lze poslat doložený fakt a snímek jako zdroj. U skupinových záznamů SIDE „vztah nedoložen“
lze připojit doložený údaj ke konkrétní existující osobě. Vazbu k rodině ponech bez zápisu, dokud ji nepotvrdí záznam.

Chybějící ID se přiřadí automaticky pouze při jediné shodě celého jména, přesného data narození a vazby
ke známému rodiči nebo manželovi na FS. Křestní jména se srovnávají přes `first_key` a `NAME_GROUPS`, tedy
Jan = Johann. Slabší jediná shoda jde do `mapping_review` (oddíl „ID ke kontrole“), nikdy rovnou do mapy:
jen rok narození (místně nebo na FS je jen rok či měsíc), jiný tvar příjmení (Nováková = Novák, prostřední
jméno navíc) nebo vazba jen přes namapované dítě. Takovou shodu zkontroluj (rodiče a manžel podle jmen,
místo, úmrtí), a když sedí, přesuň ji do `mappings` zkontrolované kopie; `map` ji pak přijme, protože ji
znovu odvodí z dat. Nejednoznačné shody, osoby bez rodiče na FS a nezaložené osoby zůstanou v seznamu
k dohledání i se seznamem kandidátů. Mapování lze opakovat.

Kandidáty bere diff z přečtených osob a ze sousedů. Snapshot s `neighbours: true` (výchozí `scope`) uloží
zesnulé rodiče a manžele, které FamilySearch vrací už v odpovědích `/parents` a `/spouses`, do `relatives`,
a u každé zesnulé čtené osoby přečte navíc `/children` (jeden dotaz): zesnulé děti do `relatives`, jejich ID
do `children` podle rodiče. Žijící se neukládají. Sousedé se jinak neporovnávají a nepočítají se do úplnosti
snapshotu. Po `map` je další snapshot čte jako běžné osoby (zdroje, shody) a ukáže jejich sousedy, takže
dohledávání postupuje po generacích. Třetí zdroj kandidátů jsou citace v GEDCOMu z MyHeritage („FamilySearch
Family Tree … entry for <jméno>, person ID XXXX-XXX“, `ged_citations`). Citaci s vlastním jménem osoby bez ID
dá `load_local` do `fs_cited`, `scope` ID do `lookup` (snapshot přečte jen osobu, jeden dotaz, do `relatives`)
a diff ji při shodě jména a roku narození nabídne v `mapping_review` s vazbou „citace“, nikdy automaticky:
je to odkaz z cizího stromu. `pace` (ms, nejméně 1100, výchozí 2000) zpomalí v záložce všechna
volání nástroje včetně `fs.zdroje` a zápisů, dokud se stránka znovu nenačte; 2 s platí, když na stejném účtu
běží i jiné vlákno.
Před uložením CLI znovu ověří návrhy proti aktuálním datům a snapshotu. Oba druhy ID téže osoby,
Kekulého číslo i GEDCOM ID, se doplňují společně. Různá místní FS ID se pouze hlásí jako konflikt.

Sloučení na FS se vypíše v `id_changes` s původním a novým ID. Snapshot ukládá `merged: {staré: nové}`
při přesměrování, HTTP 301/410 nebo vrácení osoby s jiným ID. Neznámý cíl má hodnotu `null` a chybu.
Diff u starého ID nenavrhuje zápisy ani automatické nahrazení mapování. Změnu mapy je třeba ověřit
podle celého jména, přesného narození a vazby na známého rodiče.

`missing_ids` obsahuje doložené osoby se zdrojem. Nejdřív vypíše přímou linii, potom sourozence a děti
přímé linie a nakonec ostatní. Ostatní osoby bez FS ID jsou v `missing_ids_other`, v Markdownu pouze jejich počet.

Synchronizace zahrnuje i vzdálené a přiženěné osoby. Začíná přímou linií, pak sourozenci a dětmi přímé
linie, ostatními a místně neurčenými osobami. V každé skupině řadí úkoly podle FS closeness.
`diff --task-closeness N` omezí práci na bližší osoby. Ostatní úkoly vypíše v oddílu „jen vypsat“.
U nenamapovaných osob ověř skutečný vztah před vyřízením. U osob jen z cizího stromu (`mh`) se na FS
nepíší jejich údaje, mapuje se jen ID a čtou se zdroje.
Seznam řadí podle vztahu k přímé linii a closeness. Každá stopa uvádí jméno, FS ID, místní klíč, typ a ID záznamů.
Živý formát ověřený 11. 11. 2026 je `personSummaries[].personId`, `closeness` a `recordTypes`
s poli `NEW_PERSON`, `NEW_SOURCE`, `NEW_CONCLUSION`, `OTHER`. Samotný hint není doklad ani oprávnění k zápisu.

Oddíl „Shody MyHeritage“ (v JSON `myheritage` a souhrn `myheritage_summary` s počty `read`, `with_hints`, `zero`,
`unread`; nečtené jsou naše nežijící osoby s FS ID, které snapshot na shody nečetl) řadí osoby se shodami stejně jako úkoly: přímá linie, sourozenci a děti, ostatní, místně neurčené.
`close` určuje stejná hranice `--task-closeness` (výchozí bez hranice, tedy všichni); closeness bere diff z úkolů FS, kde osoba je. U každé osoby uvádí
jméno, místní klíč, FS ID, počet shod, co shoda doplní a odkaz na stránku shod. Shody typu `record` jsou
v `record_adds` a v Markdownu jako „záznam“, ostatní (story, source, osoby z cizích stromů) v `other_adds`.
Odkaz projde jen na `https://www.myheritage.…`. Z shody diff nikdy nenavrhne zápis na FS.

Shodu prověř tak, že k záznamu najdeš originál (index nebo snímek na FamilySearch, archiv), přečteš ho na snímku
a zapíšeš běžným postupem rodokmenu. MyHeritage strojově nečti, jeho podmínky automatický přístup zakazují.
Stránku shod na MyHeritage otevře uživatel ručně. Název sbírky, jméno a rok záznamu pomůžou dohledat originál.

Na FS mohou jít jen osoby `st="doc"`, které místní data i čerstvé čtení FS označí jako nežijící.
Fakt musí mít přesné datum a citovaný zápis stejného druhu a data s odkazem na snímek. Datum z GEDCOMu
se samo nestává doloženým. Otazníky a odhady se vynechávají. Značka narození před rokem 1784 sama
nerozliší narození od křtu; pro přenos křtu použij výslovný fakt `pokřtěn`. Nástroj neodhaduje typ události.
Partner sňatku se určuje jen z textu tohoto konkrétního faktu nebo z rodiny GEDCOM se shodným datem
sňatku. Jiný partner u jiného sňatku není rozpor. Neurčený či neověřený partner patří do `manual`.
U chybějícího páru nabídne nejdřív položku `couple` a potom fakt `Marriage`. Oba partneři musí být
namapovaní, doložení a nežijící. Před vytvořením browser znovu přečte obě osoby a seznamy jejich partnerů;
existující Couple mezi nimi přeskočí. Datum sňatku přidá samostatná položka na znovu načtený pár.
Opakování po přerušení tak nevytvoří další pár ani další stejný fakt. Nová místa automaticky
nepřenáší, protože volný text faktu může obsahovat dům, partnera i poznámku.

Znak † a druh zápisu Z samy nerozliší úmrtí a pohřeb. Diff čte také `data/prepisy.json`, název
a shrnutí zápisu a místní označení pohřbu. Pohřební zápis nabídne jako `Burial`, nikdy jako zpřesnění
`Death`. Jsou-li výslovně uvedena obě data, nabídne obě události samostatně. Nejistý den nepřenáší;
datum jiné osoby či narození v témže přepisu nepoužije jako datum úmrtí nebo pohřbu.

Vazbu rodič → dítě může plán automaticky nabídnout, pokud ji dokládá `napojeni.r` dítěte a oba konce
jsou `doc`. Ostatní chybějící vazby, včetně vazeb pouze z GEDCOMu, vypíše k ruční kontrole.
U širší rodiny tím záměrně nevydává doloženou existenci člověka za doklad každého vztahu v převzatém stromu.
Vytváření osob, přejmenování, opravy rozdílných dat, slučování a odpojování vztahů nejsou automatické operace.
Přesné doložené datum však může zpřesnit existující fakt s prázdným datem, stejným rokem,
stejným rokem a měsícem nebo odhadem `about YYYY` / `A+YYYY`. Plán nabídne `fact-update`,
jen pokud má jediný fakt daného druhu vlastní ID. Odhad s jiným rokem ani časové meze nezpřesňuje.

## Snapshot, plán a přerušení

Snapshot má `schema: rodokmen.fs-snapshot.v1`, `captured_at`, volitelné `ancestry` s ID zesnulých předků, slovník `persons`,
`sources` podle FS ID, `relationships`, `childAndParentsRelationships`, `relationships_read`,
`tasks`, `tasks_read`, `tasks_raw`, `record_matches`, `record_matches_read`, `myheritage`, `myheritage_read`, `merged`, `requested_ids`, `complete` a `errors`,
s volbou `neighbours` také `relatives` (zesnulí sousedé podle FS ID) a `children` (rodič → zesnulé děti).
Chybějící osobu či nenačtené zdroje diff hlásí jako nenačtené, nikdy jako prázdný stav FS.
Úkoly, record-matches a shody MyHeritage slouží výhradně jako seznam stop. Při nerozpoznaném formátu úkolů zůstane jejich
počet nezjištěný a obsah v `tasks_raw`. `complete` znamená dokončené čtení zadaného rozsahu
bez chyb. `requested_ids` obsahuje požadované osoby před omezením `--max-persons`, které slouží k částečné
kontrole. Před vyhodnocením kola zkontroluj `complete`, `errors` a záznamy potřebných osob v `persons`.
Při sloučení osoby najdeš její nové ID v `merged`. Pro vzdálenější generace předej kořen další větve a nejvýše 8 generací.
Chyby jednotlivých čtení mají `id`, `part`, `status`, `error`; starší snapshoty mohou mít textové chyby.
Při jiných HTTP chybách než 401/403/429/503 se pokračuje dalšími údaji a osobami, chybějící čtení zůstává
nenačtené. Při 401/403/429/503 se celá dávka okamžitě zastaví.
HTTP 204 u kolekcí rodičů, partnerů a zdrojů znamená úspěšné čtení prázdného seznamu.
Nesmí se parsovat jako JSON; jiné chyby JSON zůstávají nenačtenými údaji.

Plán má `schema: rodokmen.fs-plan.v1`, stabilní `id`, `reviewed: false`, přehledy `mappings`,
`missing_ids`, `conflicts`, `unread`, `manual`, úkoly a pole `items`. Položka má `id`,
`kind: couple|fact|fact-update|source|relationship`, `pid`, `st: doc`, `living: false`, `record`, `image` a `reason`
s odkazem na snímek. Fakt přidává `type` a přesné GEDCOM X `date`, sňatek také `spouse`.
Zdroj přidává `url`, `title`, vztah `parent`, `child`. Zkontrolovanou kopii můžeš zúžit odstraněním položek,
jejich ID ale neměň. Nastav `reviewed: true` a zachovej `snapshot_file` pro ověření mapování.

Položka `couple` nese `spouse`, `type: Marriage` a přesné `date` doloženého oddacího zápisu.
Zakládá pouze vztah; následující `fact` přidá datum sňatku. Vlastní pár osoby se sebou samou odmítne.

Položka `fact-update` navíc nese `fact_id` a původní objekt `previous_date`, u sňatku také
`relationship_id`. Browser znovu načte konkrétní fakt. Pokud už má cílové datum, přeskočí ho;
pokud se původní datum mezitím změnilo nebo fakt chybí, vrátí konflikt. Při zápisu zachová ID,
místo i ostatní pole faktu a změní datum a zdůvodnění. Rozdílná přesná data dej uživateli k ruční kontrole.

U snímků FamilySearch sjednotí `www` a HTTP/HTTPS. U Matriculy také jazykovou část adresy
a opakované kódování čárek a lomítek v signatuře. Stejně postupuje offline diff i kontrola před zápisem.

Před každou položkou browser znovu načte osobu a u zdrojů a vztahů také aktuální připojení.
Stejný typ a datum, stejná URL snímku či existující rodič se přeskočí. Query parametr snímku se zachovává,
například dva různé `?pg=` na Matricule jsou dva zdroje. Rozdílné datum a jiný rodič stejného pohlaví
zůstávají konfliktem. Každý zápis má `changeMessage` s důvodem a snímkem. Požadavky jdou postupně
s odstupem alespoň 1,1 s. Při HTTP 401/403/429/503 se dávka zastaví bez opakování požadavku.
Při 403/429/503 zastav hostitele také přes `tools/slusne.py`; přímé síťové pomocníky nespouštěj.

Výsledek má `schema: rodokmen.fs-result.v1`, `plan_id` a `items: [{id, status}]`, kde status je
`applied`, `skipped`, `conflict` nebo `blocked`. Při přerušení má také `error`. `log` přijímá jen ID
z daného plánu. Ledger ukládá pouze potvrzené úspěchy. Opakovaný import výsledku ani souhrn deník nezdvojí.
Ledger potlačí již provedené položky ze starého snapshotu, nové rozpory ale nezakryje. Aktuální stav vždy
ověř čerstvým snapshotem. Pokud vznikne popis zdroje a jeho připojení selže, v účtu FamilySearch
zkontroluj existující popis a připoj ho ručně. Opakovaný zápis by mohl založit další popis.

`map` a `log` čtou, mění a přepisují `data/familysearch.json`, `data/fs_sync_stav.json` a deník pod zámkem
`<soubor>.lock` sdíleným s `tools/zapis.py` (`zamceno`, `prepis`).
Zámek starší dvou minut nástroj odstraní automaticky.

Snapshoty a výsledky mohou obsahovat rodinné údaje. Zůstávají v ignorované složce `pracovni/`.
Token ani cookie se do nich neukládají. Nástroj nemění `data/osoby.py`.

Testy zahrnují offline FS server v paměti, který ověřuje skutečný prohlížečový kód bez zápisu na FS:
`python -I -X utf8 -m pytest tests/familysearch -q` v repozitáři skillu.
