"""Browser-level acceptance checks. Run while the app and its real services are up."""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import API_KEY,ROOT

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox','--single-process','--no-zygote'])
    page=browser.new_page(viewport={'width':1440,'height':1100})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:8000',wait_until='networkidle')
    page.fill('#token',API_KEY);page.click('#connect')
    expect(page.locator('#consistent')).to_contain_text('Verified',timeout=30000)
    expect(page.locator('#client-badge')).to_contain_text('sandbox-operator')
    page.fill('#key-label','Browser acceptance key');page.click('#create-api-key')
    expect(page.locator('#secret-panel')).to_be_visible()
    one_time_secret=page.locator('#one-time-secret').inner_text()
    assert one_time_secret.startswith('pg_live_') and len(one_time_secret)>32
    prefix=one_time_secret[:14]
    row=page.locator('#api-keys tr',has_text=prefix)
    expect(row).to_contain_text('ACTIVE')
    assert one_time_secret not in row.inner_text(), 'Full secret leaked into key list'
    page.on('dialog',lambda dialog:dialog.accept())
    row.get_by_text('Revoke').click()
    expect(row).to_contain_text('REVOKED')
    # Screenshot excludes the credential panel. It contains only synthetic accounts.
    page.locator('#auth').evaluate("el=>el.style.visibility='hidden'")
    page.screenshot(path=str(ROOT/'evidence/dashboard-desktop.png'),full_page=True)
    page.locator('#auth').evaluate("el=>el.style.visibility='visible'")
    page.click('#run-all')
    expect(page.locator('#test-summary')).to_have_text('6 / 6 passed',timeout=60000)
    results=page.locator('#test-output').inner_text()
    assert results.count('RESULT: PASS')==6,results
    page.fill('#amount','2.50');page.click('#new-key');page.click('#submit-payment')
    expect(page.locator('#payment-result')).to_contain_text('SUCCEEDED')
    first=json.loads(page.locator('#payment-result').inner_text())
    expect(page.locator('#submit-payment')).to_be_enabled()
    page.click('#retry-form')
    expect(page.locator('#payment-result')).to_contain_text('"replay": "true"')
    repeat=json.loads(page.locator('#payment-result').inner_text())
    assert first['body']['id']==repeat['body']['id']
    page.reload(wait_until='networkidle')
    expect(page.locator('#consistent')).to_contain_text('Verified',timeout=30000)
    assert page.input_value('#key')==first['body']['idempotency_key']
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile layout overflows'
    assert not errors,errors
    (ROOT/'evidence/browser-results.json').write_text(json.dumps({'status':'PASS','client_identity_visible':True,'one_time_key_creation':True,'full_secret_absent_from_list':True,'revocation':True,'six_dashboard_tests':'6 / 6 passed','form_payment_and_retry_same_id':True,'key_persisted_after_reload':True,'mobile_width':390,'javascript_errors':errors,'test_log':results},indent=2))
    print('Browser acceptance: client identity, key create/revoke, six demonstrations, payment retry, reload, mobile layout PASS')
    browser.close()
