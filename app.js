'use strict';
// The page and the Windows receiver share one origin; no third-party scripts.
const $ = id => document.getElementById(id);
const pairPanel = $('pairPanel'), keyboardPanel = $('keyboardPanel'), editor = $('editor');
const badge = $('badge'), message = $('message'), toggle = $('toggle');
let paired = false, enabled = false, composing = false;
let confirmed = '', pending = null, stopped = false, manualReview = false;
let sequence = Promise.resolve();

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
  badge.textContent = !paired ? '未接続' : enabled ? '入力中' : '一時停止';
  badge.className = 'badge ' + (enabled ? 'on' : paired ? 'off' : '');
  toggle.textContent = enabled ? '入力を停止' : '入力を開始';
  toggle.classList.toggle('active', enabled);
  editor.disabled = !enabled || stopped;
  document.querySelectorAll('[data-key]').forEach(b => b.disabled = !enabled || stopped);
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
  confirmed = submitted.target;
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
editor.addEventListener('compositionstart', () => { composing = true; });
editor.addEventListener('compositionend', () => {
  composing = false;
  // iOS Safari may send the final input event just after compositionend.
  setTimeout(queueFlush, 55);
});
editor.addEventListener('input', ev => {
  $('count').textContent = Array.from(editor.value).length + ' / 750';
  if (!composing && !ev.isComposing) queueFlush();
});
$('clear').addEventListener('click', () => {
  if (pending || stopped) { info('未確認の操作があるため、再送後にクリアしてください。', true); return; }
  editor.value = '';
  confirmed = '';
  info('スマホ側の入力欄だけクリアしました。PCの文字は消していません。');
  paint();
});
for (const button of document.querySelectorAll('[data-key]')) {
  button.addEventListener('click', () => enqueue(async () => {
    if (!enabled || composing || stopped) return;
    await flush();
    if (pending) return;
    const key = button.dataset.key;
    const request = {id:randomId(), action:'key', key};
    pending = request;
    await api('/api/input', request);
    pending = null;
    info(key + ' を送信しました。');
    paint();
  }));
}
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
    if (packet.action === 'edit') confirmed = packet.target;
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
refresh();
setInterval(refresh, 5000);
