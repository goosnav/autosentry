"""Stdlib HTTP adapter for the operator dashboard (FR-17).

Deliberately dependency-free (Python's `http.server`) so the dashboard adds no packages and
nothing heavy to import. It is pure glue: every request maps onto a `DashboardService` method
(the tested core in `service.py`). Served on loopback by default and started in a daemon
thread, so it is strictly off the detection→alarm path — if it falls over, the pipeline is
unaffected (pillar 1, FR-17). Not unit-tested directly (the logic lives in DashboardService);
exercised by hand during M6 bring-up.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from autosentry.dashboard.service import DashboardService

log = logging.getLogger("autosentry.dashboard")

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AutoSentry</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font:14px system-ui,sans-serif;margin:0;background:#0e1116;color:#e6e6e6}
 header{padding:12px 16px;background:#161b22;border-bottom:1px solid #30363d;
   font-weight:600;display:flex;align-items:center;gap:12px}
 main{padding:16px;max-width:900px;margin:0 auto}
 .zone{display:flex;align-items:center;gap:12px;padding:10px 12px;margin:6px 0;
   border:1px solid #30363d;border-radius:8px;background:#161b22;flex-wrap:wrap}
 .lvl{font-weight:700;padding:2px 8px;border-radius:4px}
 .NORMAL{background:#1f6f3f}.WATCH{background:#7a6a1f}.SUSPECT{background:#8a5a1f}
 .THREAT{background:#9a3a1f}.ALARM{background:#b81d1d}
 .grow{flex:1;min-width:140px}button{font:inherit;padding:6px 10px;border:1px solid #30363d;
   border-radius:6px;background:#21262d;color:#e6e6e6;cursor:pointer}button:hover{background:#30363d}
 .panic{background:#b81d1d;border-color:#b81d1d}.warn{color:#f0a500;font-weight:600}
 section{margin-top:20px}h2{font-size:15px;border-bottom:1px solid #30363d;padding-bottom:6px}
 .ev{font-family:ui-monospace,monospace;font-size:12px;padding:4px 0;
   border-bottom:1px solid #21262d}
 .pill{font-size:12px;padding:2px 6px;border-radius:4px;background:#30363d}
 .assess{flex-basis:100%;font-size:12px;color:#9aa4af;font-family:ui-monospace,monospace}
 .meta{font-size:12px;color:#9aa4af}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #21262d}
 th{color:#9aa4af;font-weight:600}.off{color:#b81d1d}.batt{color:#f0a500}
 .bar{display:flex;gap:8px;margin:6px 0}
</style></head><body>
<header>
 <span>AutoSentry — operator dashboard</span>
 <span class="lvl" id="syslvl">—</span>
 <span class="meta" id="summary"></span>
</header>
<main>
 <div id="banner"></div>
 <section><h2>Zones</h2>
   <div class="bar">
     <button onclick="post('/api/arm',{})">Arm all</button>
     <button onclick="post('/api/disarm',{})">Disarm all</button>
     <button onclick="post('/api/test',{on:!TEST})" id="testbtn">Toggle test mode</button>
   </div>
   <div id="zones"></div></section>
 <section><h2>Mesh nodes</h2><div id="nodes"></div></section>
 <section><h2>Authority recommendations (SE-5)</h2><div id="auth"></div></section>
 <section><h2>Recent events</h2><div id="events"></div></section>
</main>
<script>
let TEST=false;
async function post(u,b){await fetch(u,{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify(b||{})});refresh();}
function el(t,c,x){let e=document.createElement(t);if(c)e.className=c;
  if(x!=null)e.textContent=x;return e;}
function ts(t){return t?new Date(t*1000).toLocaleTimeString():'';}
function assessText(a){if(!a)return '';
  let p=[];if(a.armed!=null)p.push(a.armed?'ARMED':'unarmed');
  if(a.weapon_type)p.push('weapon='+a.weapon_type);
  if(a.intent)p.push('intent="'+a.intent+'"');
  if(a.confidence!=null)p.push('conf='+Number(a.confidence).toFixed(2));
  return p.join('  ');}
async function refresh(){
 let s=await (await fetch('/api/status')).json();
 TEST=s.test_mode;document.getElementById('testbtn').textContent=
   (TEST?'Disable':'Enable')+' test mode';
 let sl=document.getElementById('syslvl');sl.textContent=s.system_level;
 sl.className='lvl '+s.system_level;
 document.getElementById('summary').textContent=
   `${s.armed_count}/${s.zone_count} armed`+(TEST?' · TEST MODE':'');
 let b=document.getElementById('banner');b.innerHTML='';
 let deg=Object.keys(s.degraded||{});
 if(deg.length||s.offline_nodes.length||s.on_battery_nodes.length){
   let d=el('div','warn');d.textContent='DEGRADED: '+deg.join(', ')
     +(s.offline_nodes.length?' | offline nodes: '+s.offline_nodes.join(','):'')
     +(s.on_battery_nodes.length?' | on battery: '+s.on_battery_nodes.join(','):'');
   b.appendChild(d);}
 let z=document.getElementById('zones');z.innerHTML='';
 for(const zz of s.zones){
   let row=el('div','zone');
   row.appendChild(el('span','lvl '+zz.level,zz.level));
   row.appendChild(el('span','grow',zz.zone+' — '+zz.reason));
   row.appendChild(el('span','pill',zz.armed?'ARMED':'disarmed'));
   let ad=el('button',null,zz.armed?'Disarm':'Arm');
   ad.onclick=()=>post(zz.armed?'/api/disarm':'/api/arm',{zone:zz.zone});
   row.appendChild(ad);
   let p=el('button','panic','Panic');p.onclick=()=>post('/api/panic',{zone:zz.zone});
   row.appendChild(p);
   let at=assessText(zz.assessment);
   if(at){let arow=el('div','assess','▸ '+at
     +(zz.assessment.description?'  — '+zz.assessment.description:''));
     row.appendChild(arow);}
   z.appendChild(row);}
 let nd=document.getElementById('nodes');nd.innerHTML='';
 if(!s.nodes.length){nd.appendChild(el('div','meta','no nodes reporting'));}
 else{let tbl=el('table');let hr=el('tr');
   for(const h of ['Node','State','Battery'])hr.appendChild(el('th',null,h));
   tbl.appendChild(hr);
   for(const n of s.nodes){let r=el('tr');
     r.appendChild(el('td',null,n.node_id));
     r.appendChild(el('td',n.online?'':'off',n.online?'online':'OFFLINE'));
     let bt=n.battery_mv!=null?(n.battery_mv/1000).toFixed(2)+' V':'—';
     r.appendChild(el('td',n.on_battery?'batt':'',
       (n.on_battery?'on battery · ':'')+bt));
     tbl.appendChild(r);}
   nd.appendChild(tbl);}
 let a=document.getElementById('auth');a.innerHTML='';
 if(!s.pending_authority.length)a.appendChild(el('div','meta','none'));
 for(const r of s.pending_authority){
   let row=el('div','zone');
   row.appendChild(el('span','grow',r.zone+' — '+r.reason+(r.confirmed?' (confirmed)':'')));
   if(!r.confirmed){let c=el('button',null,'Confirm contact');
     c.onclick=()=>post('/api/confirm_authority',{index:r.index});row.appendChild(c);}
   a.appendChild(row);}
 let ev=await (await fetch('/api/events')).json();
 let e=document.getElementById('events');e.innerHTML='';
 for(const x of ev){let d=el('div','ev');
   d.textContent=`${ts(x.ts)} [${x.level}] ${x.zone} — ${x.reason} (${(x.actions||'')})`;
   e.appendChild(d);}
}
refresh();setInterval(refresh,2000);
</script></body></html>"""


def _handler_class(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # quiet; we have structured logging
            pass

        def _json(self, code: int, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    body = _PAGE.encode()
                    self.send_response(200)
                    self.send_header("content-type", "text/html; charset=utf-8")
                    self.send_header("content-length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/status":
                    self._json(200, service.status())
                elif path == "/api/events":
                    qs = parse_qs(urlparse(self.path).query)
                    limit = int(qs["limit"][0]) if "limit" in qs else None
                    self._json(200, service.events(limit))
                else:
                    self._json(404, {"error": "not found"})
            except Exception as e:  # a dashboard error must never crash the server thread
                log.warning("dashboard GET %s failed: %s", path, e)
                self._json(500, {"error": str(e)})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("content-length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if path == "/api/arm":
                    self._json(200, service.arm(body.get("zone")))
                elif path == "/api/disarm":
                    self._json(200, service.disarm(body.get("zone")))
                elif path == "/api/panic":
                    self._json(200, service.panic(body["zone"]))
                elif path == "/api/test":
                    self._json(200, service.set_test_mode(bool(body["on"])))
                elif path == "/api/confirm_authority":
                    self._json(200, service.confirm_authority(int(body["index"])))
                else:
                    self._json(404, {"error": "not found"})
            except (KeyError, ValueError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                log.warning("dashboard POST %s failed: %s", path, e)
                self._json(500, {"error": str(e)})

    return Handler


def start_dashboard(
    service: DashboardService, host: str, port: int
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the dashboard HTTP server in a daemon thread; return (server, thread).

    The caller keeps it strictly off the critical path — it is started after the pipeline
    is up and torn down on shutdown. Failure here is logged, never propagated to the loop.
    """
    server = ThreadingHTTPServer((host, port), _handler_class(service))
    thread = threading.Thread(target=server.serve_forever, name="dashboard", daemon=True)
    thread.start()
    log.info("operator dashboard on http://%s:%d (FR-17)", host, port)
    return server, thread
