"""Read-only discovery of official public demo landing pages; no account creation."""
import asyncio,json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT.parent/'benchmark-deps'))
from playwright.async_api import async_playwright
targets=[
 ('ERPNext','https://demo.erpnext.com/'),('Frappe CRM','https://demo.crm.frappe.cloud/'),
 ('Akaunting','https://akaunting.com/demo'),('InvoicePlane','https://www.invoiceplane.com/demo'),
 ('Invoice Ninja','https://demo.invoiceninja.com/'),('Firefly III','https://demo.firefly-iii.org/'),
 ('Monica','https://demo.monicahq.com/'),('Grocy','https://demo.grocy.info/'),
 ('GLPI','https://demo.glpi-project.org/'),('iTop','https://demo.combodo.com/simple/'),
 ('OpenEMR','https://www.open-emr.org/wiki/index.php/OpenEMR_Demo'),
 ('OpenMRS','https://demo.openmrs.org/'),('Bahmni','https://www.bahmni.org/demo'),
 ('Rukovoditel','https://www.rukovoditel.net/demo.php'),('CiviCRM','https://civicrm.org/demo'),
 ('ProjeQtOr','https://demo.projeqtor.org/'),('Leantime','https://demo.leantime.io/'),
 ('Kanboard','https://demo.kanboard.org/'),('Wekan','https://wekan.github.io/'),
 ('Moodle','https://sandbox.moodledemo.net/'),('Chamilo','https://campus.chamilo.org/'),
 ('eLabFTW','https://demo.elabftw.net/'),('Nextcloud','https://try.nextcloud.com/'),
 ('OpenCart','https://www.opencart.com/index.php?route=cms/demo'),
 ('PrestaShop','https://demo.prestashop.com/'),('MantisBT','https://www.mantisbt.org/demo.php'),
 ('Redmine','https://demo.redmine.org/'),('DoliCloud','https://www.dolicloud.com/en-demo.php'),
 ('Tine','https://www.tine-groupware.de/en/demo/'),('EGroupware','https://www.egroupware.org/en/demo'),
 ('ZenTao','https://www.zentao.pm/demo/'),('Sentrifugo','https://www.sentrifugo.com/demo'),
 ('SolidInvoice','https://demo.solidinvoice.co/'),('Crater','https://demo.craterapp.com/'),
 ('OroCRM','https://oroinc.com/orocrm/demo/'),('Zammad','https://zammad.org/demo'),
 ('FreeScout','https://demo.freescout.net/'),('osTicket','https://osticket.com/demo/'),
 ('Dolibarr excluded','https://www.dolibarr.org/'),
]
async def main():
 if len(sys.argv)>1:
  targets[:]=json.loads((ROOT/sys.argv[1]).read_text(encoding='utf-8'))
 output=ROOT/(sys.argv[2] if len(sys.argv)>2 else 'DEMO_RESEARCH.json')
 exclusion=json.loads((ROOT/'HARD_EXCLUSION_SET.json').read_text());old={n.lower() for n in exclusion['excluded_applications']}
 sem=asyncio.Semaphore(4);rows=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
  async def inspect(app,url):
   if app.lower() in old or 'excluded' in app:return
   async with sem:
    page=await browser.new_page()
    row={'application':app,'url':url,'inspected_utc':datetime.now(timezone.utc).isoformat()}
    try:
     response=await page.goto(url,wait_until='domcontentloaded',timeout=22000)
     await asyncio.sleep(3)
     row.update(status=response.status if response else None,final_url=page.url,title=await page.title(),body=(await page.locator('body').inner_text(timeout=3000))[:16000],
      links=await page.locator('a[href]').evaluate_all('(es)=>es.map(e=>({text:e.innerText||e.textContent||"",href:e.href})).filter(e=>e.text.trim()).slice(0,250)'),
      controls=await page.locator('input,button').evaluate_all('(es)=>es.map(e=>({tag:e.tagName,name:e.name,type:e.type,text:e.innerText,placeholder:e.placeholder})).slice(0,35)'))
    except Exception as e:row['error']=str(e).split('Call log:')[0][:600]
    finally:
     rows.append(row);await page.close();output.write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
     print(app,row.get('status'),row.get('title',row.get('error',''))[:100],flush=True)
  await asyncio.gather(*(inspect(*t) for t in targets));await browser.close()
asyncio.run(main())
