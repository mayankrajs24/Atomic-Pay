let ME = {};
let TOKEN = localStorage.getItem('ap_token') || '';
let RECIPIENT = null;

const API = '/api';

async function api(path, data, method) {
  const opts = { headers: {} };
  if (TOKEN) opts.headers['Authorization'] = 'Bearer ' + TOKEN;
  if (data) {
    opts.method = method || 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(data);
  } else {
    opts.method = method || 'GET';
  }
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(e.detail || e.message || 'Error');
  }
  return r.json();
}

function $(id) { return document.getElementById(id); }
function show(id) {
  document.querySelectorAll('.scr').forEach(s => s.classList.remove('on'));
  $(id).classList.add('on');
}
function showErr(id, msg) { const e = $(id); e.textContent = msg; e.style.display = 'block'; }
function hideErr(id) { $(id).style.display = 'none'; }
function showOk(id, msg) { const e = $(id); e.textContent = msg; e.style.display = 'block'; }

async function doRegister() {
  hideErr('regErr');
  const name = $('regName').value.trim();
  const mobile = $('regMobile').value.trim();
  const pin = $('regPin').value.trim();
  if (!name || !mobile || !pin) return showErr('regErr', 'All fields are required');
  if (mobile.length < 10) return showErr('regErr', 'Enter valid 10-digit mobile');
  if (pin.length < 4) return showErr('regErr', 'PIN must be 4 digits');
  $('regBtn').disabled = true;
  try {
    const r = await api('/register', { name, mobile, pin });
    TOKEN = r.token;
    localStorage.setItem('ap_token', TOKEN);
    ME = r;
    show('scrLinkBank');
    loadBanks();
  } catch (e) {
    showErr('regErr', e.message);
  }
  $('regBtn').disabled = false;
}

async function doLogin() {
  hideErr('loginErr');
  const mobile = $('loginMobile').value.trim();
  const pin = $('loginPin').value.trim();
  if (!mobile || !pin) return showErr('loginErr', 'Enter mobile and PIN');
  $('loginBtn').disabled = true;
  try {
    const r = await api('/login', { mobile, pin });
    TOKEN = r.token;
    localStorage.setItem('ap_token', TOKEN);
    ME = r;
    if (!r.bank_linked) {
      show('scrLinkBank');
      loadBanks();
    } else {
      goHome();
    }
  } catch (e) {
    showErr('loginErr', e.message);
  }
  $('loginBtn').disabled = false;
}

async function loadBanks() {
  try {
    const banks = await api('/banks');
    const grid = $('bankGrid');
    grid.innerHTML = '';
    banks.forEach(b => {
      const card = document.createElement('div');
      card.className = 'bcard';
      card.onclick = () => {
        document.querySelectorAll('.bcard').forEach(c => c.classList.remove('sel'));
        card.classList.add('sel');
        card.dataset.bankId = b.id;
      };
      card.dataset.bankId = b.id;
      card.innerHTML = `
        <div class="bico">${b.icon}</div>
        <div class="binf">
          <div class="bnm">${b.name}</div>
          <div class="bsh">${b.short} - ${b.label}</div>
          <div class="bonl ${b.online ? 'online' : 'offline'}">${b.online ? 'Online' : 'Offline'}</div>
        </div>
        <div class="bchk">&#10003;</div>
      `;
      grid.appendChild(card);
    });
  } catch (e) {
    $('bankGrid').innerHTML = '<div style="color:var(--red);font-size:13px">Failed to load banks</div>';
  }
}

async function doLinkBank() {
  hideErr('linkErr');
  const sel = document.querySelector('.bcard.sel');
  if (!sel) return showErr('linkErr', 'Select a bank first');
  const bankId = sel.dataset.bankId;
  const accId = $('linkAcc').value.trim();
  if (!accId) return showErr('linkErr', 'Enter your account number');
  $('linkBtn').disabled = true;
  try {
    const r = await api('/link_bank', { bank_id: bankId, account_id: accId });
    ME.bank_linked = true;
    ME.bank_id = bankId;
    ME.account_id = r.account_id;
    ME.bank_name = r.bank_name;
    ME.bank_label = r.bank_label;
    showOk('linkOk', `Linked! ${r.holder} @ ${r.bank_name}`);
    setTimeout(() => goHome(), 1000);
  } catch (e) {
    showErr('linkErr', e.message);
  }
  $('linkBtn').disabled = false;
}

async function goHome() {
  show('scrHome');
  $('hName').textContent = ME.name || '—';
  $('hSub').textContent = ME.bank_name ? `${ME.bank_label} · ${ME.account_id}` : 'No bank linked';
  const av = $('hAv');
  av.textContent = (ME.name || '?')[0];
  av.style.background = ME.avatar_color || '#3b7fff';
  loadBal();
  loadHistory();
  setNav('home');
}

async function loadBal() {
  try {
    const r = await api('/balance');
    $('bAmt').textContent = `Rs. ${Number(r.balance).toLocaleString('en-IN')}`;
    $('bSub').textContent = `${r.bank_name}`;
    $('bAccId').textContent = r.account_id;
    $('bBank').textContent = r.bank_label;
  } catch (e) {
    $('bAmt').textContent = 'Rs. —';
  }
}

async function loadHistory() {
  try {
    const txns = await api('/history');
    const list = $('txList');
    if (!txns.length) {
      list.innerHTML = '<div class="txmt">No transactions yet.<br>Send your first payment.</div>';
      return;
    }
    list.innerHTML = '';
    txns.forEach(t => {
      const sent = t.sender_mobile === ME.mobile;
      const div = document.createElement('div');
      div.className = 'txi';
      const otherName = sent ? t.receiver_name : t.sender_name;
      const initial = (otherName || '?')[0];
      div.innerHTML = `
        <div class="txic ${sent ? 's' : 'r'}">${initial}</div>
        <div class="txinf">
          <div class="txnm">${otherName}</div>
          <div class="txdt">${t.date} ${t.time}</div>
          ${t.note ? `<div class="txnt">"${t.note}"</div>` : ''}
        </div>
        <div class="txamt">
          <div class="txa ${sent ? 's' : 'r'}">${sent ? '-' : '+'}Rs.${Number(t.amount).toLocaleString('en-IN')}</div>
          <div class="txst">${t.state === 1 ? 'Completed' : 'Reversed'}</div>
        </div>
      `;
      list.appendChild(div);
    });
  } catch (e) {
    $('txList').innerHTML = '<div class="txmt">Could not load transactions</div>';
  }
}

function goSend() {
  show('scrSend');
  RECIPIENT = null;
  $('cpNm').textContent = 'Select Recipient';
  $('cpSb').textContent = 'Enter mobile number to find';
  $('cpAv').textContent = '?';
  $('cpAv').style.background = 'var(--card)';
  $('sAmt').value = '';
  $('sNote').value = '';
  setNav('send');
}

function openFind() { $('findModal').classList.add('on'); $('findMob').value = ''; $('foundDiv').style.display = 'none'; hideErr('findErr'); $('findMob').focus(); }
function closeFind() { $('findModal').classList.remove('on'); }

let findTimer;
function findUser() {
  clearTimeout(findTimer);
  const mob = $('findMob').value.trim();
  hideErr('findErr');
  $('foundDiv').style.display = 'none';
  if (mob.length < 10) return;
  findTimer = setTimeout(async () => {
    try {
      const r = await api('/find_user', { mobile: mob });
      $('fNm').textContent = r.name;
      $('fSb').textContent = `${r.mobile} · ${r.bank}`;
      $('fAv').textContent = r.name[0];
      $('foundDiv').style.display = 'block';
      $('foundDiv').dataset.mobile = r.mobile;
      $('foundDiv').dataset.name = r.name;
      $('foundDiv').dataset.bank = r.bank;
    } catch (e) {
      showErr('findErr', e.message);
    }
  }, 300);
}

function pickRecipient() {
  RECIPIENT = {
    mobile: $('foundDiv').dataset.mobile,
    name: $('foundDiv').dataset.name,
    bank: $('foundDiv').dataset.bank
  };
  $('cpNm').textContent = RECIPIENT.name;
  $('cpSb').textContent = `${RECIPIENT.mobile} · ${RECIPIENT.bank}`;
  $('cpAv').textContent = RECIPIENT.name[0];
  $('cpAv').style.background = 'var(--accent)';
  closeFind();
}

async function doSend() {
  if (!RECIPIENT) return alert('Select a recipient first');
  const amount = parseFloat($('sAmt').value);
  if (!amount || amount <= 0) return alert('Enter a valid amount');
  const note = $('sNote').value.trim();
  $('sendBtn').disabled = true;
  $('sendBtn').textContent = 'Processing...';
  try {
    const r = await api('/pay', { receiver_mobile: RECIPIENT.mobile, amount, note });
    showResult(r);
    loadBal();
    loadHistory();
  } catch (e) {
    alert(e.message);
  }
  $('sendBtn').disabled = false;
  $('sendBtn').textContent = 'Send Payment';
}

function showResult(r) {
  const ok = r.state === 1;
  $('rico').textContent = ok ? '&#10003;' : '&#10007;';
  $('rico').style.color = ok ? 'var(--green)' : 'var(--red)';
  $('rtitle').textContent = ok ? 'Payment Successful' : 'Payment Failed';
  $('rtitle').style.color = ok ? 'var(--green)' : 'var(--red)';
  $('rsub').textContent = ok ? `To ${r.receiver_name}` : r.reason;
  $('ramt').textContent = `Rs. ${Number(r.amount).toLocaleString('en-IN')}`;
  $('ramt').style.color = ok ? 'var(--green)' : 'var(--red)';

  let bupd = '';
  if (r.new_sender_bal !== null && r.new_sender_bal !== undefined) {
    bupd += `<div class="bucard"><div class="bunm">Your Balance</div><div class="bubal">Rs.${Number(r.new_sender_bal).toLocaleString('en-IN')}</div></div>`;
  }
  if (r.new_receiver_bal !== null && r.new_receiver_bal !== undefined) {
    bupd += `<div class="bucard"><div class="bunm">${r.receiver_name}'s Balance</div><div class="bubal">Rs.${Number(r.new_receiver_bal).toLocaleString('en-IN')}</div></div>`;
  }
  $('bupd').innerHTML = bupd;

  $('rdets').innerHTML = `
    <div class="rdrow"><span class="rdlbl">Transaction ID</span><span class="rdval">${(r.tx_id||'').substring(0,8)}</span></div>
    <div class="rdrow"><span class="rdlbl">State</span><span class="rdval">${r.state === 1 ? '+1 Sattva' : '-1 Tamas'}</span></div>
    <div class="rdrow"><span class="rdlbl">Transit Time</span><span class="rdval">${r.transit_ms}ms</span></div>
    <div class="rdrow"><span class="rdlbl">Signature</span><span class="rdval">${r.signature||'—'}</span></div>
    <div class="rdrow"><span class="rdlbl">Fraud Score</span><span class="rdval">${r.fraud_score||0}</span></div>
  `;

  if (r.steps && r.steps.length) {
    $('rsteps').textContent = r.steps.join('\n');
    $('rsteps').style.display = 'block';
  } else {
    $('rsteps').style.display = 'none';
  }
  $('rov').classList.add('on');
}

function closeResult() { $('rov').classList.remove('on'); goHome(); }

function setNav(tab) {
  document.querySelectorAll('.ni').forEach(n => n.classList.remove('on'));
  const el = document.querySelector(`.ni[data-tab="${tab}"]`);
  if (el) el.classList.add('on');
}

function doLogout() {
  TOKEN = '';
  ME = {};
  localStorage.removeItem('ap_token');
  show('scrWelcome');
}

function goProfile() {
  show('scrProfile');
  $('pName').textContent = ME.name || '—';
  $('pMobile').textContent = ME.mobile || '—';
  $('pBank').textContent = ME.bank_name || 'Not linked';
  $('pAccount').textContent = ME.account_id || '—';
  $('pKyc').textContent = `Level ${ME.kyc_level || 0}`;
  setNav('profile');
  loadKycStatus();
}

async function loadKycStatus() {
  try {
    const r = await api('/kyc/status');
    $('pKyc').textContent = `Level ${r.kyc_level} - ${r.kyc_status}`;
    const docList = $('kycDocs');
    if (r.documents.length) {
      docList.innerHTML = r.documents.map(d => `
        <div class="txi" style="margin-bottom:8px">
          <div class="txinf">
            <div class="txnm">${d.type}</div>
            <div class="txdt">${d.number} - ${d.status}</div>
          </div>
        </div>
      `).join('');
    } else {
      docList.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">No documents submitted</div>';
    }
  } catch (e) {}
}

async function submitKyc() {
  const docType = $('kycDocType').value;
  const docNum = $('kycDocNum').value.trim();
  if (!docNum) return alert('Enter document number');
  hideErr('kycErr');
  try {
    await api('/kyc/submit', { document_type: docType, document_number: docNum });
    $('kycDocNum').value = '';
    showOk('kycOk', 'Document submitted for verification');
    loadKycStatus();
  } catch (e) {
    showErr('kycErr', e.message);
  }
}

async function seedDemo() {
  try { await api('/admin/seed_demo', {}, 'POST'); } catch (e) {}
}

window.addEventListener('DOMContentLoaded', () => {
  seedDemo();
});
