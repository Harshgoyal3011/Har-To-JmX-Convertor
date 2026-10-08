"""Record native UI journeys in official public demos; never synthesize requests."""
import asyncio, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'benchmark-deps'))
from playwright.async_api import async_playwright

ALLOWED = {'demo.invoiceplane.com', 'demo.grocy.info', 'sandbox.moodledemo.net',
           'demo.elabftw.net', 'demo.opencart.com', 'try.nextcloud.com',
           'demo.egroupware.net', 'demo.combodo.com', 'demo.projeqtor.org',
           'demo.invoiceninja.com', 'demo.prestashop.com', 'demo.openemr.io',
           'demo.[REDACTED:6f0309fea1db].com', 'try.vikunja.io', 'demo.easyappointments.org',
           'demo.bookedscheduler.com', 'demo.rei3.de', 'demo.frontaccounting.eu',
           'demo.netbox.dev', 'demo.invoiceplane.com', 'demo.standard.mybahmni.in',
           'demo.invoiceshelf.com', 'v2.demo.sylius.com'}

async def inspect(page):
    frames = []
    for frame in page.frames:
        try:
            frames.append({'url': frame.url, 'body': (await frame.locator('body').inner_text(timeout=2000))[:18000],
                'controls': await frame.locator('input,textarea,select,button,a[href]').evaluate_all("""es => es.map(e => ({tag:e.tagName,id:e.id,name:e.name,type:e.type,text:(e.innerText||'').trim().slice(0,160),value:e.value,href:e.href,placeholder:e.placeholder,visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),options:e.tagName==='SELECT'?Array.from(e.options).map(o=>({text:o.text,value:o.value})):undefined})).filter(e=>e.visible||e.type==='hidden').sort((a,b)=>(a.tag==='A')-(b.tag==='A')).slice(0,500)""")})
        except Exception as exc:
            frames.append({'url':frame.url,'inspection_error':str(exc)[:200]})
    return {'url': page.url, 'title': await page.title(), 'frames': frames}

async def main():
    plans = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        for plan in plans:
            folder = ROOT / 'staging' / plan['id']; folder.mkdir(parents=True,exist_ok=True)
            record = {**plan,'started_utc':datetime.now(timezone.utc).isoformat(),'capture_method':'Playwright native Chromium UI; full embedded HAR; no request interception or fabricated traffic','actions':[],'status':'INSPECTION_ONLY'}
            context = await browser.new_context(record_har_path=str(folder/'raw.har'),record_har_content='embed',record_har_mode='full',viewport={'width':1440,'height':1000})
            page = await context.new_page(); page.set_default_timeout(12000)
            try:
                for index, step in enumerate(plan['steps']):
                    start = datetime.now(timezone.utc).isoformat()
                    action = {'index':index,'started_utc':start,**step,'url_before':page.url}
                    target = page
                    if 'frame' in step: target = next(f for f in page.frames if step['frame'] in f.url)
                    op = step['op']
                    if op == 'goto':
                        assert urlsplit(step['url']).hostname in ALLOWED, 'Target must be an approved public demo'
                        await page.goto(step['url'],wait_until='domcontentloaded',timeout=30000)
                    elif op == 'fill': await target.locator(step['selector']).fill(step['value'])
                    elif op == 'click': await target.locator(step['selector']).click()
                    elif op == 'select':
                        if 'label' in step: await target.locator(step['selector']).select_option(label=step['label'])
                        else: await target.locator(step['selector']).select_option(step['value'])
                    elif op == 'check': await target.locator(step['selector']).set_checked(step.get('value',True))
                    elif op == 'press': await target.locator(step['selector']).press(step['key'])
                    elif op == 'assert_text': await target.get_by_text(step['text'],exact=step.get('exact',False)).first.wait_for(state='visible')
                    elif op == 'wait': await asyncio.sleep(min(step.get('seconds',2),15))
                    else: raise ValueError(op)
                    if op in {'fill','select','check'}:
                        action['element_evidence']=await target.locator(step['selector']).evaluate("e => ({name:e.name,id:e.id,type:e.type,value:e.value,formAction:e.form?.action,formMethod:e.form?.method,selectedText:e.selectedOptions?Array.from(e.selectedOptions).map(o=>o.text):undefined})")
                    action['url_after']=page.url; action['completed_utc']=datetime.now(timezone.utc).isoformat();record['actions'].append(action)
                await asyncio.sleep(2)
                record['inspection']=await inspect(page)
                (folder/'final.html').write_text(await page.content(),encoding='utf-8')
                await page.screenshot(path=str(folder/'final.png'),full_page=False)
                if plan.get('completion_assertion'):
                    assertion=plan['completion_assertion']
                    await page.get_by_text(assertion,exact=False).first.wait_for(state='visible')
                    record['status']='COMPLETED_PENDING_INDEPENDENT_AUDIT'
            except Exception as exc:
                record['status']='CAPTURE_LIMITED';record['error']=str(exc)[:1200]
                record['inspection']=await inspect(page)
            finally:
                await context.close();record['finished_utc']=datetime.now(timezone.utc).isoformat()
                raw=(folder/'raw.har').read_bytes();record['sha256']=hashlib.sha256(raw).hexdigest()
                entries=json.loads(raw)['log']['entries'];record['request_count']=len(entries)
                record['representation_types']=sorted({e['request'].get('postData',{}).get('mimeType','') for e in entries if e['request'].get('postData')})
                (folder/'capture.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
                print(plan['id'],plan['application'],record['status'],record['request_count'],record.get('error','')[:150],flush=True)
        await browser.close()

asyncio.run(main())
