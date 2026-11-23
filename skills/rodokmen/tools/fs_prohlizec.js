// FamilySearch v prohlížeči – zdroje u osob a stahování snímků.
//
// Postup pro přihlášený prohlížeč:
//   1. Otevři účet na https://www.familysearch.org/.
//   2. Celý tento soubor vlož jednou do preview_evaluate. Definuje funkce na objektu window.fs.
//   3. Pak volej např.:
//        await fs.zdroje(['AAAA-BBB','CCCC-DDD'])        -> názvy a odkazy připojených zdrojů (bez církevních indexů)
//        fs.zdrojeNaPozadi([...150 id...]); ...; fs.vysledek()  -> pro velké seznamy (evaluate má limit 15 s)
//        await fs.snimek(arkId)                         -> stáhne snímek podle ARK ID, vrátí film, pořadí a velikost
//        await fs.film(dgs)                             -> počet snímků ve filmu
//        await fs.stahni(dgs, 85)                       -> stáhne snímek č. 85 filmu
//
// Pravidlo: než začneš hledat v archivech osobu s ID na FamilySearch, přečti nejdřív její připojené zdroje.
// Rodina tam připojuje i snímky, které vyhledávání nenajde (sčítání 1921, vídeňské přihlášky, opisy).
(() => {
  const tok = () => (document.cookie.match(/fssessionid=([^;]+)/) || [])[1];
  const DAS = 'https://sg30p0.familysearch.org/service/records/storage/dascloud/das/v2/';
  const H = (accept) => ({ Authorization: 'Bearer ' + tok(), Accept: accept || 'application/json' });
  const CIRKEV = /Church Books|Církevní knihy|digi\.ceskearchivy|ebadatelna|matricula|^Křest |^Sňatek |^Úmrtí |^Pohřeb /i;
  // Skrytá záložka náhledu: prohlížeč po 5 minutách brzdí setTimeout na jedno probuzení za minutu
  // (dávka 250 položek tak 19. 11. 2026 jela položku za minutu). Časovač ve Web Workeru brzděný není.
  if (!window.fsSpanek) {
    let worker = null;
    try {
      const src = 'onmessage=e=>setTimeout(()=>postMessage(e.data[0]),e.data[1])';
      worker = typeof Worker === 'function' ? new Worker(URL.createObjectURL(new Blob([src], {type: 'text/javascript'}))) : null;
    } catch (_) { worker = null; /* CSP nebo prostředí bez Workeru: běžný setTimeout. */ }
    const waiting = new Map();
    let next = 0;
    if (worker) worker.onmessage = (e) => { const done = waiting.get(e.data); waiting.delete(e.data); if (done) done(); };
    window.fsSpanek = (ms) => new Promise((done) => {
      if (!worker) return setTimeout(done, ms);
      const id = ++next; waiting.set(id, done); worker.postMessage([id, ms]);
    });
  }
  const sleep = (ms) => window.fsSpanek(ms);
  // Snímky i starší čtení zdrojů sdílejí tempo a trvalou stopku synchronizace.
  // 403 u snímku nebo filmu (úložiště DAS, /platform/records/images/) znamená neveřejný snímek
  // (omezený film), ne blokaci: chyba jen pro ten snímek, bez stopky. Tři takové za sebou už stopka jsou.
  const SNIMEK = /\/das\/v2\/|^\/platform\/records\/images\//;
  const readFetch = async (url, options) => {
    const state = window.fsSyncState || (window.fsSyncState = {last: 0, busy: false, stop: null});
    if (state.stop) throw new Error(state.stop);
    if (state.busy) throw new Error('Synchronizace už běží; použij fs.syncStav()');
    await sleep(Math.max(0, Math.max(1100, state.pace || 0) - (Date.now() - state.last)));
    state.last = Date.now();
    const response = await fetch(url, options);
    if (!response.ok) {
      if (response.status === 403 && SNIMEK.test(url) && (state.imageDenied || 0) < 2) {
        state.imageDenied = (state.imageDenied || 0) + 1;
        const e = new Error('NEVEŘEJNÝ SNÍMEK HTTP 403 (omezený film, přeskoč ho; není to blokace)');
        e.status = 403; e.restricted = true;
        throw e;
      }
      if ([401, 403, 429, 503].includes(response.status)) state.stop = 'STOP HTTP ' + response.status;
      const e = new Error(state.stop || 'HTTP ' + response.status);
      e.status = response.status;
      throw e;
    }
    if (SNIMEK.test(url)) state.imageDenied = 0;
    return response;
  };
  const uloz = (blob, jmeno) => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = jmeno; document.body.appendChild(a); a.click();
  };
  const fs = {
    async zdroje(ids, vse = false) {
      const out = {};
      for (const id of ids) {
        const r = await readFetch('/platform/tree/persons/' + id + '/sources', { headers: H('application/x-fs-v1+json') });
        if (r.status !== 200) { out[id] = r.status; continue; }
        const j = await r.json();
        const x = (j.sourceDescriptions || []).map((s) => [(s.titles?.[0]?.value || '').slice(0, 120), s.about || '']);
        const f = vse ? x : x.filter((s) => !CIRKEV.test(s[0] + ' ' + s[1]));
        if (f.length) out[id] = f;
      }
      return out;
    },
    zdrojeNaPozadi(ids, vse = false) { fs._v = null; fs.zdroje(ids, vse).then((o) => (fs._v = o)); return 'spuštěno'; },
    async vysledek(cekej = 12) { for (let i = 0; i < cekej && !fs._v; i++) await sleep(1000); return fs._v || 'ještě běží'; },
    async film(film) {
      const c = await (await readFetch(DAS + 'dgs:' + film + '/children', { headers: H() })).json();
      return c.children.length;
    },
    async stahni(film, poradi) {
      const c = await (await readFetch(DAS + 'dgs:' + film + '/children', { headers: H() })).json();
      const x = c.children.find((y) => y.order == poradi);
      if (!x) return [film, poradi, 'není', c.children.length];
      const b = await (await readFetch(DAS + x.apid + '/dist.jpg', { headers: { Authorization: 'Bearer ' + tok() } })).blob();
      uloz(b, 'f' + film + '_' + poradi + '.jpg');
      return film + ':' + poradi + ':' + b.size;
    },
    async snimek(ark) {
      const j = await (await readFetch('/platform/records/images/' + ark.replace(/^.*?(3:1:)/, '$1'), { headers: H('application/x-gedcomx-v1+json') })).json();
      const node = j.links['image-node'].href;
      const jmeno = await (await readFetch(node + '/name', { headers: { Authorization: 'Bearer ' + tok() } })).text(); // dgs:FILM.FILM_00085
      const m = jmeno.match(/dgs:(\d+)\.\d+_(\d+)/);
      const b = await (await readFetch(node + '/dist.jpg', { headers: { Authorization: 'Bearer ' + tok() } })).blob();
      uloz(b, 'f' + m[1] + '_' + (+m[2]) + '.jpg');
      return m[1] + ':' + (+m[2]) + ':' + b.size;
    },
  };
  window.fs = fs;
  return tok() ? 'fs připraveno' : 'nejsi přihlášen na FamilySearch';
})();

// Opakovatelná synchronizace stromu. Starší funkce nahoře zůstávají pro práci se snímky.
// scope.json vytvoří tools/fs_sync.py scope. Plán i konfiguraci lze předat jako objekt,
// nebo přes fs.syncSoubor() vybrat stažený JSON. V preview vždy spouštěj *NaPozadi.
(() => {
  const fs = window.fs;
  // Přežije opětovné vložení souboru. Po blokaci se v této záložce už nic nezkouší.
  const state = window.fsSyncState || (window.fsSyncState = {last: 0, busy: false, stop: null});
  const BASE = 'http://gedcomx.org/';
  const sleep = ms => (window.fsSpanek ? window.fsSpanek(ms) : new Promise(resolve => setTimeout(resolve, ms)));
  const download = (data, name) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], {type: 'application/json'}));
    const a = document.createElement('a');
    a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const request = async (path, method = 'GET', body, extraHeaders = {}) => {
    if (state.stop) throw new Error(state.stop);
    if (!path.startsWith('/platform/') && !path.startsWith('/service/')) throw new Error('Neplatná FS cesta');
    await sleep(Math.max(0, Math.max(1100, state.pace || 0) - (Date.now() - state.last)));
    state.last = Date.now();
    const token = (document.cookie.match(/(?:^|;\s*)fssessionid=([^;]+)/) || [])[1];
    if (!token) throw new Error('FamilySearch není přihlášený');
    const headers = {Authorization: 'Bearer ' + token,
      Accept: path.startsWith('/service/') ? 'application/json'
        : /\/changes(?:\?|$)/.test(path) ? 'application/x-gedcomx-atom+json'
        : path.startsWith('/platform/records/') ? 'application/x-gedcomx-v1+json' : 'application/x-fs-v1+json',
      ...extraHeaders};
    if (body) headers['Content-Type'] = 'application/x-fs-v1+json';
    const response = await fetch(path, {method, headers, ...(body ? {body: JSON.stringify(body)} : {})});
    if (!response.ok) {
      if ([401, 403, 429, 503].includes(response.status)) state.stop = 'STOP HTTP ' + response.status;
      const error = new Error((state.stop || 'HTTP ' + response.status) + ' ' + path.replace(/users\/[^/]+/, 'users/<user>'));
      error.status = response.status;
      if ([301, 410].includes(response.status)) {
        error.location = response.headers?.get('Location');
        try { error.data = await response.json(); } catch (_) { /* Bez těla nebo ne-JSON odpověď. */ }
      }
      throw error;
    }
    // Zápis obvykle vrací 201/204 bez těla.
    return {data: method === 'GET' ? (response.status === 204 ? {} : await response.json()) : null,
      location: response.headers.get('Location') || response.headers.get('X-Entity-Id')};
  };
  const guarded = async work => {
    if (state.busy) throw new Error('Synchronizace už běží; použij fs.syncStav()');
    state.busy = true;
    try { return await work(); } finally { state.busy = false; }
  };
  // Pomocné čtení používá stejné přihlášení, tempo a trvalou stopku jako synchronizace.
  fs.syncCti = path => guarded(async () => (await request(path)).data);
  const date = value => {
    const text = typeof value === 'object' ? value?.formal || value?.original || '' : value || '';
    if (/^\+?\d{4}(?:-\d{2}(?:-\d{2})?)?$/.test(text)) return '+' + text.replace(/^\+/, '');
    const m = text.match(/^(?:(\d{1,2})\s+)?([a-z]+)\s+(\d{4})$/i);
    if (!m) return null;
    const months = 'january february march april may june july august september october november december'.split(' ');
    const month = months.findIndex(v => [v, v.slice(0, 3)].includes(m[2].toLowerCase())) + 1;
    return month ? '+' + m[3] + '-' + String(month).padStart(2, '0') + (m[1] ? '-' + m[1].padStart(2, '0') : '') : null;
  };
  const refinesDate = (exact, previous) => {
    if (!/^\+\d{4}-\d{2}-\d{2}$/.test(exact)) return false;
    const text = previous?.formal || previous?.original || '';
    if (!text) return true;
    const old = date(text);
    if (old) return exact.startsWith(old + '-');
    const estimate = text.match(/^A\+(\d{4})$/) || text.match(/^(?:about|abt\.?|circa|ca\.?|asi)\s+(\d{4})$/i);
    return estimate?.[1] === exact.slice(1, 5);
  };
  const urlKey = value => {
    const u = new URL(value);
    u.hash = '';
    u.pathname = u.pathname.replace(/\/$/, '');
    if (u.hostname === 'data.matricula-online.eu') {
      u.protocol = 'https:';
      u.pathname = u.pathname.replace(/^\/(en|de|cs|sk|pl)(?=\/)/, '')
        .replace(/%(?:25)*2c/gi, ',').replace(/%(?:25)*2f/gi, '%2F');
    }
    // Index určuje ARK ID; FS vrací jeho odkazy bez www, starší citace i přes HTTP.
    if (['familysearch.org', 'www.familysearch.org'].includes(u.hostname)
        && /^\/ark:\/61903\/(?:1:1|3:1):[A-Z0-9-]+$/.test(u.pathname)) {
      u.protocol = 'https:'; u.hostname = 'familysearch.org';
      if (u.pathname.startsWith('/ark:/61903/1:1:')) u.search = '';
    }
    for (const k of [...u.searchParams.keys()]) if (k.startsWith('utm_')) u.searchParams.delete(k);
    u.searchParams.sort();
    return u.href.replace(/\/$/, '');
  };
  const pid = value => /^[A-Z0-9]{4}-[A-Z0-9]{2,4}$/.test(value || '');
  const pathOf = id => {
    if (!pid(id)) throw new Error('Neplatné FS ID');
    return '/platform/tree/persons/' + id;
  };
  const deceased = async id => {
    const j = (await request(pathOf(id))).data;
    const p = (j.persons || []).find(p => p.id === id);
    return p?.living === false ? p : null;
  };
  const parents = j => {
    const pairs = (j.relationships || []).filter(r => r.type === BASE + 'ParentChild')
      .map(r => [r.person1?.resourceId, r.person2?.resourceId]);
    for (const r of j.childAndParentsRelationships || []) {
      for (const role of ['father', 'mother']) if (r[role]?.resourceId) pairs.push([r[role].resourceId, r.child?.resourceId]);
    }
    return pairs;
  };
  const personRelations = async id => {
    // Dokumentovaný endpoint vrací rodiče, child-and-parents vztahy a osoby rodičů.
    return (await request(pathOf(id) + '/parents')).data;
  };
  fs.syncSoubor = () => new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.json';
    input.oncancel = () => reject(new Error('Nebyl vybrán žádný soubor'));
    input.onchange = () => input.files[0].text().then(JSON.parse).then(resolve, reject);
    input.click();
  });
  fs.syncSnapshot = config => guarded(async () => {
    const cfg = {...{root: null, generations: 8, ids: [], tasks: true, matches: true, myheritage: true,
      maxPersons: 0, neighbours: false, pace: 0, lookup: []}, ...config};
    if ((cfg.root !== null && !pid(cfg.root)) || !Number.isInteger(cfg.generations) || cfg.generations < 1 || cfg.generations > 8
        || !Number.isInteger(cfg.maxPersons) || cfg.maxPersons < 0 || !cfg.ids.every(pid)
        || !Array.isArray(cfg.lookup) || !cfg.lookup.every(pid)
        || !Number.isInteger(cfg.pace) || cfg.pace < 0) throw new Error('Neplatná konfigurace');
    if (cfg.pace) state.pace = cfg.pace;
    const out = {schema: 'rodokmen.fs-snapshot.v1', captured_at: new Date().toISOString(), complete: false,
      ancestry: null, persons: {}, relatives: {}, children: {}, relationships: [], childAndParentsRelationships: [], relationships_read: [],
      sources: {}, tasks: [], record_matches: {}, record_matches_read: {}, myheritage: {}, myheritage_read: {}, merged: {},
      errors: [], requested_ids: [], tasks_read: false};
    fs._sync = {running: true, kind: 'snapshot', count: 0};
    const read = async (id, part, work) => {
      try { return await work(); } catch (e) {
        out.errors.push({id, part, status: e.status || null, error: String(e.message)});
        if (state.stop) throw e;
        return null;
      }
    };
    const readPerson = async id => {
      let j;
      try { j = (await request(pathOf(id))).data; } catch (e) {
        if (![301, 410].includes(e.status)) throw e;
        const target = e.location?.match(/\/persons\/([A-Z0-9]{4}-[A-Z0-9]{2,4})(?:[/?#]|$)/)?.[1]
          || e.data?.persons?.find(p => p.id !== id && pid(p.id))?.id;
        out.merged[id] = target || null;
        if (!target || target === id) throw e;
        j = (await request(pathOf(target))).data;
      }
      const p = j.persons?.find(p => p.id === id) || (j.persons?.length === 1 ? j.persons[0] : null);
      if (!p || !pid(p.id)) throw new Error('Osoba ve výpisu chybí: ' + id);
      if (p.id !== id) out.merged[id] = p.id;
      return p;
    };
    try {
      const ancestry = cfg.root ? await read(cfg.root, 'ancestry', async () =>
        (await request('/platform/tree/ancestry?person=' + cfg.root + '&generations=' + cfg.generations)).data) : null;
      const ancestors = ancestry?.persons || [];
      if (ancestry) out.ancestry = {persons: ancestors.filter(p => p.living === false).map(p => ({id: p.id}))};
      let ids = [...new Set([...cfg.ids, ...ancestors.map(p => p.id)])].filter(pid);
      out.requested_ids = ids;
      if (cfg.maxPersons) ids = ids.slice(0, cfg.maxPersons);
      for (const requestedId of ids) {
        const p = await read(requestedId, 'person', () => readPerson(requestedId));
        fs._sync.count++;
        if (!p) continue;
        const id = p.id;
        if (out.persons[id]) continue;
        // Žijícím neukládej podrobnosti do pracovního snapshotu.
        out.persons[id] = p.living === false ? p : {id, living: p.living};
        if (p.living === false) {
          const rel = await read(id, 'parents', () => personRelations(id));
          out.relationships.push(...(rel?.relationships || []));
          out.childAndParentsRelationships.push(...(rel?.childAndParentsRelationships || []));
          const spouses = await read(id, 'spouses', async () => (await request(pathOf(id) + '/spouses')).data);
          out.relationships.push(...(spouses?.relationships || []));
          if (rel && spouses) out.relationships_read.push(id);
          // Sousedé jen k dohledání FS ID místních osob (diff je páruje podle jména, narození a vazby).
          // Žijící se neukládají vůbec.
          if (cfg.neighbours) {
            const keep = q => q && pid(q.id) && q.id !== id && q.living === false;
            for (const q of [...(rel?.persons || []), ...(spouses?.persons || [])]) if (keep(q)) out.relatives[q.id] = q;
            const kids = await read(id, 'children', async () => (await request(pathOf(id) + '/children')).data);
            if (kids) {
              const dead = (kids.persons || []).filter(keep);
              out.children[id] = dead.map(q => q.id);
              for (const q of dead) out.relatives[q.id] = q;
            }
          }
          const sources = await read(id, 'sources', async () => (await request(pathOf(id) + '/sources')).data);
          if (sources) out.sources[id] = sources.sourceDescriptions || [];
          if (cfg.matches) {
            const cached = cfg.cachedMatches?.[id];
            const matches = cached || await read(id, 'record-matches', async () => ({
              data: (await request('/service/tree/tree-data/record-matches/' + id + '/all')).data,
              read_at: new Date().toISOString()
            }));
            if (matches) {
              out.record_matches[id] = matches.data;
              out.record_matches_read[id] = matches.read_at;
            }
          }
          // Shody MyHeritage ukazuje FS u osoby. Jen stopa; 204 a 404 = 0 shod, chybějící klíč = nečteno.
          if (cfg.myheritage) {
            const cached = cfg.cachedMyHeritage?.[id];
            const mh = cached || await read(id, 'myheritage', async () => {
              let j;
              try { j = (await request('/service/external/hints/myheritage/persons/' + id + '/hints')).data; } catch (e) {
                if (e.status !== 404) throw e;
                j = {};
              }
              // Neznámý tvar odpovědi se nesmí vydávat za 0 shod.
              if (Object.keys(j || {}).length && !Number.isInteger(j.totalHints)) throw new Error('Neznámý formát shod MyHeritage');
              return {data: {totalHints: Number.isInteger(j.totalHints) ? j.totalHints : 0,
                hintDetails: Array.isArray(j.hintDetails) ? j.hintDetails : [],
                factorsDescription: j.factorsDescription || '', link: j.link || null},
                read_at: new Date().toISOString()};
            });
            if (mh) {
              out.myheritage[id] = mh.data;
              out.myheritage_read[id] = mh.read_at;
            }
          }
        }
      }
      // Kandidáti z citací GEDCOMu: jen osoba (jeden dotaz), k dohledání ID. Žijící se neukládají.
      for (const id of cfg.lookup) {
        if (out.persons[id] || out.relatives[id]) continue;
        const p = await read(id, 'lookup', () => readPerson(id));
        if (p?.living === false && !out.persons[p.id]) out.relatives[p.id] = p;
      }
      if (cfg.tasks) {
        const tasks = await read(null, 'tasks', async () => {
          const user = (await request('/platform/users/current')).data.users?.[0];
          const cis = user?.cisId || user?.id;
          if (!cis) throw new Error('Chybí ID přihlášeného uživatele');
          return (await request('/service/home/pop/users/' + encodeURIComponent(cis) + '/opportunities/summaries')).data;
        });
        out.tasks_raw = tasks;
        const list = Array.isArray(tasks) ? tasks : tasks?.personSummaries || tasks?.summaries || tasks?.opportunities;
        out.tasks = Array.isArray(list) ? list : [];
        out.tasks_read = Array.isArray(list);
        if (!out.tasks_read) out.errors.push('Neznámý formát opportunities; viz tasks_raw');
        // Summaries mají jen personId, jméno doplň jedním čtením osoby i u vzdálených úkolů.
        for (const id of [...new Set(out.tasks.map(t => t.personId).filter(pid))]) {
          if (out.persons[id]) continue;
          const p = await read(id, 'task-person', () => readPerson(id));
          if (p) out.persons[p.id] = p.living === false ? p : {id: p.id, living: p.living};
        }
      }
      out.complete = ids.length === out.requested_ids.length && !out.errors.length;
    } catch (e) {
      if (!out.errors.some(v => v.error === String(e.message)))
        out.errors.push({id: null, status: e.status || null, error: String(e.message)});
    } finally {
      fs._sync = {running: false, kind: 'snapshot', count: fs._sync.count, result: out, stop: state.stop};
      download(out, 'fs-snapshot-' + out.captured_at.slice(0, 10) + '.json');
    }
    return out;
  });
  fs.syncApply = plan => guarded(async () => {
    if (plan.schema !== 'rodokmen.fs-plan.v1' || plan.reviewed !== true || !Array.isArray(plan.items))
      throw new Error('Vyžaduji zkontrolovaný plán s reviewed: true');
    const kinds = new Set(['couple', 'fact', 'fact-update', 'source', 'relationship']);
    if (plan.items.some(item => !kinds.has(item?.kind))) throw new Error('Neznámý druh položky');
    const result = {schema: 'rodokmen.fs-result.v1', plan_id: plan.id, items: []};
    fs._sync = {running: true, kind: 'apply', count: 0};
    try {
      for (const it of plan.items) {
        const row = {id: it.id, status: 'blocked'};
        if (it.st !== 'doc' || it.living !== false || !it.image?.match(/^https?:\/\//)
            || !it.reason?.includes(it.image) || !it.record) {
          result.items.push(row); continue;
        }
        const p = await deceased(it.pid);
        if (!p) { result.items.push(row); continue; }
        const attribution = {changeMessage: it.reason};
        if (it.kind === 'couple') {
          if (it.spouse === it.pid || !pid(it.spouse) || it.type !== 'Marriage'
              || !/^\+\d{4}-\d{2}-\d{2}$/.test(it.date) || date(it.date) !== it.date
              || !await deceased(it.spouse)) { result.items.push(row); continue; }
          const a = (await request(pathOf(it.pid) + '/spouses')).data;
          const b = (await request(pathOf(it.spouse) + '/spouses')).data;
          const exists = [...(a.relationships || []), ...(b.relationships || [])].some(r =>
            r.type === BASE + 'Couple'
            && [r.person1?.resourceId, r.person2?.resourceId].includes(it.pid)
            && [r.person1?.resourceId, r.person2?.resourceId].includes(it.spouse));
          if (exists) row.status = 'skipped';
          else {
            await request('/platform/tree/relationships', 'POST', {relationships: [{type: BASE + 'Couple',
              person1: {resourceId: it.pid, resource: 'https://www.familysearch.org' + pathOf(it.pid)},
              person2: {resourceId: it.spouse, resource: 'https://www.familysearch.org' + pathOf(it.spouse)}, attribution}]});
            row.status = 'applied';
          }
        } else if (it.kind === 'fact' || it.kind === 'fact-update') {
          if (!['Birth', 'Christening', 'Death', 'Burial', 'Marriage'].includes(it.type) || date(it.date) !== it.date)
            throw new Error('Nepodporovaný fakt');
          let target = p, couple = null;
          if (it.type === 'Marriage') {
            if (!await deceased(it.spouse)) { result.items.push(row); continue; }
            const j = (await request(pathOf(it.pid) + '/spouses')).data;
            couple = (j.relationships || []).find(r => r.type === BASE + 'Couple'
              && (it.kind !== 'fact-update' || r.id === it.relationship_id)
              && [r.person1?.resourceId, r.person2?.resourceId].includes(it.pid)
              && [r.person1?.resourceId, r.person2?.resourceId].includes(it.spouse));
            if (!couple?.id) { row.status = 'conflict'; result.items.push(row); continue; }
            target = couple;
          }
          const old = (target.facts || []).filter(f => f.type === BASE + it.type);
          if (it.kind === 'fact-update') {
            if (!it.fact_id || !it.previous_date || typeof it.previous_date !== 'object'
                || Array.isArray(it.previous_date) || !/^\+\d{4}-\d{2}-\d{2}$/.test(it.date)) {
              result.items.push(row); continue;
            }
            const fact = old.find(f => f.id === it.fact_id);
            const canonical = v => JSON.stringify(v, (key, value) =>
              value && typeof value === 'object' && !Array.isArray(value)
                ? Object.fromEntries(Object.keys(value).sort().map(k => [k, value[k]])) : value);
            if (!fact) row.status = 'conflict';
            else if (date(fact.date) === it.date) row.status = 'skipped';
            else if (canonical(fact.date || {}) !== canonical(it.previous_date)) row.status = 'conflict';
            else if (!refinesDate(it.date, fact.date)) row.status = 'conflict';
            else {
              const updated = {...fact, date: {formal: it.date, original: it.date.slice(1)},
                attribution: {...fact.attribution, ...attribution}};
              if (couple) await request('/platform/tree/couple-relationships/' + encodeURIComponent(couple.id), 'POST',
                {relationships: [{id: couple.id, facts: [updated]}]});
              else await request(pathOf(it.pid), 'POST', {persons: [{id: it.pid, facts: [updated]}]});
              row.status = 'applied';
            }
          } else if (old.some(f => date(f.date) === it.date)) row.status = 'skipped';
          else if (old.length) row.status = 'conflict';
          else {
            const fact = {type: BASE + it.type, date: {formal: it.date, original: it.date.slice(1)}, attribution};
            if (couple) await request('/platform/tree/couple-relationships/' + encodeURIComponent(couple.id), 'POST',
              {relationships: [{id: couple.id, facts: [fact]}]});
            else await request(pathOf(it.pid), 'POST', {persons: [{id: it.pid, facts: [fact]}]});
            row.status = 'applied';
          }
        } else if (it.kind === 'source') {
          if (it.url !== it.image) throw new Error('Zdroj musí odkazovat na snímek');
          const attached = (await request(pathOf(it.pid) + '/sources')).data.sourceDescriptions || [];
          if (attached.some(s => s.about && urlKey(s.about) === urlKey(it.url))) row.status = 'skipped';
          else {
            const desc = await request('/platform/sources/descriptions', 'POST', {sourceDescriptions: [
              {about: it.url, titles: [{value: it.title}], citations: [{value: it.reason}], attribution}]});
            if (!desc.location) throw new Error('FS nevrátil ID zdroje');
            const description = desc.location.includes('/') ? desc.location : '/platform/sources/descriptions/' + desc.location;
            await request(pathOf(it.pid), 'POST', {persons: [{id: it.pid, sources: [{description, attribution}]}]});
            row.status = 'applied';
          }
        } else if (it.kind === 'relationship') {
          if (it.child !== it.pid || it.parent === it.child) throw new Error('Neplatná vazba');
          const parent = await deceased(it.parent);
          if (parent) {
            const j = await personRelations(it.child);
            const pairs = parents(j);
            const old = pairs.filter(([a, b]) => b === it.child).map(([a]) => a);
            if (old.includes(it.parent)) row.status = 'skipped';
            else if (old.length >= 2 || old.some(id => {
              const existing = (j.persons || []).find(p => p.id === id);
              return !parent.gender?.type || !existing?.gender?.type || existing.gender.type === parent.gender.type;
            })) row.status = 'conflict';
            else {
              await request('/platform/tree/relationships', 'POST', {relationships: [{type: BASE + 'ParentChild',
                person1: {resourceId: it.parent, resource: 'https://www.familysearch.org' + pathOf(it.parent)},
                person2: {resourceId: it.child, resource: 'https://www.familysearch.org' + pathOf(it.child)}, attribution}]});
              row.status = 'applied';
            }
          }
        }
        result.items.push(row);
        fs._sync.count++;
      }
    } catch (e) {
      result.error = String(e.message);
      throw e;
    } finally {
      fs._sync = {running: false, kind: 'apply', count: result.items.length, result, stop: state.stop};
      download(result, 'fs-result-' + new Date().toISOString().slice(0, 10) + '.json');
    }
    return result;
  });
  const background = (work) => {
    if (state.busy) return 'Synchronizace už běží';
    work().catch(e => { if (fs._sync) fs._sync.error = String(e.message); });
    return 'spuštěno; fs.syncStav()';
  };
  fs.syncSnapshotNaPozadi = config => background(() => fs.syncSnapshot(config));
  fs.syncApplyNaPozadi = plan => background(() => fs.syncApply(plan));
  fs.syncStav = () => {
    const s = fs._sync;
    return s ? {running: s.running, kind: s.kind, count: s.count, stop: s.stop || state.stop,
      error: s.error, errors: s.result?.errors, complete: s.result?.complete} : {running: false, stop: state.stop};
  };
})();
