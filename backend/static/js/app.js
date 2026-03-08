let ME = {};
let TOKEN = localStorage.getItem('ap_token') || '';
let RECIPIENT = null;
let PIN_BUFFER = '';
let PENDING_PAYMENT = null;

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

function showErr(id, msg) {
  const e = $(id);
  e.textContent = msg;
  e.style.display = 'block';
  setTimeout(() => { e.style.display = 'none'; }, 5000);
}

function hideErr(id) { $(id).style.display = 'none'; }

function showOk(id, msg) {
  const e = $(id);
  e.textContent = msg;
  e.style.display = 'block';
  setTimeout(() => { e.style.display = 'none'; }, 3000);
}

function showToast(msg, type) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type || '');
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

function formatCurrency(n) {
  return '\u20B9 ' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

async function doRegister() {
  hideErr('regErr');
  const name = $('regName').value.trim();
  const mobile = $('regMobile').value.trim();
  const pin = $('regPin').value.trim();
  if (!name || !mobile || !pin) return showErr('regErr', 'All fields are required');
  if (mobile.length < 10) return showErr('regErr', 'Enter valid 10-digit mobile number');
  if (pin.length < 4) return showErr('regErr', 'PIN must be at least 4 digits');
  const btn = $('regBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Creating...';
  try {
    const r = await api('/register', { name, mobile, pin });
    TOKEN = r.token;
    localStorage.setItem('ap_token', TOKEN);
    ME = r;
    showToast('Account created successfully!', 'success');
    show('scrLinkBank');
    loadBanks();
  } catch (e) {
    showErr('regErr', e.message);
  }
  btn.disabled = false;
  btn.textContent = 'Create Account';
}

async function doLogin() {
  hideErr('loginErr');
  const mobile = $('loginMobile').value.trim();
  const pin = $('loginPin').value.trim();
  if (!mobile || !pin) return showErr('loginErr', 'Enter mobile number and PIN');
  const btn = $('loginBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Signing in...';
  try {
    const r = await api('/login', { mobile, pin });
    TOKEN = r.token;
    localStorage.setItem('ap_token', TOKEN);
    ME = r;
    showToast('Welcome back, ' + r.name + '!', 'success');
    if (!r.bank_linked) {
      show('scrLinkBank');
      loadBanks();
    } else {
      goHome();
    }
  } catch (e) {
    showErr('loginErr', e.message);
  }
  btn.disabled = false;
  btn.textContent = 'Sign In';
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
          <div class="bsh">${b.short} &middot; ${b.label}</div>
          <div class="bonl ${b.online ? 'online' : 'offline'}">${b.online ? 'Online' : 'Offline'}</div>
        </div>
        <div class="bchk">&#10003;</div>
      `;
      grid.appendChild(card);
    });
  } catch (e) {
    $('bankGrid').innerHTML = '<div style="color:var(--red);font-size:13px;padding:12px">Failed to load banks</div>';
  }
}

async function doLinkBank() {
  hideErr('linkErr');
  const sel = document.querySelector('.bcard.sel');
  if (!sel) return showErr('linkErr', 'Select a bank first');
  const bankId = sel.dataset.bankId;
  const accId = $('linkAcc').value.trim();
  if (!accId) return showErr('linkErr', 'Enter your account number');
  const btn = $('linkBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Verifying...';
  try {
    const r = await api('/link_bank', { bank_id: bankId, account_id: accId });
    ME.bank_linked = true;
    ME.bank_id = bankId;
    ME.account_id = r.account_id;
    ME.bank_name = r.bank_name;
    ME.bank_label = r.bank_label;
    showToast('Bank linked: ' + r.holder + ' @ ' + r.bank_name, 'success');
    setTimeout(() => goHome(), 800);
  } catch (e) {
    showErr('linkErr', e.message);
  }
  btn.disabled = false;
  btn.textContent = 'Verify & Link Bank';
}

async function goHome() {
  show('scrHome');
  $('hName').textContent = ME.name || '\u2014';
  $('hSub').textContent = ME.bank_name ? `${ME.bank_label} \u00B7 ${ME.account_id}` : 'No bank linked';
  const av = $('hAv');
  av.textContent = (ME.name || '?')[0];
  av.style.background = ME.avatar_color || 'linear-gradient(135deg, var(--accent), #4f46e5)';
  loadBal();
  loadHistory();
  setNav('home');
  renderAccountSelector();
}

async function renderAccountSelector() {
  const sel = $('accountSelector');
  const inner = $('accountSelectorInner');
  if (!ME.accounts || ME.accounts.length < 2) {
    if (!ME.accounts) {
      try {
        ME.accounts = await api('/accounts');
      } catch(e) { ME.accounts = []; }
    }
  }
  if (!ME.accounts || ME.accounts.length < 2) {
    sel.style.display = 'none';
    return;
  }
  sel.style.display = 'block';
  inner.innerHTML = ME.accounts.map(a => {
    const active = a.is_primary;
    const bankLabel = a.bank_name || a.bank_id;
    return `<div onclick="switchAccount(${a.id})" style="flex:0 0 auto;padding:8px 14px;border-radius:10px;cursor:pointer;border:1px solid ${active ? 'var(--accent)' : 'var(--bdr)'};background:${active ? 'var(--accent-glow)' : 'var(--card)'};white-space:nowrap">
      <div style="font-size:12px;font-weight:600;color:${active ? 'var(--accent)' : 'var(--txt)'}">${bankLabel}</div>
      <div style="font-size:10px;color:var(--dim);font-family:'JetBrains Mono',monospace">${a.account_id}</div>
    </div>`;
  }).join('');
}

async function switchAccount(id) {
  try {
    await api('/accounts/set_primary', { account_id: id });
    ME.accounts = await api('/accounts');
    const primary = ME.accounts.find(a => a.is_primary);
    if (primary) {
      ME.bank_id = primary.bank_id;
      ME.account_id = primary.account_id;
      ME.bank_name = primary.bank_name || primary.bank_id;
    }
    $('hSub').textContent = ME.bank_name ? `${ME.bank_label || ME.bank_name} \u00B7 ${ME.account_id}` : 'No bank linked';
    loadBal();
    renderAccountSelector();
    showToast('Switched account', 'success');
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function loadBal() {
  try {
    const r = await api('/balance');
    $('bAmt').textContent = formatCurrency(r.balance);
    $('bSub').textContent = r.bank_name;
    $('bAccId').textContent = r.account_id;
    $('bBank').textContent = r.bank_label;
  } catch (e) {
    $('bAmt').textContent = '\u20B9 \u2014';
  }
}

async function loadHistory() {
  try {
    const txns = await api('/history');
    renderTxList($('txList'), txns, 5);
  } catch (e) {
    $('txList').innerHTML = '<div class="empty-state"><div class="empty-icon">&#128176;</div><div class="empty-sub">Could not load transactions</div></div>';
  }
}

async function loadHistoryFull() {
  try {
    const txns = await api('/history');
    renderTxList($('txListFull'), txns, 50);
  } catch (e) {
    $('txListFull').innerHTML = '<div class="empty-state"><div class="empty-sub">Could not load transactions</div></div>';
  }
}

function renderTxList(container, txns, limit) {
  if (!txns.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-icon">&#128176;</div><div class="empty-title">No transactions yet</div><div class="empty-sub">Your payment history will appear here</div></div>';
    return;
  }
  container.innerHTML = '';
  txns.slice(0, limit).forEach(t => {
    const sent = t.sender_mobile === ME.mobile;
    const div = document.createElement('div');
    div.className = 'txi';
    const otherName = sent ? t.receiver_name : t.sender_name;
    const initial = (otherName || '?')[0];
    const stateClass = t.state === 1 ? 'sattva' : 'tamas';
    const stateLabel = t.state === 1 ? '+1 Sattva' : '-1 Tamas';
    div.innerHTML = `
      <div class="txic ${sent ? 's' : 'r'}">${initial}</div>
      <div class="txinf">
        <div class="txnm">${otherName}</div>
        <div class="txdt">${t.date} ${t.time}</div>
        ${t.note ? `<div class="txnt">"${t.note}"</div>` : ''}
      </div>
      <div class="txamt">
        <div class="txa ${sent ? 's' : 'r'}">${sent ? '-' : '+'}${formatCurrency(t.amount)}</div>
        <div class="txst"><span class="state-badge ${stateClass}">${stateLabel}</span></div>
      </div>
    `;
    container.appendChild(div);
  });
}

function goSend() {
  show('scrSend');
  RECIPIENT = null;
  $('cpNm').textContent = 'Select Recipient';
  $('cpSb').textContent = 'Tap to search by mobile number';
  $('cpAv').innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
  $('cpAv').style.background = 'var(--card2)';
  $('sAmt').value = '';
  $('sNote').value = '';
  setNav('send');
}

function goScan() { show('scrScan'); setNav('home'); }

function setAmount(v) {
  $('sAmt').value = v;
  $('sAmt').focus();
}

function openFind() {
  $('findModal').classList.add('on');
  $('findMob').value = '';
  $('foundDiv').style.display = 'none';
  hideErr('findErr');
  setTimeout(() => $('findMob').focus(), 100);
}
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
      $('fSb').textContent = `${r.mobile} \u00B7 ${r.bank}`;
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
  $('cpSb').textContent = `${RECIPIENT.mobile} \u00B7 ${RECIPIENT.bank}`;
  $('cpAv').textContent = RECIPIENT.name[0];
  $('cpAv').style.background = 'linear-gradient(135deg, var(--accent), #4f46e5)';
  closeFind();
}

function initiateSend() {
  if (!RECIPIENT) return showToast('Select a recipient first', 'error');
  const amount = parseFloat($('sAmt').value);
  if (!amount || amount <= 0) return showToast('Enter a valid amount', 'error');
  const note = $('sNote').value.trim();
  PENDING_PAYMENT = { receiver_mobile: RECIPIENT.mobile, amount, note };
  $('pcSub').innerHTML = `Sending <strong>${formatCurrency(amount)}</strong> to <strong>${RECIPIENT.name}</strong>`;
  openPinConfirm();
}

function openPinConfirm() {
  PIN_BUFFER = '';
  updatePinDots();
  $('pcErr').textContent = '';
  $('pinOverlay').classList.add('on');
}

function cancelPin() {
  $('pinOverlay').classList.remove('on');
  PIN_BUFFER = '';
  PENDING_PAYMENT = null;
}

function pinInput(digit) {
  if (PIN_BUFFER.length >= 4) return;
  PIN_BUFFER += digit;
  updatePinDots();
  if (PIN_BUFFER.length === 4) {
    setTimeout(() => verifyPinAndSend(), 200);
  }
}

function pinDelete() {
  PIN_BUFFER = PIN_BUFFER.slice(0, -1);
  updatePinDots();
  $('pcErr').textContent = '';
}

function updatePinDots() {
  const dots = $('pinDots').querySelectorAll('.pin-dot');
  dots.forEach((d, i) => {
    d.classList.remove('filled', 'error');
    if (i < PIN_BUFFER.length) d.classList.add('filled');
  });
}

function showPinError(msg) {
  $('pcErr').textContent = msg;
  const dots = $('pinDots').querySelectorAll('.pin-dot');
  dots.forEach(d => { d.classList.remove('filled'); d.classList.add('error'); });
  setTimeout(() => {
    PIN_BUFFER = '';
    updatePinDots();
    $('pcErr').textContent = '';
  }, 1500);
}

async function verifyPinAndSend() {
  try {
    await api('/login', { mobile: ME.mobile, pin: PIN_BUFFER });
  } catch (e) {
    showPinError('Incorrect PIN. Try again.');
    return;
  }

  $('pinOverlay').classList.remove('on');
  const btn = $('sendBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Processing...';

  try {
    const r = await api('/pay', PENDING_PAYMENT);
    showResult(r);
    loadBal();
    loadHistory();
  } catch (e) {
    showToast(e.message, 'error');
  }

  btn.disabled = false;
  btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:middle;margin-right:8px"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>Send Payment';
  PIN_BUFFER = '';
  PENDING_PAYMENT = null;
}

async function biometricAuth() {
  showToast('Use PIN to confirm payment', 'error');
  PIN_BUFFER = '';
  updatePinDots();
}

function showResult(r) {
  const ok = r.state === 1;
  $('rico').textContent = ok ? '\u2714' : '\u2718';
  $('rico').style.color = ok ? 'var(--green)' : 'var(--red)';
  $('rtitle').textContent = ok ? 'Payment Successful' : 'Payment Failed';
  $('rtitle').style.color = ok ? 'var(--green)' : 'var(--red)';
  $('rsub').textContent = ok ? `To ${r.receiver_name}` : r.reason;
  $('ramt').textContent = formatCurrency(r.amount);
  $('ramt').style.color = ok ? 'var(--green)' : 'var(--red)';

  let bupd = '';
  if (r.new_sender_bal !== null && r.new_sender_bal !== undefined) {
    bupd += `<div class="bucard"><div class="bunm">Your Balance</div><div class="bubal">${formatCurrency(r.new_sender_bal)}</div></div>`;
  }
  if (false) {
  }
  $('bupd').innerHTML = bupd;

  const stateClass = r.state === 1 ? 'sattva' : 'tamas';
  const stateLabel = r.state === 1 ? '+1 Sattva' : '-1 Tamas';
  $('rdets').innerHTML = `
    <div class="rdrow"><span class="rdlbl">Transaction ID</span><span class="rdval">${(r.tx_id||'').substring(0,8)}...</span></div>
    <div class="rdrow"><span class="rdlbl">State</span><span class="rdval"><span class="state-badge ${stateClass}">${stateLabel}</span></span></div>
    <div class="rdrow"><span class="rdlbl">Transit Time</span><span class="rdval">${r.transit_ms}ms</span></div>
    <div class="rdrow"><span class="rdlbl">Signature</span><span class="rdval">${r.signature||'\u2014'}</span></div>
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
  showToast('Signed out successfully', 'success');
}

function goProfile() {
  show('scrProfile');
  const av = $('pAvatar');
  av.textContent = (ME.name || '?')[0];
  av.style.background = ME.avatar_color || 'linear-gradient(135deg, var(--accent), #4f46e5)';
  $('pName').textContent = ME.name || '\u2014';
  $('pMobile').textContent = ME.mobile || '\u2014';

  const kycLevel = ME.kyc_level || 0;
  $('pKyc').textContent = `Level ${kycLevel}`;
  const badge = $('pKycBadge');
  if (kycLevel >= 2) {
    badge.innerHTML = '<span class="kyc-badge verified">Fully Verified</span>';
  } else if (kycLevel === 1) {
    badge.innerHTML = '<span class="kyc-badge pending">Partially Verified</span>';
  } else {
    badge.innerHTML = '<span class="kyc-badge unverified">Not Verified</span>';
  }

  const portalEl = $('portalLink');
  if (portalEl) portalEl.style.display = ME.role === 'admin' ? 'block' : 'none';

  setNav('profile');
  loadKycStatus();
  loadAccounts();
}

async function loadAccounts() {
  const container = $('pAccountsList');
  try {
    const accounts = await api('/accounts');
    ME.accounts = accounts;
    if (!accounts.length) {
      container.innerHTML = '<div style="color:var(--dim);font-size:13px;padding:12px 0">No accounts linked yet. Add one below.</div>';
      return;
    }
    container.innerHTML = accounts.map(a => {
      const bankLabel = a.bank_name || a.bank_id;
      const typeLabel = (a.account_type || 'savings').charAt(0).toUpperCase() + (a.account_type || 'savings').slice(1);
      const primaryBadge = a.is_primary ? '<span style="background:var(--accent);color:#fff;font-size:10px;padding:2px 6px;border-radius:6px;margin-left:6px;font-weight:600">PRIMARY</span>' : '';
      const ifscLine = a.branch_ifsc ? `<div style="font-size:11px;color:var(--dim);margin-top:2px">IFSC: ${a.branch_ifsc}</div>` : '';
      const labelLine = a.account_label ? ` \u00B7 ${a.account_label}` : '';
      return `<div style="background:var(--card);border:1px solid var(--bdr);border-radius:14px;padding:14px;margin-bottom:8px;position:relative">
        <div style="display:flex;align-items:center;gap:10px">
          <div style="width:38px;height:38px;border-radius:10px;background:var(--blue-bg);color:var(--blue);display:flex;align-items:center;justify-content:center;font-size:18px">&#127974;</div>
          <div style="flex:1;min-width:0">
            <div style="font-size:14px;font-weight:600;color:var(--txt)">${bankLabel}${primaryBadge}</div>
            <div style="font-size:12px;color:var(--dim);font-family:'JetBrains Mono',monospace;margin-top:2px">${a.account_id}</div>
            <div style="font-size:11px;color:var(--dim);margin-top:2px">${typeLabel}${labelLine}</div>
            ${ifscLine}
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            ${!a.is_primary ? `<button onclick="setPrimaryAccount(${a.id})" style="background:none;border:1px solid var(--accent);color:var(--accent);font-size:10px;padding:4px 8px;border-radius:6px;cursor:pointer">Set Primary</button>` : ''}
            ${!a.is_primary ? `<button onclick="removeAccount(${a.id})" style="background:none;border:1px solid var(--red);color:var(--red);font-size:10px;padding:4px 8px;border-radius:6px;cursor:pointer">Remove</button>` : ''}
          </div>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = '<div style="color:var(--dim);font-size:13px;padding:12px 0">Could not load accounts</div>';
  }
}

async function setPrimaryAccount(id) {
  try {
    await api('/accounts/set_primary', { account_id: id });
    showToast('Primary account updated', 'success');
    loadAccounts();
    loadBal();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function removeAccount(id) {
  if (!confirm('Remove this account?')) return;
  try {
    await api('/accounts/' + id, null, 'DELETE');
    showToast('Account removed', 'success');
    loadAccounts();
    loadBal();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function showAddAccount() {
  $('addAccountModal').classList.add('on');
  $('addAccId').value = '';
  $('addAccIfsc').value = '';
  $('addAccLabel').value = '';
  $('addAccType').value = 'savings';
  hideErr('addAccErr');
  loadAddAccBanks();
}

function closeAddAccount() {
  $('addAccountModal').classList.remove('on');
}

async function loadAddAccBanks() {
  try {
    const banks = await api('/banks');
    const grid = $('addAccBankGrid');
    grid.innerHTML = '';
    banks.forEach(b => {
      const card = document.createElement('div');
      card.className = 'bcard';
      card.onclick = () => {
        grid.querySelectorAll('.bcard').forEach(c => c.classList.remove('sel'));
        card.classList.add('sel');
        card.dataset.bankId = b.id;
      };
      card.dataset.bankId = b.id;
      card.innerHTML = `
        <div class="bico">${b.icon}</div>
        <div class="binf">
          <div class="bnm">${b.name}</div>
          <div class="bsh">${b.short} \u00B7 ${b.label}</div>
          <div class="bonl ${b.online ? 'online' : 'offline'}">${b.online ? 'Online' : 'Offline'}</div>
        </div>
        <div class="bchk">&#10003;</div>
      `;
      grid.appendChild(card);
    });
  } catch (e) {
    $('addAccBankGrid').innerHTML = '<div style="color:var(--red);font-size:13px;padding:12px">Failed to load banks</div>';
  }
}

async function doAddAccount() {
  hideErr('addAccErr');
  const sel = document.querySelector('#addAccBankGrid .bcard.sel');
  if (!sel) return showErr('addAccErr', 'Select a bank first');
  const bankId = sel.dataset.bankId;
  const accountId = $('addAccId').value.trim();
  if (!accountId) return showErr('addAccErr', 'Enter your account number');
  const ifsc = $('addAccIfsc').value.trim() || null;
  const accountType = $('addAccType').value;
  const label = $('addAccLabel').value.trim() || null;

  const btn = $('addAccBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Verifying...';
  try {
    const r = await api('/accounts/add', {
      bank_id: bankId,
      account_id: accountId,
      branch_ifsc: ifsc,
      account_type: accountType,
      account_label: label
    });
    showToast('Account added: ' + r.holder + ' @ ' + r.bank_name, 'success');
    closeAddAccount();
    loadAccounts();
    loadBal();
  } catch (e) {
    showErr('addAccErr', e.message);
  }
  btn.disabled = false;
  btn.textContent = 'Verify & Add Account';
}

async function loadKycStatus() {
  try {
    const r = await api('/kyc/status');
    $('pKyc').textContent = `Level ${r.kyc_level} \u2014 ${r.kyc_status}`;
    const docList = $('kycDocs');
    if (r.documents.length) {
      docList.innerHTML = r.documents.map(d => `
        <div class="txi" style="margin-bottom:6px">
          <div class="txic" style="background:var(--blue-bg);color:var(--blue);font-size:14px">&#128196;</div>
          <div class="txinf">
            <div class="txnm">${d.type}</div>
            <div class="txdt">${d.number} &middot; ${d.status}</div>
          </div>
        </div>
      `).join('');
    } else {
      docList.innerHTML = '<div style="color:var(--dim);font-size:13px;padding:8px 0">No documents submitted yet</div>';
    }
  } catch (e) {}
}

async function submitKyc() {
  const docType = $('kycDocType').value;
  const docNum = $('kycDocNum').value.trim();
  if (!docNum) return showToast('Enter document number', 'error');
  hideErr('kycErr');
  try {
    await api('/kyc/submit', { document_type: docType, document_number: docNum });
    $('kycDocNum').value = '';
    showToast('Document submitted for verification', 'success');
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

  document.addEventListener('keydown', (e) => {
    if ($('pinOverlay').classList.contains('on')) {
      if (e.key >= '0' && e.key <= '9') pinInput(e.key);
      else if (e.key === 'Backspace') pinDelete();
      else if (e.key === 'Escape') cancelPin();
    }
  });
});
