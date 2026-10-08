"""Native Chromium recording of documented public read API journeys.

Every HAR entry is browser-generated traffic to the real service. No constructed
HAR entries, route interception, mocked responses, or production writes.
"""
import asyncio,hashlib,json,re,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote,urlsplit
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent/'benchmark-deps'))
from playwright.async_api import async_playwright

async def main():
 specs={r['application']:r for r in json.loads((ROOT/'api_targets.json').read_text())}
 plans=json.loads((ROOT/(sys.argv[1] if len(sys.argv)>1 else 'api_workflows.json')).read_text())
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
  for num,plan in enumerate(plans):
   slug=re.sub('[^a-z0-9]+','-',plan['application'].lower());ident=plan.get('id',f'api-{num+1:03d}-{slug}')
   folder=ROOT/'staging'/ident
   if (folder/'capture.json').exists():continue
   folder.mkdir(parents=True,exist_ok=True);spec=specs[plan['application']]
   ctx=await browser.new_context(record_har_path=str(folder/'raw.har'),record_har_content='embed',record_har_mode='full')
   page=await ctx.new_page();record={**plan,'id':ident,'permission_url':spec['permission'],'started_utc':datetime.now(timezone.utc).isoformat(),'capture_method':'Native browser navigation to documented public API; no mocks or fabricated HAR; read-only selection workflows','actions':[],'status':'CAPTURE_LIMITED'}
   data=None;selected=None;source=None
   try:
    for i,step in enumerate(plan['steps']):
     await asyncio.sleep(1.1)
     url=step['path'];selection=None
     if 'select' in step:
      sel=step['select'];value=data
      for key in sel['path']:value=value[key]
      if 'key' in sel:value=list(value)[sel['key']]
      if value is None or str(value)=='':raise ValueError('Selected source value absent')
      selected=str(value)
      if sel.get('value_transform')=='last_path_segment':selected=selected.rstrip('/').rsplit('/',1)[-1]
      if sel.get('value_transform')=='strip_leading_slash':selected=selected.lstrip('/')
      selection={'value':value,'source_step':i-1,'source_url':source,'source_response_path':sel['path'],'selected_dict_key_index':sel.get('key'),'known_transform':sel.get('value_transform','identity'),'consumer_spelling':selected,'classification':sel['kind'],'reason':'Explicit documented read-workflow selection from the preceding real response; existing catalog identity, except explicitly issued session token.'}
     if '{selected}' in url:
      if selected is None:raise ValueError('No selected response value')
      # URLs explicitly returned by an API are navigated directly after origin check.
      encoded=selected if step.get('select',{}).get('absolute') or selected.startswith('https://') else quote(selected,safe='/' if step.get('select',{}).get('encoding')=='path_preserve_slash' or selected.startswith('/') else '')
      url=url.replace('{selected}',encoded)
     if not url.startswith('https://'):url=spec['base'].rstrip('/')+'/'+url.lstrip('/')
     assert urlsplit(url).hostname==urlsplit(spec['base']).hostname, 'Returned URL must stay on approved public API origin'
     action={'index':i,'op':'documented_api_navigation','method':'GET','url':url,'inputs':step.get('inputs',{}),'selection':selection,'started_utc':datetime.now(timezone.utc).isoformat()}
     res=await page.goto(url,wait_until='domcontentloaded',timeout=30000);text=await res.text()
     action.update(status=res.status,response_sha256=hashlib.sha256(text.encode()).hexdigest(),response_content_type=res.headers.get('content-type'),response_excerpt=text[:200])
     record['actions'].append(action)
     if res.status>=400:raise ValueError(f'HTTP {res.status}; denied/unavailable/rate control, no bypass')
     if any(x in text[:10000].lower() for x in ['just a moment','verify you are human','captcha challenge']):raise ValueError('Challenge, no bypass')
     data=json.loads(text);source=url
     if isinstance(data,dict) and (data.get('response_code',0)!=0 or data.get('error') or data.get('success') is False):raise ValueError('API error acknowledgement, not completed')
    record['status']='COMPLETED_PENDING_INDEPENDENT_AUDIT';record['final_url']=page.url
    await page.screenshot(path=str(folder/'final.png'))
   except Exception as exc:record['error']=str(exc)[:700]
   finally:
    await ctx.close();raw=(folder/'raw.har').read_bytes();entries=json.loads(raw)['log']['entries']
    record.update(finished_utc=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest(),request_count=len(entries),representation_types=['JSON response; URL query/path request'])
    (folder/'capture.json').write_text(json.dumps(record,indent=2,ensure_ascii=False),encoding='utf-8');print(ident,record['status'],record.get('error','')[:120],flush=True)
  await browser.close()
asyncio.run(main())
