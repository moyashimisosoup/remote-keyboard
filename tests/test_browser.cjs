const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
function harness() {
  const elements = new Map(), timers = [], packets = [], store = new Map();
  function element() {
    return {value:'', textContent:'', hidden:false, disabled:false, dataset:{}, children:[],
      classList:{toggle(){}}, listeners:{},
      addEventListener(event, fn) { this.listeners[event] = fn; },
      append(...items) { this.children.push(...items); },
      replaceChildren() { this.children = []; }, focus(){}};
  }
  function get(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }
  const keys = ['Enter','Backspace','Tab','Escape'].map(key => {
    const e=element(); e.dataset.key=key; return e;
  });
  const state = {enabled:true, fail:false, hold:null};
  const viewport = {height:800, listeners:{}, addEventListener(event,fn){this.listeners[event]=fn;}};
  const root = {dataset:{},style:{setProperty(){}}};
  const context = vm.createContext({
    window:{innerHeight:800, visualViewport:viewport},
    document:{documentElement:root,body:element(),getElementById:get, createElement:element,
      querySelectorAll(selector) {
        if (selector === '[data-key]') return keys;
        return [...keys, ...get('presetList').children.map(row => row.children[0])];
      }},
    localStorage:{getItem:key=>store.get(key) || null, setItem:(key,value)=>store.set(key,value)},
    crypto:require('node:crypto').webcrypto, Uint8Array,
    setInterval(){}, setTimeout:fn=>timers.push(fn),
    async fetch(url, opts) {
      if (url === '/api/status') return {ok:true, json:async()=>({paired:true, enabled:state.enabled})};
      const body=JSON.parse(opts.body);
      if (url === '/api/control') { state.enabled=body.enabled; return {ok:true,json:async()=>({enabled:state.enabled})}; }
      if (url === '/api/input') {
        packets.push(body);
        if (state.hold) await state.hold;
        if (state.fail) { state.fail=false; throw Error('connection lost'); }
      }
      return {ok:true,json:async()=>({ok:true})};
    }
  });
  vm.runInContext(source, context);
  const settle = async()=>{for(let i=0;i<10;i++) await Promise.resolve();};
  return {get,keys,state,timers,packets,store,settle,viewport,root,
    run:code=>vm.runInContext(code,context),
    async fire(id, event, data={}) { await get(id).listeners[event]({preventDefault(){},...data}); await settle(); }};
}
test('only acknowledged text enters history; clearing history never sends a key', async()=>{
  const h=harness(); await h.settle();
  h.get('editor').value='こんにちは'; await h.fire('editor','input');
  assert.equal(h.get('sentHistory').children[0].textContent,'こんにちは');
  const count=h.packets.length;
  await h.fire('clearHistory','click');
  assert.equal(h.get('sentHistory').children.length,0); assert.equal(h.packets.length,count);
  assert.equal(h.get('editor').value,'こんにちは');
});
test('deletions remain PC Backspace operations and preserve prior sent text', async()=>{
  const h=harness(); await h.settle();
  h.get('editor').value='今日'; await h.fire('editor','input');
  h.get('editor').value='今'; await h.fire('editor','input');
  assert.equal(h.packets.at(-1).erase,1);
  assert.equal(h.get('sentHistory').children[0].textContent,'今日');
  assert.match(h.get('sentHistory').children[1].textContent,/PCで削除/);
  await h.keys[1].listeners.click(); await h.settle();
  assert.equal(h.packets.at(-1).key,'Backspace'); assert.equal(h.get('editor').value,'');
  h.get('editor').value='次'; await h.fire('editor','input');
  assert.equal(h.packets.at(-1).erase,0);
});
test('preset registration is local; sending does not append Enter and is blocked while paused', async()=>{
  const h=harness(); await h.settle();
  h.get('presetName').value='確認'; h.get('presetType').value='text'; h.get('presetText').value='git status';
  await h.fire('presetForm','submit'); assert.equal(h.packets.length,0); assert.equal(h.store.size,1);
  const button=h.get('presetList').children[0].children[0];
  await button.listeners.click(); await h.settle();
  assert.equal(h.packets.length,1); assert.equal(h.packets[0].text,'git status'); assert.equal(h.packets[0].erase,0);
  h.state.enabled=false; await h.run('refresh()');
  assert.equal(button.disabled,true);
  await button.listeners.click(); await h.settle(); assert.equal(h.packets.length,1);
});
test('uncertain send is not recorded until retry succeeds with the same ID', async()=>{
  const h=harness(); await h.settle(); h.state.fail=true;
  h.get('editor').value='確認'; await h.fire('editor','input');
  assert.equal(h.get('sentHistory').children.length,0);
  await h.fire('retry','click');
  assert.equal(h.packets[0].id,h.packets[1].id);
  assert.equal(h.get('sentHistory').children.length,1);
  assert.equal(h.get('sentHistory').children[0].textContent,'確認');
  await h.fire('retry','click'); assert.equal(h.get('sentHistory').children.length,1);
});
test('Japanese composition waits for confirmation; clear cannot discard in-flight input', async()=>{
  const h=harness(); await h.settle();
  await h.fire('editor','compositionstart'); h.get('editor').value='きょう';
  await h.fire('editor','input',{isComposing:true}); assert.equal(h.packets.length,0);
  await h.fire('clear','click'); assert.equal(h.get('editor').value,'きょう');
  h.get('editor').value='今日'; await h.fire('editor','compositionend');
  for(const fn of h.timers) await fn(); await h.settle();
  assert.equal(h.packets.length,1); assert.equal(h.packets[0].text,'今日');
});
test('quick actions preserve keyboard focus and serialize preceding input', async()=>{
  const h=harness(); await h.settle();
  let release; h.state.hold=new Promise(resolve=>release=resolve);
  h.get('editor').value='先行入力';
  const sending=h.keys[0].listeners.click(); await h.settle();
  assert.equal(h.get('editor').disabled,false); assert.equal(h.keys[0].disabled,true); assert.equal(h.packets.length,1);
  release(); await sending; await h.settle();
  assert.equal(h.packets.length,2); assert.equal(h.packets[1].key,'Enter');
});

test('theme selection is local and unsupported values are ignored', async()=>{
  const h=harness(); await h.settle();
  h.get('theme').value='night'; await h.fire('theme','change');
  assert.equal(h.root.dataset.theme,'night');
  assert.equal(h.store.get('remote-keyboard.theme'),'night');
  h.get('theme').value='invalid'; await h.fire('theme','change');
  assert.equal(h.root.dataset.theme,'night'); assert.equal(h.packets.length,0);
});

test('characters typed during a quick-action reply remain queued after the action', async()=>{
  const h=harness(); await h.settle();
  h.get('editor').value='先行'; await h.fire('editor','input');
  let release; h.state.hold=new Promise(resolve=>release=resolve);
  const sending=h.keys[0].listeners.click(); await h.settle();
  h.get('editor').value='先行つづき';
  const typing=h.fire('editor','input');
  release(); await sending; await typing; await h.settle();
  assert.equal(h.get('editor').value,'つづき');
  assert.equal(h.packets.at(-1).text,'つづき');
  assert.equal(h.packets.at(-1).erase,0);
});
