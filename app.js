'use strict';
// The page and the Windows receiver share one origin; no third-party scripts.
const $ = id => document.getElementById(id);
const pairPanel = $('pairPanel'), keyboardPanel = $('keyboardPanel'), editor = $('editor');
const badge = $('badge'), message = $('message'), toggle = $('toggle');
let paired = false, enabled = false, composing = false;
let confirmed = '', pending = null, stopped = false, manualReview = false;
let sequence = Promise.resolve();
let quickSending = false;
const sentRecords = [];
const PRESET_STORAGE = 'remote-keyboard.presets.v1';
const allowedKeys = ['Enter', 'Backspace', 'Tab', 'Escape'];
let presets = [];
try {
  const saved = JSON.parse(localStorage.getItem(PRESET_STORAGE) || '[]');
  if (Array.isArray(saved)) presets = saved.filter(validPreset).slice(0, 20);
} catch { /* Storage can be unavailable in private browsing. */ }
function validPreset(p) {
  return p && typeof p.name === 'string' && p.name.trim().length > 0 && p.name.length <= 30 &&
    ((p.type === 'text' && typeof p.value === 'string' && p.value.length > 0 && p.value.length <= 750 && !/[\x00-\x09\x0b-\x1f\x7f]/.test(p.value)) ||
     (p.type === 'key' && allowedKeys.includes(p.value)));
}
function drawHistory() {
  $('historyEmpty').hidden = sentRecords.length > 0;
  $('sentHistory').replaceChildren();
  for (const record of sentRecords) {
    const row = document.createElement('li');
    row.className = record.kind;
    row.textContent = record.value;
    $('sentHistory').append(row);
  }
}
function recordAccepted(packet) {
  if (packet.action === 'edit') {
    if (packet.erase) sentRecords.push({kind:'operation', value:'PCで削除 × ' + packet.erase});
    if (packet.text) {
      const last = sentRecords[sentRecords.length - 1];
      if (last && last.kind === 'text' && last.value.length + packet.text.length <= 3000) last.value += packet.text;
      else sentRecords.push({kind:'text', value:packet.text});
    }
    if (typeof packet.target === 'string') confirmed = packet.target;
  } else {
    sentRecords.push({kind:'operation', value:packet.key === 'Backspace' ? 'PCで削除 × 1' : packet.key + ' を送信'});
  }
  sentRecords.splice(0, Math.max(0, sentRecords.length - 40));
  if (packet.resetEditor) {
    const base = packet.resetBase || '';
    if (editor.value.startsWith(base)) {
      // Keep characters typed while the quick action was awaiting its reply.
      editor.value = editor.value.slice(base.length); confirmed = '';
    } else {
      confirmed = editor.value; stopped = true;
      info('キー送信中に入力欄が編集されました。PCを確認し、入力を停止・再開してから入力欄だけクリアしてください。', true);
    }
  }
  drawHistory();
}
function drawPresets() {
  $('presetList').replaceChildren();
  presets.forEach((preset, index) => {
    const row = document.createElement('div'); row.className = 'preset-row';
    const send = document.createElement('button');
    send.textContent = preset.name;
    send.title = preset.type === 'key' ? preset.value : '登録した文字を送信';
    send.dataset.presetSend = '1';
    send.addEventListener('click', () => sendQuick(preset));
    const remove = document.createElement('button');
    remove.textContent = '登録解除'; remove.className = 'subtle';
    remove.addEventListener('click', () => {
      const next = presets.filter((_, i) => i !== index);
      if (savePresets(next)) { presets = next; drawPresets(); paint(); }
    });
    row.append(send, remove); $('presetList').append(row);
  });
}
function savePresets(next) {
  try { localStorage.setItem(PRESET_STORAGE, JSON.stringify(next)); return true; }
  catch { info('ブラウザに保存できません。保存領域やプライベートブラウズ設定を確認してください。', true); return false; }
}
function sendQuick(preset) {
  return enqueue(async () => {
    if (!enabled || composing || stopped || !paired) return;
    quickSending = true; paint();
    try {
      do {
        await flush();
        if (pending || !enabled || stopped || composing) return;
      } while (editor.value !== confirmed);
      const request = preset.type === 'key'
        ? {id:randomId(), action:'key', key:preset.value, resetEditor:true, resetBase:editor.value}
        : {id:randomId(), action:'edit', erase:0, text:preset.value, resetEditor:true, resetBase:editor.value};
      pending = request;
      await api('/api/input', request);
      recordAccepted(request); pending = null;
      if (!stopped) info('送信しました。続けて新しい文章を入力できます。');
    } finally { quickSending = false; paint(); }
  });
}

function randomId() {
  if (globalThis.crypto && crypto.randomUUID) return crypto.randomUUID();
  const random = new Uint8Array(20);
  crypto.getRandomValues(random);
  return Array.from(random, x => x.toString(16).padStart(2, '0')).join('');
}
function info(msg, isError = false) {
  message.textContent = msg;
  message.classList.toggle('error', isError);
}
function paint() {
  pairPanel.hidden = paired;
  keyboardPanel.hidden = !paired;
  $('historyPanel').hidden = !paired;
  $('presetsPanel').hidden = !paired;
  badge.textContent = !paired ? '未接続' : enabled ? '入力中' : '一時停止';
  badge.className = 'badge ' + (enabled ? 'on' : paired ? 'off' : '');
  toggle.textContent = enabled ? '入力を停止' : '入力を開始';
  toggle.classList.toggle('active', enabled);
  editor.disabled = !enabled || stopped;
  document.querySelectorAll('[data-key], [data-preset-send]').forEach(b => b.disabled = !enabled || stopped || quickSending || composing);
  $('retryWrap').hidden = !stopped || !pending;
  $('retry').textContent = manualReview ? 'PCを確認し、入力状態を再同期' : '同じ操作IDで再確認';
  $('count').textContent = Array.from(editor.value).length + ' / 750';
}
async function api(path, data) {
  const opts = {credentials:'same-origin', cache:'no-store'};
  if (data !== undefined) {
    opts.method='POST';
    opts.headers={'Content-Type':'application/json','X-Remote-Keyboard':'1'};
    opts.body=JSON.stringify(data);
  }
  const res = await fetch(path, opts);
  let body;
  try { body = await res.json(); } catch { body = {}; }
  if (!res.ok) {
    const error = new Error(body.error || ('HTTP ' + res.status));
    error.status = res.status;
    throw error;
  }
  return body;
}
function enqueue(fn) {
  sequence = sequence.then(fn).catch(e => {
    stopped = true;
    manualReview = e.status === 500;
    if (manualReview) {
      info('Windowsへの入力が一部だけ成功した可能性があります。PC画面を確認してから再同期してください。', true);
    } else {
      info('送信の確認ができません。' + e.message + ' 接続確認後に同じIDで再送できます。', true);
    }
    paint();
  });
  return sequence;
}
function difference(before, after) {
  const b = Array.from(before), a = Array.from(after);
  let prefix = 0;
  while (prefix < b.length && prefix < a.length && b[prefix] === a[prefix]) prefix++;
  return {erase:b.length-prefix, text:a.slice(prefix).join('')};
}
async function flush() {
  if (composing || !enabled || stopped || !paired) return;
  if (!pending && editor.value !== confirmed) {
    const target = editor.value;
    pending = {id:randomId(), action:'edit', ...difference(confirmed, target), target};
  }
  if (!pending) return;
  const submitted = pending;
  await api('/api/input', submitted);
  recordAccepted(submitted);
  if (pending === submitted) pending = null;
  info('Windowsに送信しました');
  paint();
}
function queueFlush() { return enqueue(flush); }
async function refresh() {
  try {
    const data = await api('/api/status');
    const previous = paired;
    paired = data.paired;
    enabled = data.enabled;
    if (!paired && previous) {
      if (pending) {
        stopped = true; manualReview = true;
        info('認証が切れました。入力結果をPCで確認後、再ペアリングと再同期が必要です。', true);
      } else {
        stopped = false; confirmed = editor.value;
        info('接続が切れました。再度ペアリングしてください。', true);
      }
    }
    if (!previous && paired) info('接続しました。入力を開始してください。');
    paint();
  } catch (e) {
    enabled = false;
    info('PCと通信できません。Tailscaleと受信アプリを確認してください。', true);
    paint();
  }
}
$('pairForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    await api('/api/pair', {code:$('pin').value.trim()});
    $('pin').value = '';
    paired = true; enabled = false;
    if (!pending) { stopped = false; manualReview = false; confirmed = editor.value; }
    info('接続しました。Windowsの入力先を選び、「入力を開始」を押してください。');
    paint();
  } catch (err) { info(err.message, true); }
});
toggle.addEventListener('click', async () => {
  try {
    if (enabled) {
      enabled = false;
      paint();
      await api('/api/control', {enabled:false});
      info('入力を停止しました。');
    } else {
      if (pending) {
        info('未確認の送信があります。先に再送で確認してください。', true);
        return;
      }
      await api('/api/control', {enabled:true});
      confirmed = editor.value;
      enabled = true; stopped = false;
      info('入力可能です。メモ帳などを選択して文字を打ってください。');
      paint();
      editor.focus();
    }
  } catch (err) { info(err.message, true); await refresh(); }
});
editor.addEventListener('compositionstart', () => { composing = true; paint(); });
editor.addEventListener('compositionend', () => {
  composing = false; paint();
  // iOS Safari may send the final input event just after compositionend.
  setTimeout(queueFlush, 55);
});
editor.addEventListener('input', ev => {
  $('count').textContent = Array.from(editor.value).length + ' / 750';
  if (!composing && !ev.isComposing) queueFlush();
});
$('clear').addEventListener('click', () => {
  if (composing || quickSending || pending || stopped || editor.value !== confirmed) {
    info('変換・送信が完了してから入力欄をクリアしてください。', true); return;
  }
  editor.value = ''; confirmed = '';
  info('入力欄だけクリアしました。PCの文字と送信記録は残っています。'); paint();
});
$('clearHistory').addEventListener('click', () => {
  sentRecords.length = 0; drawHistory();
  info('iPhone側の送信記録だけ消しました。PCにはキーを送っていません。');
});
for (const button of document.querySelectorAll('[data-key]')) {
  button.addEventListener('click', () => sendQuick({type:'key', value:button.dataset.key}));
}
$('presetType').addEventListener('change', () => {
  const key = $('presetType').value === 'key';
  $('presetTextWrap').hidden = key; $('presetKeyWrap').hidden = !key;
});
$('presetForm').addEventListener('submit', e => {
  e.preventDefault();
  const preset = {name:$('presetName').value.trim(), type:$('presetType').value,
    value:$('presetType').value === 'key' ? $('presetKey').value : $('presetText').value};
  if (!validPreset(preset) || presets.length >= 20) {
    info('名前と内容を確認してください。登録は20件までです。', true); return;
  }
  const next = [...presets, preset];
  if (!savePresets(next)) return;
  presets = next; drawPresets(); paint();
  $('presetName').value = ''; $('presetText').value = '';
  info('このブラウザに登録しました。送信するには登録したボタンを押してください。');
});
$('retry').addEventListener('click', async () => {
  if (!pending) return;
  try {
    const result = await api('/api/status');
    paired = result.paired; enabled = result.enabled;
    if (manualReview) {
      if (!paired) throw new Error('まず再ペアリングしてください。');
      pending = null;
      confirmed = editor.value;
      manualReview = false; stopped = false; enabled = false;
      info('入力欄の基準を再設定しました。PCの入力位置を確認して「入力を開始」を押してください。');
      paint();
      return;
    }
    if (!enabled) {
      if (!paired) throw new Error('再ペアリングが必要です。');
      await api('/api/control', {enabled:true});
      enabled = true;
    }
    const packet = pending;
    await api('/api/input', packet);
    recordAccepted(packet);
    pending = null;
    stopped = false;
    info('操作が確認できました。入力を再開できます。');
    paint();
    queueFlush();
  } catch (e) {
    info('再送できません：' + e.message, true);
    paint();
  }
});
drawPresets(); drawHistory();
refresh();
setInterval(refresh, 5000);


const themes = ['mint', 'night', 'peach', 'gameboy'];
let chosenTheme = 'mint';
try { const saved = localStorage.getItem('remote-keyboard.theme'); if (themes.includes(saved)) chosenTheme = saved; } catch {}
document.documentElement.dataset.theme = chosenTheme;
$('theme').value = chosenTheme;
$('theme').addEventListener('change', () => {
  const value = $('theme').value;
  if (!themes.includes(value)) return;
  document.documentElement.dataset.theme = value;
  try { localStorage.setItem('remote-keyboard.theme', value); } catch {}
});
// Safari's visible viewport shrinks when the software keyboard opens.
function fitKeyboardViewport() {
  if (!window.visualViewport) return;
  const view = window.visualViewport;
  document.documentElement.style.setProperty('--visible-height', view.height + 'px');
  document.body.classList.toggle('keyboard-open', window.innerHeight - view.height > 120);
}
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', fitKeyboardViewport);
  window.visualViewport.addEventListener('scroll', fitKeyboardViewport);
  fitKeyboardViewport();
}
// Keep Safari's keyboard open when tapping a quick key or clear.
for (const button of document.querySelectorAll('[data-key], #clear')) {
  button.addEventListener('pointerdown', ev => {
    if (document.activeElement === editor) ev.preventDefault();
  });
}
