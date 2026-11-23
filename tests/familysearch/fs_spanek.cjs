// Tempo FS v prohlížeči musí čekat přes Web Worker: skrytá záložka brzdí setTimeout na 1× za minutu.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const posted = [];
let pageTimeouts = 0;
class FakeWorker {
  constructor() { this.onmessage = null; }
  postMessage(data) {
    posted.push(data);
    setImmediate(() => this.onmessage && this.onmessage({data: data[0]}));
  }
}
const context = {
  window: {}, URL: {createObjectURL: () => 'blob:test'}, Blob: class {}, Worker: FakeWorker, Date,
  document: {cookie: 'fssessionid=TEST_ONLY', createElement: () => ({click() {}, remove() {}}), body: {appendChild() {}}},
  setTimeout: (f) => { pageTimeouts++; setImmediate(f); },
  fetch: async () => ({ok: true, status: 200, json: async () => ({persons: []}), headers: {get: () => null}}),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../skills/rodokmen/tools/fs_prohlizec.js'), 'utf8'), context);
(async () => {
  const api = context.window.fs;
  await api.syncCti('/platform/tree/persons/AAAA-BBB');
  await api.syncCti('/platform/tree/persons/AAAA-BBB');
  assert.ok(posted.length >= 2, 'čekání mezi požadavky jde přes Worker');
  assert.ok(posted.some(([, ms]) => ms >= 1000), 'Worker drží odstup aspoň 1 s');
  assert.equal(pageTimeouts, 0, 'tempo nepoužívá setTimeout stránky');
  console.log('FS spánek přes Worker OK');
})().catch(e => { console.error(e); process.exitCode = 1; });
