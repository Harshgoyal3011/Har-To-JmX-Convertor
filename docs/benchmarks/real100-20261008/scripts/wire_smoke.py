"""One-VU/two-iteration local replay of actual generated plans, no live writes."""
import base64,concurrent.futures,copy,csv,json,re,subprocess,threading,shutil
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
save=lambda p,v:p.write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')
manifest=read(ROOT/'REAL100_CORPUS_MANIFEST.json');byid={r['benchmark_id']:r for r in manifest['records']}
chosen=[1,2,3,4,5,6,7,8,14,19,26,28,32,34,36,43,47,58,64,85]
captures={};all_records=[];lock=threading.Lock()
for n in chosen:
 bid=f'REAL100-{n:03d}';captures[bid]=read(Path(byid[bid]['raw_har']))['log']['entries']
def header(parent,name,value):
 node=ET.SubElement(parent,'stringProp',name=name);node.text=value;return node
def fields(mime,body):
 if 'x-www-form-urlencoded' in mime:return parse_qsl(body.decode('utf-8',errors='replace'),keep_blank_values=True)
 if 'multipart/' in mime:
  msg=BytesParser(policy=default).parsebytes(('Content-Type: '+mime+'\r\n\r\n').encode()+body)
  if msg.is_multipart():return [(p.get_param('name',header='content-disposition'),p.get_payload(decode=True).decode('utf-8',errors='replace')) for p in msg.iter_parts() if not p.get_filename()]
 return []
class Receiver(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def receive(self):
  bid=self.headers.get('X-REAL100-Workflow');index=self.headers.get('X-REAL100-Request');body=self.rfile.read(int(self.headers.get('Content-Length','0')))
  if bid not in captures or index is None:self.send_error(400,'Unknown audit request');return
  index=int(index);entries=captures[bid];entry=entries[index]
  # Automatic redirect retains parent headers. Identify the actual next source
  # route from method/path rather than attributing it to that parent occurrence.
  current=urlsplit(self.path);expected=urlsplit(entry['request']['url'])
  if current.path!=expected.path:
   choices=[(i,e) for i,e in enumerate(entries) if e['request']['method']==self.command and urlsplit(e['request']['url']).path==current.path]
   if choices:index,entry=min(choices,key=lambda pair:abs(pair[0]-index))
  mime=self.headers.get('Content-Type','')
  with lock:all_records.append({'benchmark_id':bid,'request_index':index,'method':self.command,'path':current.path,'raw_query':current.query,
   'content_type':mime,'raw_body_base64':base64.b64encode(body).decode(),'raw_body':body.decode('utf-8',errors='replace'),
   'parsed_body_fields':fields(mime,body),'headers':dict(self.headers)})
  res=entry['response'];content=res.get('content',{});text=content.get('text','');payload=base64.b64decode(text) if content.get('encoding')=='base64' else text.encode('utf-8')
  status=int(res.get('status') or 200);status=status if 100<=status<=599 else 200
  if status in [204,304] or self.command=='HEAD':payload=b''
  self.send_response(status)
  for h in res.get('headers',[]):
   key=h['name'];value=h['value']
   if key.lower() in {'content-length','transfer-encoding','content-encoding','connection',':status'}:continue
   if key.lower()=='location' and value.startswith(('http://','https://')):
    u=urlsplit(value);value=f'http://127.0.0.1:{self.server.server_port}'+u.path+('?' +u.query if u.query else '')
   if key.lower()=='set-cookie':value=re.sub(r';\s*(domain=[^;]+|secure)(?=;|$)','',value,flags=re.I)
   try:self.send_header(key,value)
   except (ValueError,UnicodeEncodeError):pass
  self.send_header('Content-Length',str(len(payload)));self.end_headers()
  if payload:
   try:self.wfile.write(payload)
   except (ConnectionResetError,BrokenPipeError):pass
 do_GET=do_HEAD=do_POST=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=receive
server=ThreadingHTTPServer(('127.0.0.1',0),Receiver);threading.Thread(target=server.serve_forever,daemon=True).start()
jobs=[]
for n in chosen:
 bid=f'REAL100-{n:03d}';folder=ROOT/'wire'/bid;folder.mkdir(parents=True,exist_ok=True)
 d=read(ROOT/'baseline'/bid/'engine_decisions.json');tree=ET.parse(d['jmx']);root=tree.getroot()
 for csv_path in d['csv_files']:shutil.copyfile(csv_path,folder/Path(csv_path).name)
 for p in root.iter('stringProp'):
  if p.get('name')=='HTTPSampler.domain':p.text='127.0.0.1'
  if p.get('name')=='HTTPSampler.protocol':p.text='http'
  if p.get('name')=='HTTPSampler.port':p.text=str(server.server_port)
  if p.get('name') in {'HTTPSampler.connect_timeout','HTTPSampler.response_timeout'}:p.text='3000'
 for a in root.findall(".//elementProp[@elementType='Argument']"):
  name=a.findtext("stringProp[@name='Argument.name']")
  if name in {'THINKTIME','RAMP','HOLD','DURATION'}:a.find("stringProp[@name='Argument.value']").text='0'
  if name=='BASE_URL':a.find("stringProp[@name='Argument.value']").text='127.0.0.1'
  if name=='PROTOCOL':a.find("stringProp[@name='Argument.value']").text='http'
  if name=='LOOPS':a.find("stringProp[@name='Argument.value']").text='2'
  if name=='THREADS':a.find("stringProp[@name='Argument.value']").text='1'
  if name=='TIMEOUT':a.find("stringProp[@name='Argument.value']").text='3000'
 indices=[i for t in d['transactions'] for i in t['request_indices'] if not d['requests'][i]['excluded'] and i not in d['redirect_execution'].get('automatic_targets',[])]
 parents={c:p for p in root.iter() for c in p}
 for index,sampler in zip(indices,root.iter('HTTPSamplerProxy')):
  siblings=list(parents[sampler]);subtree=siblings[siblings.index(sampler)+1]
  hm=next((x for x in subtree if x.tag=='HeaderManager'),None)
  if hm is None:
   hm=ET.SubElement(subtree,'HeaderManager',guiclass='HeaderPanel',testclass='HeaderManager',testname='Local audit routing',enabled='true');coll=ET.SubElement(hm,'collectionProp',name='HeaderManager.headers');ET.SubElement(subtree,'hashTree')
  else:coll=hm.find("collectionProp[@name='HeaderManager.headers']")
  for key,value in [('X-REAL100-Workflow',bid),('X-REAL100-Request',str(index))]:
   elem=ET.SubElement(coll,'elementProp',name=key,elementType='Header');header(elem,'Header.name',key);header(elem,'Header.value',value)
 path=folder/'local.jmx';tree.write(path,encoding='utf-8',xml_declaration=True);jobs.append((bid,path,folder))
def execute(job):
 bid,path,folder=job
 try:
  proc=subprocess.run(['C:/Program Files/Common Files/Oracle/Java/javapath/java.exe','-Djava.awt.headless=true','-jar',str(WORK.parent/'apache-jmeter-5.6.3/apache-jmeter-5.6.3/bin/ApacheJMeter.jar'),'-n','-t',str(path),'-l',str(folder/'results.jtl'),'-j',str(folder/'jmeter.log')],cwd=folder,capture_output=True,text=True,timeout=100)
  (folder/'console.txt').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8')
  with (folder/'results.jtl').open(encoding='utf-8',newline='') as f:samples=list(csv.DictReader(f))
  result={'benchmark_id':bid,'exit_code':proc.returncode,'completed':True,'samples':len(samples),'failed_samples':sum(s.get('success')!='true' for s in samples)}
 except Exception as exc:result={'benchmark_id':bid,'completed':False,'error':str(exc)}
 print('local smoke',bid,result,flush=True);return result
try:
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(execute,jobs))
finally:server.shutdown();server.server_close()
save(ROOT/'WIRE_RAW_REQUESTS.json',all_records)
save(ROOT/'WIRE_SMOKE_EXECUTION.json',{'one_vu':True,'iterations':2,'workflows':20,'destination':'Deterministic loopback receiver serving original captured responses; no external business replay','results':results,
 'limits':'Transport and captured-response smoke only. Destination and Set-Cookie scope rewritten for loopback; no fresh business-state issuance, live auth success, or load claim. Runtime failures remain evidence, not repaired.',
 'received_requests':len(all_records)})
