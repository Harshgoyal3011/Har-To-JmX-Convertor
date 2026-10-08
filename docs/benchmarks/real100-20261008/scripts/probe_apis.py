"""Read-only reachability of documented public API endpoints, not benchmark HARs."""
import asyncio,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent/'benchmark-deps'))
from playwright.async_api import async_playwright

async def main():
 rows=[];sem=asyncio.Semaphore(4)
 targets=json.loads((ROOT/(sys.argv[1] if len(sys.argv)>1 else 'api_targets.json')).read_text(encoding='utf-8'))
 skip={'Open Exchange Rates public','Open Library Covers','Socrata NYC','GeoNames','OpenRouteService public demo'}
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
  async def one(spec):
   async with sem:
    page=await browser.new_page();row={**spec,'utc':datetime.now(timezone.utc).isoformat()}
    try:
     res=await page.goto(spec['base']+spec['probe'],wait_until='domcontentloaded',timeout=25000)
     text=await res.text();row['status']=res.status;row['content_type']=res.headers.get('content-type');row['body']=text[:15000];row['final_url']=page.url
     try:row['json']=json.loads(text[:2000000])
     except ValueError:pass
    except Exception as exc:row['error']=str(exc)[:200]
    finally:
     rows.append(row);await page.close();(ROOT/(sys.argv[2] if len(sys.argv)>2 else 'API_REACHABILITY.json')).write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8');print(spec['application'],row.get('status'),row.get('error','')[:90],flush=True)
  await asyncio.gather(*(one(s) for s in targets if s['application'] not in skip));await browser.close()
asyncio.run(main())
