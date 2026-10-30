'use strict';
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('payguard-token') || '';
let lastRequest = JSON.parse(localStorage.getItem('payguard-last-request') || 'null');
let busy = false;
const outcomes = {};
const money = p => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'}).format(p / 100);
const freshKey = () => 'pg-' + crypto.randomUUID();
const print = (id, data) => { $(id).textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2); };
const notice = message => { $('notice').textContent = message; };
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {...options, headers:{Authorization:'Bearer ' + token, ...(options.body ? {'Content-Type':'application/json'} : {}), ...options.headers}});
  const body = await response.json();
  return {code:response.status, body, replay:response.headers.get('Idempotency-Replayed'), source:response.headers.get('Idempotency-Source')};
}
async function get(path) { const r=await api(path); if(r.code!==200) throw new Error(r.body.detail || 'Request failed'); return r.body; }
function send(body, key, fault, signal) { return api('/payments', {method:'POST', body:JSON.stringify(body), headers:{'Idempotency-Key':key, ...(fault ? {'X-Demo-Fault':fault} : {})}, signal}); }
function balances(accounts) { return Object.fromEntries(accounts.map(a=>[a.id,a.balance])); }
function equal(a,b) { return JSON.stringify(a) === JSON.stringify(b); }
async function refresh() {
  const h = await fetch('/api/health').then(r=>r.json());
  $('service').textContent = h.database==='up' ? (h.redis==='up' ? '● PostgreSQL + Redis online' : '● Database online · Redis fallback') : '● Database unavailable';
  if (!token) return;
  const [accounts, payments, audit, ledger] = await Promise.all([get('/accounts'),get('/payments'),get('/audit'),get('/ledger')]);
  $('auth').classList.add('connected');
  $('total').textContent=money(audit.current_total); $('succeeded').textContent=audit.stats.succeeded;
  $('volume').textContent=money(audit.stats.volume); $('consistent').textContent=audit.consistent ? 'Verified ✓' : 'Mismatch';
  $('integrity-note').textContent=audit.consistent ? 'All balances match the ledger' : 'Inspect database evidence below';
  const selected=[$('sender').value,$('receiver').value];
  $('accounts').replaceChildren(); $('sender').replaceChildren(); $('receiver').replaceChildren();
  accounts.forEach(a=>{
    const card=document.createElement('article');card.className='account';
    const id=document.createElement('span');id.textContent='ACCOUNT 00'+a.id;
    const curr=document.createElement('span');curr.className='currency';curr.textContent=a.currency;
    const name=document.createElement('strong');name.textContent=a.name;
    const value=document.createElement('span');value.className='money';value.textContent=money(a.balance);
    card.append(id,curr,name,value);$('accounts').append(card);
    for(const select of [$('sender'),$('receiver')]){const option=document.createElement('option');option.value=a.id;option.textContent=a.name;select.append(option);}
  });
  $('sender').value=selected[0]||'1';$('receiver').value=selected[1]||'2';
  $('transactions').replaceChildren();
  if(!payments.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=5;td.textContent='No payments yet. Create your first simulated transfer.';tr.append(td);$('transactions').append(tr);}
  payments.forEach(p=>{
    const tr=document.createElement('tr');
    const payment=document.createElement('td');payment.textContent=p.id.slice(0,8)+'…';const key=document.createElement('small');key.textContent=p.idempotency_key;payment.append(key);
    const route=document.createElement('td');route.textContent=p.sender_id+' → '+p.receiver_id;
    const amount=document.createElement('td');amount.textContent=money(p.amount);
    const status=document.createElement('td');const badge=document.createElement('span');badge.className='status '+p.status;badge.textContent=p.status;status.append(badge);
    const date=document.createElement('td');date.textContent=new Date(p.created_at).toLocaleTimeString();
    tr.append(payment,route,amount,status,date);$('transactions').append(tr);
  });
  print('audit-output',audit);print('ledger-output',ledger);
}
$('key').value=freshKey();
if(lastRequest){$('key').value=lastRequest.key;$('amount').value=(lastRequest.body.amount/100).toFixed(2);}
$('token').value=token;
$('connect').onclick=async()=>{token=$('token').value.trim();sessionStorage.setItem('payguard-token',token);try{await refresh();notice('Sandbox connected. All amounts are simulated.');if(lastRequest){$('sender').value=lastRequest.body.sender_id;$('receiver').value=lastRequest.body.receiver_id;}}catch(e){notice(e.message);}};
$('disconnect').onclick=()=>{sessionStorage.removeItem('payguard-token');token='';$('token').value='';$('auth').classList.remove('connected');location.reload();};
$('new-key').onclick=()=>{$('key').value=freshKey();notice('New key generated. Submitting will create a new payment.');};
function formBody(){
  const raw=$('amount').value.trim();
  if(!/^\d+(\.\d{1,2})?$/.test(raw)) throw new Error('Enter rupees with at most two decimal places.');
  const [whole,fraction='']=raw.split('.');const amount=Number(whole)*100+Number(fraction.padEnd(2,'0'));
  if(!Number.isSafeInteger(amount)||amount<=0||amount>100000000)throw new Error('Amount must be between ₹0.01 and ₹10,00,000.');
  return {sender_id:Number($('sender').value),receiver_id:Number($('receiver').value),amount,currency:'INR'};
}
async function submit(saved){
  if(busy)return;busy=true;$('submit-payment').disabled=true;
  try{
    if(!token)throw new Error('Connect your sandbox first.');
    const request=saved||{body:formBody(),key:$('key').value};
    lastRequest=request;localStorage.setItem('payguard-last-request',JSON.stringify(request));
    const r=await send(request.body,request.key);print('payment-result',r);
    notice(r.body.status==='SUCCEEDED'?(r.replay==='true'?'Original result returned. No additional debit.':'Payment committed successfully.'):(r.body.failure_code||JSON.stringify(r.body.detail)));
    await refresh();
  }catch(e){print('payment-result',e.message);notice('Outcome may be unknown. Retry last submitted request using the same key. '+e.message);}
  finally{busy=false;$('submit-payment').disabled=false;}
}
$('payment-form').onsubmit=e=>{e.preventDefault();submit();};
$('retry-form').onclick=()=>lastRequest?submit(lastRequest):notice('Submit a payment first.');
$('refresh').onclick=()=>refresh().catch(e=>notice(e.message));
$('audit-button').onclick=()=>refresh().then(()=>notice('Database audit refreshed.')).catch(e=>notice(e.message));
function assert(ok,message){if(!ok)throw new Error(message);}
async function runTest(name){
  if(!token)throw new Error('Connect your sandbox first.');
  const before=balances(await get('/accounts'));const beforeAudit=await get('/audit');
  const key=freshKey();const body={sender_id:1,receiver_id:2,amount:100,currency:'INR'};
  const lines=['TEST: '+name,'Key: '+key,'Before balances (paise): '+JSON.stringify(before)];
  let expected={...before};let response;
  if(['normal','duplicate','retry','concurrent'].includes(name))assert(before[1]>=1200,'Sender needs at least ₹12. Transfer funds back from account 2 or 3.');
  if(name==='normal'){
    response=await send(body,key);assert(response.code===201&&response.body.status==='SUCCEEDED','Expected a new successful payment');
    expected[1]-=100;expected[2]+=100;lines.push('Expected: one successful ₹1 payment.');
  }else if(name==='duplicate'){
    const r=await Promise.all([send(body,key),send(body,key)]);response=r;
    assert(r.every(x=>[200,201].includes(x.code))&&r[0].body.id===r[1].body.id&&r.some(x=>x.replay==='true'),'Expected same payment ID and a replay');
    expected[1]-=100;expected[2]+=100;lines.push('Expected: two requests, one payment ID, one ₹1 debit.');
  }else if(name==='concurrent'){
    response=await Promise.all(Array.from({length:12},()=>send(body,freshKey())));
    assert(response.every(x=>x.code===201&&x.body.status==='SUCCEEDED'),'All twelve payments should succeed');
    assert(new Set(response.map(x=>x.body.id)).size===12,'Expected twelve distinct payment IDs');
    expected[1]-=1200;expected[2]+=1200;lines.push('Expected: 12 parallel ₹1 payments, exact ₹12 debit.');
  }else if(name==='retry'){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),250);let lost=false;
    try{await send(body,key,'delayed-response',controller.signal);}catch(e){if(e.name==='AbortError')lost=true;else throw e;}finally{clearTimeout(timer);}
    assert(lost,'Client should time out before the delayed response');
    response=await send(body,key);assert(response.body.status==='SUCCEEDED','Retry must settle once');
    const stored=await get('/payments/by-key/'+key);assert(stored.id===response.body.id,'Stored result must match retry');
    expected[1]-=100;expected[2]+=100;lines.push('Expected: aborted response, retry with same key, one ₹1 debit.');
  }else if(name==='insufficient'){
    body.amount=before[1]+1;response=await send(body,key);
    assert(response.code===422&&response.body.failure_code==='INSUFFICIENT_FUNDS','Expected insufficient funds');
    const replay=await send(body,key);assert(replay.body.id===response.body.id&&replay.replay==='true','Failed result should also replay');
    lines.push('Expected: FAILED status, no balance changes, failure replays.');
  }else if(name==='rollback'){
    response=await send(body,key,'rollback');assert(response.code===503,'Injected rollback must return 503');
    const status=await api('/payments/by-key/'+key);assert(status.code===404,'Rolled-back payment must not be committed');
    lines.push('Expected: 503 after debit, no payment record and no balance changes.');
  }
  const after=balances(await get('/accounts'));const audit=await get('/audit');
  assert(equal(expected,after),'Balance mismatch. Expected '+JSON.stringify(expected)+' observed '+JSON.stringify(after));
  assert(audit.consistent,'Ledger audit failed');
  const increment=name==='concurrent'?12:name==='rollback'?0:1;
  assert(audit.stats.total-beforeAudit.stats.total===increment,'Unexpected payment record count');
  lines.push('Expected balances: '+JSON.stringify(expected),'Actual balances: '+JSON.stringify(after),'New payment records: '+(audit.stats.total-beforeAudit.stats.total),'Consistent ledger: '+audit.consistent,'API response: '+JSON.stringify(response,null,2),'RESULT: PASS');
  return lines.join('\n');
}
async function executeTests(names){
  if(busy)return;busy=true;
  document.querySelectorAll('[data-test],#run-all,#submit-payment,#retry-form').forEach(b=>b.disabled=true);
  print('test-output','Executing against PostgreSQL and Redis…');let output=[];
  for(const name of names){
    $('badge-'+name).textContent='Running…';
    try{output.push(await runTest(name));outcomes[name]=true;$('badge-'+name).textContent='PASS · Verified';$('badge-'+name).className='test-badge pass';}
    catch(e){outcomes[name]=false;output.push('TEST: '+name+'\nRESULT: FAIL\n'+e.message);$('badge-'+name).textContent='FAIL · See evidence';$('badge-'+name).className='test-badge fail';}
    print('test-output',output.join('\n\n────────────────────────\n\n'));
  }
  $('test-summary').textContent=Object.values(outcomes).filter(Boolean).length+' / '+Object.keys(outcomes).length+' passed';
  try{await refresh();}catch(e){notice(e.message);}
  busy=false;document.querySelectorAll('[data-test],#run-all,#submit-payment,#retry-form').forEach(b=>b.disabled=false);
}
document.querySelectorAll('[data-test]').forEach(b=>b.onclick=()=>executeTests([b.dataset.test]));
$('run-all').onclick=()=>executeTests(['normal','duplicate','concurrent','retry','insufficient','rollback']);
function addAboutSection(){
  if($('about'))return;
  $('auth').querySelector('p').textContent='Paste API_KEY from your local .env file or the Render service environment. This operator can use all demo accounts.';
  const link=document.createElement('a');link.href='#about';link.textContent='i  About';document.querySelector('nav').append(link);
  const about=document.createElement('section');about.id='about';about.className='panel about';
  about.innerHTML='<div class="section-title"><div><p class="eyebrow">05 / PROJECT GUIDE</p><h2>About PayGuard</h2></div><span class="pill">Prototype</span></div><p class="about-lead">PayGuard is an academic payment-reliability prototype for simulated INR transfers. It demonstrates how a payment can be processed once when users click twice, requests run concurrently, or a response is lost.</p><div class="about-grid"><article class="about-card"><span class="about-icon">1</span><h3>Duplicate prevention</h3><p>Redis speeds up replay detection. PostgreSQL permanently enforces one payment per operator and idempotency key.</p></article><article class="about-card"><span class="about-icon">2</span><h3>Safe concurrency</h3><p>PostgreSQL transactions lock both account rows in a fixed order before checking and changing balances.</p></article><article class="about-card"><span class="about-icon">3</span><h3>Safe recovery</h3><p>Payment status, balances, and ledger entries commit together. Failures roll back; retries reuse the same key.</p></article></div><div class="about-how"><strong>Simple demo flow</strong><ol><li>Connect with the API key from your local <code>.env</code> file.</li><li>Run the six Reliability tests one at a time, or use Run all six tests.</li><li>Open Transactions and Verify ledger to explain the evidence.</li><li>Use the same idempotency key when retrying an uncertain request.</li></ol></div><p class="about-note"><strong>Important:</strong> This is local sandbox software. It moves no real money and is not a production bank or payment gateway.</p>';
  document.querySelector('footer').before(about);
  const styleLink=document.createElement('link');styleLink.rel='stylesheet';styleLink.href='/static/about.css';document.head.append(styleLink);
}
addAboutSection();
refresh().then(()=>{if(lastRequest){$('sender').value=lastRequest.body.sender_id;$('receiver').value=lastRequest.body.receiver_id;}}).catch(e=>notice(e.message));
