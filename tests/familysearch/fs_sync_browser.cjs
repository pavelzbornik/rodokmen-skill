// Skutečný prohlížečový kód proti malému FS serveru v paměti, bez sítě.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
let writes = 0, blocked = false, delay = 0;
const failures = new Map(), redirects = new Map(), reads = [];
const people = {
  'AAAA-BBB': {id: 'AAAA-BBB', living: false, facts: []},
  'CCCC-DDD': {id: 'CCCC-DDD', living: false, facts: []},
};
const sources = [], relationships = [], caps = [];
const descriptions = new Map();
const context = {window: {}, document: {cookie: 'fssessionid=TEST_ONLY', createElement: () => ({click(){},remove(){}}), body: {appendChild(){}}},
  URL, Blob, Date, setTimeout: (f, ms) => { delay += ms; f(); },
  fetch: async (url, options = {}) => {
    const method = options.method || 'GET';
    if (method === 'GET') reads.push(url);
    if (blocked) return {ok:false, status:429};
    if (failures.get(url) === 204) return {ok:true,status:204,headers:{get:()=>null}};
    if (failures.has(url)) return {ok:false, status:failures.get(url), headers:{get:()=>redirects.get(url)||null},json:async()=>({})};
    if (url.startsWith('/service/') && options.headers.Accept !== 'application/json') return {ok:false,status:406};
    if (url.startsWith('/platform/records/') && options.headers.Accept !== 'application/x-gedcomx-v1+json')
      return {ok:false,status:406};
    if (url.endsWith('/changes') && options.headers.Accept !== 'application/x-gedcomx-atom+json')
      return {ok:false,status:406};
    let body = {};
    if (method !== 'GET') {
      assert.equal(method, 'POST');
      writes++;
      body = JSON.parse(options.body);
      for (const p of body.persons || []) {
        for (const fact of p.facts || []) {
          const pos = fact.id ? people[p.id].facts.findIndex(f => f.id === fact.id) : -1;
          if (pos < 0) people[p.id].facts.push(fact);
          else people[p.id].facts[pos] = fact;
        }
        sources.push(...(p.sources || []).map(s => ({about:descriptions.get(s.description)?.about || 'https://example.org/image/1'})));
      }
      for (const desc of body.sourceDescriptions || []) descriptions.set('/platform/sources/descriptions/1',desc);
      for (const rel of body.relationships || []) {
        const old = rel.id && relationships.find(r => r.id === rel.id);
        if (old) for (const fact of rel.facts || []) {
          const pos = fact.id ? old.facts.findIndex(f => f.id === fact.id) : -1;
          if (pos < 0) old.facts.push(fact);
          else old.facts[pos] = fact;
        }
        else relationships.push({...rel,id:rel.id || 'created-'+relationships.length,facts:rel.facts || []});
      }
    } else if (/^\/platform\/tree\/couple-relationships\/[^/]+$/.test(url)) {
      const rel = relationships.find(r => r.id === url.split('/').pop());
      if (!rel) return {ok:false,status:404,headers:{get:()=>null},json:async()=>({})};
      body = {relationships:[rel],persons:Object.values(people)};
    } else if (url === '/platform/records/personas/1:1:TEST-REC') body = {persons:[{id:'record-person'}]};
    else if (url.startsWith('/platform/tree/ancestry')) body = {persons:Object.values(people)};
    else if (url.endsWith('/users/current')) body = {users:[{id:'cis.user.test-user',treeUserId:'OWN-AGENT'}]};
    else if (url.endsWith('/changes')) body = {entries:[{id:'change1'}]};
    else if (url.endsWith('/opportunities/summaries')) body = {personSummaries:[{personId:'CCCC-DDD',closeness:29.556,
      recordTypes:{NEW_PERSON:['record1'],NEW_SOURCE:[]}}]};
    else if (url.includes('/record-matches/')) body = {matches:[{id:'record1'}]};
    else if (url.includes('/service/external/hints/myheritage/persons/') && context.mhOdd) body = {unexpected:true};
    else if (url.includes('/service/external/hints/myheritage/persons/')) body = {
      link:'https://www.myheritage.com/matchingresult-abc?minimal_match_confidence=20&lang=EN&sortBy=8', totalHints:2,
      hintDetails:[{type:'record',name:'residence',modifier:'adds'},{type:'story',name:'story',modifier:'adds'}],
      hintSummaryDetails:[{x:1}], factorsDescription:'Adds: residence and story', fsETag:'etag1'};
    else if (url.endsWith('/sources')) body = {sourceDescriptions:sources};
    else if (url.endsWith('/parents')) body = {relationships,childAndParentsRelationships:caps,persons:Object.values(people)};
    else if (url.endsWith('/spouses')) body = {relationships,persons:Object.values(people)};
    else if (url.endsWith('/children')) {
      const id = url.split('/').at(-2);
      body = {persons:caps.filter(r=>[r.parent1?.resourceId,r.parent2?.resourceId].includes(id))
        .map(r=>people[r.child.resourceId])};
    }
    else body = {persons:[people[url.split('/').pop()]]};
    return {ok:true, status:200, json:async()=>body, headers:{get:()=>'/platform/sources/descriptions/1'}};
  }};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../skills/rodokmen/tools/fs_prohlizec.js'),'utf8'), context);
(async () => {
  const api = context.window.fs;
  const writesBeforeRead = writes;
  assert.equal(typeof api.syncOprava, 'undefined', 'sdílený nástroj nenabízí ruční opravy stromu');
  context.document.cookie = 'other=1; fssessionid=TEST_ONLY; last=2';
  assert.equal((await api.syncCti('/platform/tree/persons/AAAA-BBB')).persons[0].id,'AAAA-BBB');
  assert.equal(writes,writesBeforeRead,'samostatné čtení nesmí zapisovat');
  assert.equal((await api.syncCti('/platform/records/personas/1:1:TEST-REC')).persons[0].id,'record-person');
  assert.equal((await api.syncCti('/platform/tree/persons/AAAA-BBB/changes')).entries[0].id,'change1');
  await assert.rejects(() => api.syncCti('https://example.org/'), /Neplatná FS cesta/);
  const createElement = context.document.createElement;
  try {
    let input;
    context.document.createElement = () => (input = {click() {}});
    const malformed = api.syncSoubor();
    input.files = [{text: async () => 'neplatný JSON'}];
    const checkMalformed = assert.rejects(malformed, {name: 'SyntaxError'});
    assert.doesNotThrow(() => input.onchange());
    await checkMalformed;
    const cancelled = api.syncSoubor();
    const checkCancelled = assert.rejects(cancelled, /nebyl vybrán/i);
    input.oncancel();
    await checkCancelled;
  } finally {
    context.document.createElement = createElement;
  }
  context.window.fsSyncState.busy=true;
  await assert.rejects(() => api.syncCti('/platform/tree/persons/AAAA-BBB'), /už běží/);
  context.window.fsSyncState.busy=false;
  const item = {id:'f1', kind:'fact', pid:'AAAA-BBB', type:'Birth', date:'+1800-01-02',
    st:'doc', living:false, record:'krest', image:'https://example.org/image/1', reason:'Čteno https://example.org/image/1'};
  const plan = {schema:'rodokmen.fs-plan.v1', id:'plan1', reviewed:true, items:[item]};
  assert.equal((await api.syncApply(plan)).items[0].status,'applied');
  assert.equal((await api.syncApply(plan)).items[0].status,'skipped');
  assert.equal(writes,1);
  const source = {...item,id:'s1',kind:'source',url:item.image,title:'Křest'};
  assert.equal((await api.syncApply({...plan,items:[source]})).items[0].status,'applied');
  assert.equal((await api.syncApply({...plan,items:[source]})).items[0].status,'skipped');
  assert.equal(writes,3); // založit popis a připojit k osobě
  const rel = {...item,id:'r1',kind:'relationship',parent:'CCCC-DDD',child:'AAAA-BBB'};
  assert.equal((await api.syncApply({...plan,items:[rel]})).items[0].status,'applied');
  assert.equal((await api.syncApply({...plan,items:[rel]})).items[0].status,'skipped');
  assert.equal(writes,4);
  const marriage = {...item,id:'m1',type:'Marriage',spouse:'CCCC-DDD',date:'+1820-01-02'};
  relationships.push({id:'couple1',type:'http://gedcomx.org/Couple',person1:{resourceId:'AAAA-BBB'},person2:{resourceId:'CCCC-DDD'},facts:[]});
  assert.equal((await api.syncApply({...plan,items:[marriage]})).items[0].status,'applied');
  assert.equal((await api.syncApply({...plan,items:[marriage]})).items[0].status,'skipped');
  assert.equal(writes,5);
  const beforeUpdates = writes;
  const originalBirth = {id:'birth1',type:'http://gedcomx.org/Birth',date:{formal:'+1800'},
    place:{original:'Praha'},qualifiers:[{name:'test',value:'keep'}],
    attribution:{contributor:{resourceId:'ORIGINAL-AUTHOR'}}};
  people['AAAA-BBB'].facts = [originalBirth];
  const update = {...item,id:'u1',kind:'fact-update',fact_id:'birth1',previous_date:{formal:'+1800'}};
  assert.equal((await api.syncApply({...plan,items:[update]})).items[0].status,'applied');
  const updated = people['AAAA-BBB'].facts[0];
  assert.equal(people['AAAA-BBB'].facts.length,1);
  assert.equal(updated.id,'birth1');
  assert.deepEqual(updated.place,originalBirth.place);
  assert.deepEqual(updated.qualifiers,originalBirth.qualifiers);
  assert.deepEqual(updated.attribution.contributor,originalBirth.attribution.contributor);
  assert.equal(updated.attribution.changeMessage,update.reason);
  assert.equal(updated.date.formal,update.date);
  assert.equal((await api.syncApply({...plan,items:[update]})).items[0].status,'skipped');
  assert.equal(writes,beforeUpdates+1);
  const dateCorrection = {...update,date:'+1800-01-03',previous_date:{original:update.date.slice(1),formal:update.date}};
  assert.equal((await api.syncApply({...plan,items:[dateCorrection]})).items[0].status,'conflict',
    'synchronizace nepřepisuje celé přesné datum');
  assert.equal((await api.syncApply({...plan,items:[{...dateCorrection,fact_id:'missing'}]})).items[0].status,'conflict');
  assert.equal((await api.syncApply({...plan,items:[{...dateCorrection,previous_date:undefined,date:'+1800-01-04'}]})).items[0].status,'blocked');
  relationships[1].facts = [{id:'marriage1',type:'http://gedcomx.org/Marriage',date:{},place:{original:'Brno'}}];
  const marriageUpdate = {...marriage,kind:'fact-update',fact_id:'marriage1',relationship_id:'couple1',previous_date:{}};
  assert.equal((await api.syncApply({...plan,items:[marriageUpdate]})).items[0].status,'applied');
  assert.equal(relationships[1].facts.length,1);
  assert.equal(relationships[1].facts[0].place.original,'Brno');
  assert.equal((await api.syncApply({...plan,items:[marriageUpdate]})).items[0].status,'skipped');
  assert.equal(writes,beforeUpdates+2);
  for (const estimate of [{formal:'A+1800'}, {original:'about 1800'}]) {
    people['AAAA-BBB'].facts = [{...originalBirth,date:estimate}];
    const refinement = {...update,previous_date:estimate};
    assert.equal((await api.syncApply({...plan,items:[refinement]})).items[0].status,'applied');
    assert.equal(people['AAAA-BBB'].facts[0].date.formal,update.date);
  }
  const beforeStaleUpdate = writes;
  people['AAAA-BBB'].facts = [{...originalBirth,date:{formal:'+1800',normalized:[{lang:'en',value:'1800 revised'}]}}];
  const staleUpdate = {...update,previous_date:{formal:'+1800',normalized:[{lang:'en',value:'1800'}]}};
  assert.equal((await api.syncApply({...plan,items:[staleUpdate]})).items[0].status,'conflict',
    'kontrola původního data zahrnuje i vnořená pole');
  assert.equal(writes,beforeStaleUpdate);
  const beforeImages = writes;
  for (const kind of ['new-person', 'split-couple', 'index-source']) {
    await assert.rejects(() => api.syncApply({...plan,items:[{...source,kind}]}), /Neznámý druh položky/);
  }
  const otherImage = 'https://example.org/image/2';
  const validSource = {...source,url:otherImage,image:otherImage,reason:'Čteno '+otherImage};
  const mixed = {...plan,items:[validSource,{...source,kind:'new-person'}]};
  await assert.rejects(() => api.syncApply(mixed), /Neznámý druh položky/);
  assert.equal(writes,beforeImages);
  const imagePairs = [
    ['http://data.matricula-online.eu/en/a/01%252C2%252C3%252F02/?pg=180',
      'https://data.matricula-online.eu/de/a/01%2C2%2C3%2F02/?pg=180'],
    ['https://familysearch.org/ark:/61903/3:1:TEST-IMAGE',
      'https://www.familysearch.org/ark:/61903/3:1:TEST-IMAGE'],
  ];
  for (const [attached, proposed] of imagePairs) {
    sources.push({about:attached});
    assert.equal((await api.syncApply({...plan,items:[{...source,url:proposed,image:proposed,reason:'Čteno '+proposed}]})).items[0].status,'skipped');
  }
  assert.equal(writes,beforeImages,'stejné snímky s jinou adresou se znovu nepřipojí');
  const nextUrl = imagePairs[0][1].replace('pg=180','pg=181');
  const nextPage = {...source,url:nextUrl,image:nextUrl,reason:'Čteno '+nextUrl};
  assert.equal((await api.syncApply({...plan,items:[nextPage]})).items[0].status,'applied','jiný snímek je nový zdroj');
  assert.equal(writes,beforeImages+2);
  const expectedWrites = writes;
  people['AAAA-BBB'].living=true;
  assert.equal((await api.syncApply({...plan,items:[nextPage]})).items[0].status,'blocked');
  assert.equal(writes,expectedWrites,'zdroj žijící osoby je zablokován i při existujícím připojení');
  people['AAAA-BBB'].living=false;
  await assert.rejects(() => api.syncApply({...plan,items:[{...source,url:'https://example.org/not-a-record'}]}), /Zdroj musí odkazovat na snímek/);
  const personPath = '/platform/tree/persons/AAAA-BBB';
  const matchPath = '/service/tree/tree-data/record-matches/AAAA-BBB/all';
  for (const endpoint of [personPath+'/parents',personPath+'/spouses',personPath+'/sources']) {
    failures.set(endpoint,204);
    const empty = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB']});
    assert.equal(empty.errors.length,0,'HTTP 204 je platná prázdná kolekce');
    assert.ok(empty.relationships_read.includes('AAAA-BBB'));
    assert.ok(Object.hasOwn(empty.sources,'AAAA-BBB'));
    failures.clear();
  }
  for (const [endpoint, status] of [[personPath,404],[personPath,410],[matchPath,404],[matchPath,406],
      [personPath+'/parents',500],[personPath+'/spouses',406],[personPath+'/sources',404]]) {
    failures.set(endpoint,status);
    const partial = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB','CCCC-DDD']});
    assert.ok(partial.persons['CCCC-DDD'], 'po chybě musí přečíst další osobu');
    assert.ok(partial.errors.some(e=>e.id==='AAAA-BBB' && e.status===status));
    assert.equal(partial.tasks_read,true);
    assert.equal(partial.complete,false);
    failures.clear();
  }
  for (const status of [301,410]) {
    failures.set(personPath,status);
    redirects.set(personPath,'/platform/tree/persons/CCCC-DDD');
    const merged = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB']});
    assert.equal(merged.merged['AAAA-BBB'],'CCCC-DDD');
    assert.ok(merged.persons['CCCC-DDD']);
    failures.clear(); redirects.clear();
  }
  const original = people['AAAA-BBB'];
  people['AAAA-BBB'] = people['CCCC-DDD'];
  assert.equal((await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB']})).merged['AAAA-BBB'],'CCCC-DDD');
  people['AAAA-BBB'] = original;
  const cachedAt = new Date().toISOString();
  reads.length=0;
  const incremental = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1,
    cachedMatches:{'AAAA-BBB':{data:{matches:[{id:'cached'}]},read_at:cachedAt}}});
  assert.equal(reads.includes(matchPath),false);
  assert.equal(incremental.record_matches['AAAA-BBB'].matches[0].id,'cached');
  assert.equal(incremental.record_matches_read['AAAA-BBB'],cachedAt);
  reads.length=0;
  await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1});
  assert.equal(reads.includes(matchPath),true,'plný režim musí číst matches');
  // Shody MyHeritage: jen stopa; snapshot rozliší „nečteno“ a „0 shod“.
  const mhPath = id => '/service/external/hints/myheritage/persons/' + id + '/hints';
  reads.length=0;
  failures.set(mhPath('CCCC-DDD'),404);
  const mh = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB','CCCC-DDD']});
  assert.ok(reads.includes(mhPath('AAAA-BBB')),'výchozí snapshot čte shody MyHeritage');
  assert.deepEqual(JSON.parse(JSON.stringify(mh.myheritage['AAAA-BBB'])),{totalHints:2,
    hintDetails:[{type:'record',name:'residence',modifier:'adds'},{type:'story',name:'story',modifier:'adds'}],
    factorsDescription:'Adds: residence and story',
    link:'https://www.myheritage.com/matchingresult-abc?minimal_match_confidence=20&lang=EN&sortBy=8'});
  assert.equal(mh.myheritage['CCCC-DDD'].totalHints,0,'404 znamená 0 shod, ne chybu');
  assert.ok(mh.myheritage_read['AAAA-BBB'] && mh.myheritage_read['CCCC-DDD']);
  assert.equal(mh.errors.length,0);
  assert.equal(mh.complete,true);
  failures.clear();
  failures.set(mhPath('AAAA-BBB'),204);
  assert.equal((await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1})).myheritage['AAAA-BBB'].totalHints,0,
    '204 znamená 0 shod');
  failures.set(mhPath('AAAA-BBB'),500);
  const mhFail = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1});
  assert.equal(Object.hasOwn(mhFail.myheritage,'AAAA-BBB'),false,'nepřečtená shoda zůstane nečtená');
  assert.ok(mhFail.errors.some(e=>e.id==='AAAA-BBB' && e.part==='myheritage' && e.status===500));
  failures.clear(); reads.length=0;
  const mhOff = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1,myheritage:false});
  assert.equal(reads.some(u=>u.includes('/myheritage/')),false,'myheritage:false shody nečte');
  assert.deepEqual(JSON.parse(JSON.stringify(mhOff.myheritage)),{});
  reads.length=0;
  const mhCached = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1,
    cachedMyHeritage:{'AAAA-BBB':{data:{totalHints:0,hintDetails:[],factorsDescription:'',link:null},read_at:cachedAt}}});
  assert.equal(reads.includes(mhPath('AAAA-BBB')),false,'čerstvě čtené shody se převezmou');
  assert.equal(mhCached.myheritage['AAAA-BBB'].totalHints,0);
  assert.equal(mhCached.myheritage_read['AAAA-BBB'],cachedAt);
  context.mhOdd = true;
  const mhOdd = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1});
  assert.equal(Object.hasOwn(mhOdd.myheritage,'AAAA-BBB'),false,'neznámý formát není 0 shod');
  assert.ok(mhOdd.errors.some(e=>e.part==='myheritage'));
  context.mhOdd = false;
  failures.set(mhPath('AAAA-BBB'),429); reads.length=0;
  const mhStop = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB','CCCC-DDD']});
  assert.equal(reads.includes('/platform/tree/persons/CCCC-DDD'),false,'429 u MyHeritage zastaví dávku');
  assert.equal(mhStop.complete,false);
  failures.clear(); context.window.fsSyncState.stop=null;
  for (const status of [401,403,429,503]) {
    failures.set(personPath,status); reads.length=0;
    const stopped = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB','CCCC-DDD']});
    assert.equal(reads.includes('/platform/tree/persons/CCCC-DDD'),false);
    assert.equal(stopped.complete,false);
    assert.ok(stopped.errors.some(e=>e.status===status));
    const readsBeforeStoppedRead=reads.length;
    await assert.rejects(() => api.syncCti('/platform/tree/persons/CCCC-DDD'), /STOP HTTP/);
    assert.equal(reads.length,readsBeforeStoppedRead,'čtecí pomocník sdílí trvalou stopku');
    failures.clear(); context.window.fsSyncState.stop=null;
  }
  const snap = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB','CCCC-DDD'],maxPersons:1});
  assert.equal(snap.tasks.length,1);
  assert.equal(snap.tasks_read,true);
  assert.equal(snap.errors.length,0);
  assert.equal(snap.complete,false);
  assert.equal(snap.relationships_read.length,1);
  assert.equal(writes,expectedWrites);
  // Sousedé (rodiče, manželé, děti) jen pro dohledání ID: zesnulí do relatives, žijící vůbec ne.
  people['EEEE-FFF'] = {id:'EEEE-FFF', living:false, facts:[], names:[{nameForms:[{fullText:'Marie Nová'}]}]};
  people['GGGG-HHH'] = {id:'GGGG-HHH', living:true, facts:[], names:[{nameForms:[{fullText:'Žijící Nový'}]}]};
  const kidCaps = [{id:'CAPK-1',parent1:{resourceId:'AAAA-BBB'},child:{resourceId:'EEEE-FFF'}},
    {id:'CAPK-2',parent1:{resourceId:'AAAA-BBB'},child:{resourceId:'GGGG-HHH'}}];
  caps.push(...kidCaps);
  const plain = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1,matches:false,myheritage:false,tasks:false});
  assert.equal(Object.keys(plain.relatives || {}).length,0,'bez neighbours se sousedé neukládají');
  reads.length=0;
  const delayBefore = delay;
  const near = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1,matches:false,myheritage:false,
    tasks:false,neighbours:true,pace:2000});
  assert.ok(reads.includes('/platform/tree/persons/AAAA-BBB/children'),'neighbours čte děti');
  assert.ok(near.relatives['EEEE-FFF'],'zesnulé dítě je v relatives');
  assert.ok(near.relatives['CCCC-DDD'],'zesnulý rodič nebo manžel je v relatives');
  assert.equal(near.relatives['GGGG-HHH'],undefined,'žijící se neukládá');
  assert.equal(near.relatives['AAAA-BBB'],undefined,'čtená osoba sama není soused');
  assert.deepEqual(Array.from(near.children['AAAA-BBB']),['EEEE-FFF']);
  assert.equal(near.errors.length,0);
  assert.ok(delay - delayBefore >= 2000 * (reads.length - 1) - 50,'tempo 2 s mezi požadavky');
  await assert.rejects(() => api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],pace:-1}),/Neplatná konfigurace/);
  // lookup: jen čtení osoby (jeden dotaz), zesnulá do relatives, žijící ne.
  reads.length=0;
  const look = await api.syncSnapshot({root:'AAAA-BBB',ids:['AAAA-BBB'],maxPersons:1,matches:false,myheritage:false,
    tasks:false,lookup:['EEEE-FFF','GGGG-HHH']});
  assert.ok(look.relatives['EEEE-FFF']);
  assert.equal(look.relatives['GGGG-HHH'],undefined);
  assert.equal(reads.filter(u => u.startsWith('/platform/tree/persons/EEEE-FFF')).length,1,'lookup čte jen osobu');
  await assert.rejects(() => api.syncSnapshot({root:'AAAA-BBB',lookup:['bad']}),/Neplatná konfigurace/);
  context.window.fsSyncState.pace = 0;
  delete people['EEEE-FFF']; delete people['GGGG-HHH'];
  for (const c of kidCaps) caps.splice(caps.indexOf(c),1);
  people['AAAA-BBB'].facts = [{type:'http://gedcomx.org/Birth',date:{formal:'+1801'}}];
  assert.equal((await api.syncApply(plan)).items[0].status,'conflict');
  assert.equal(writes,expectedWrites);
  people['AAAA-BBB'].living = true;
  assert.equal((await api.syncApply(plan)).items[0].status,'blocked');
  assert.equal(writes,expectedWrites);
  await assert.rejects(() => api.syncApply({...plan,reviewed:false}));
  blocked = true;
  await assert.rejects(() => api.syncApply(plan), /429/);
  assert.equal(writes,expectedWrites);
  assert.ok(delay >= 1000);
  blocked=false; context.window.fsSyncState.stop=null;
  const beforeCouple = writes;
  relationships.length=0;
  people['AAAA-BBB'].living=false;
  people['CCCC-DDD'].living=false;
  const couple = {...marriage,id:'couple-new',kind:'couple'};
  const couplePlan = {...plan,items:[couple,marriage]};
  const readStart = reads.length;
  assert.deepEqual(Array.from((await api.syncApply(couplePlan)).items, i=>i.status),['applied','applied']);
  assert.equal(writes,beforeCouple+2);
  assert.equal(relationships.length,1);
  assert.equal(relationships[0].facts.length,1);
  assert.ok(reads.slice(readStart).includes('/platform/tree/persons/AAAA-BBB/spouses'));
  assert.ok(reads.slice(readStart).includes('/platform/tree/persons/CCCC-DDD/spouses'));
  assert.deepEqual(Array.from((await api.syncApply(couplePlan)).items, i=>i.status),['skipped','skipped']);
  assert.equal(writes,beforeCouple+2);
  const keepCouple=relationships.pop();
  people['CCCC-DDD'].living=true;
  assert.equal((await api.syncApply({...plan,items:[couple]})).items[0].status,'blocked');
  people['CCCC-DDD'].living=false;
  assert.equal((await api.syncApply({...plan,items:[{...couple,spouse:couple.pid}]})).items[0].status,'blocked');
  assert.equal((await api.syncApply({...plan,items:[{...couple,date:'+1820'}]})).items[0].status,'blocked');
  assert.equal((await api.syncApply({...plan,items:[{...couple,record:''}]})).items[0].status,'blocked');
  assert.equal(writes,beforeCouple+2);
  // Pár nalezený pouze z opačného konce se také nesmí zdvojit.
  failures.set('/platform/tree/persons/AAAA-BBB/spouses',204);
  relationships.push(keepCouple);
  assert.equal((await api.syncApply({...plan,items:[couple]})).items[0].status,'skipped');
  failures.clear();
  assert.equal(writes,beforeCouple+2);
  const das='https://sg30p0.familysearch.org/service/records/storage/dascloud/das/v2/dgs:TEST/children';
  // 403 u snímku nebo filmu = neveřejný snímek (omezený film), ne blokace: zastaví jen ten snímek.
  failures.set(das,403);
  const restricted = await api.film('TEST').then(() => null, e => e);
  assert.match(restricted.message,/NEVEŘEJNÝ SNÍMEK HTTP 403/);
  assert.equal(restricted.status,403);
  assert.equal(restricted.restricted,true);
  assert.equal(context.window.fsSyncState.stop,null,'neveřejný snímek nenastaví stopku');
  const beforeTree=reads.length;
  await api.syncCti('/platform/tree/persons/AAAA-BBB');
  assert.equal(reads.length,beforeTree+1,'po neveřejném snímku se strom čte dál');
  // Tři neveřejné snímky za sebou už mohou být blokace: zastavit vše.
  await assert.rejects(() => api.film('TEST'), /NEVEŘEJNÝ SNÍMEK/);
  await assert.rejects(() => api.film('TEST'), /STOP HTTP 403/);
  const afterImageStop=reads.length;
  await assert.rejects(() => api.film('TEST'), /STOP HTTP 403/);
  await assert.rejects(() => api.syncCti('/platform/tree/persons/AAAA-BBB'), /STOP HTTP 403/);
  assert.equal(reads.length,afterImageStop,'blokace snímků zastaví i strom a další snímky bez nového požadavku');
  // 429 u snímku zastaví hned.
  context.window.fsSyncState.stop=null;
  context.window.fsSyncState.imageDenied=0;
  failures.set(das,429);
  await assert.rejects(() => api.film('TEST'), /STOP HTTP 429/);
  assert.equal(context.window.fsSyncState.stop,'STOP HTTP 429');
  console.log('FS browser: idempotence, conflict, living, review, HTTP stop OK');
})().catch(e => { console.error(e); process.exitCode=1; });
