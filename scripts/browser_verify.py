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
    (ROOT/'evidence/browser-results.json').write_text(json.dumps({'status':'PASS','six_dashboard_tests':'6 / 6 passed','form_payment_and_retry_same_id':True,'key_persisted_after_reload':True,'mobile_width':390,'javascript_errors':errors,'test_log':results},indent=2))
    print('Browser acceptance: six demonstrations, form payment, same-key retry, reload recovery, mobile layout PASS')
    browser.close()
