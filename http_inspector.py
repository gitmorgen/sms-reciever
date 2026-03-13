#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import sqlite3
import socket
import threading
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sms.db")
db_lock = threading.Lock()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            text TEXT NOT NULL,
            sent_stamp INTEGER NOT NULL,
            received_stamp INTEGER NOT NULL,
            sim TEXT NOT NULL DEFAULT ''
        )""")
        conn.commit()


def insert_message(sender, text, sent, received, sim):
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO messages (sender, text, sent_stamp, received_stamp, sim) VALUES (?,?,?,?,?)",
                (sender, text, sent, received, sim),
            )
            conn.commit()


def get_all_messages():
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT sender, text, sent_stamp, received_stamp, sim FROM messages ORDER BY sent_stamp"
            ).fetchall()
    return [
        {"from": r[0], "text": r[1], "sent": r[2], "received": r[3], "sim": r[4]}
        for r in rows
    ]


HTML_PAGE = r"""<!DOCTYPE html><html><head><title>SMS Inbox</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  height:100vh;display:flex;background:#111b21;color:#e9edef;overflow:hidden}

/* --- Sidebar --- */
#sidebar{width:320px;min-width:320px;background:#111b21;border-right:1px solid #222d34;
  display:flex;flex-direction:column;height:100vh}
#sidebar-header{padding:16px;font-size:20px;font-weight:600;color:#e9edef;
  background:#1f2c34;border-bottom:1px solid #222d34;display:flex;align-items:center;
  justify-content:space-between}
#contact-list{flex:1;overflow-y:auto}
.contact{padding:14px 16px;display:flex;align-items:center;gap:12px;cursor:pointer;
  border-bottom:1px solid #222d34;transition:background .15s}
.contact:hover{background:#202c33}
.contact.active{background:#2a3942}
.avatar{width:44px;height:44px;border-radius:50%;background:#00a884;display:flex;
  align-items:center;justify-content:center;font-size:18px;font-weight:600;
  color:#111b21;flex-shrink:0}
.contact-info{flex:1;min-width:0}
.contact-name{font-size:15px;color:#e9edef;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.contact-preview{font-size:13px;color:#8696a0;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;margin-top:2px}
.contact-meta{text-align:right;flex-shrink:0}
.contact-time{font-size:11px;color:#8696a0}
.badge{background:#00a884;color:#111b21;border-radius:50%;font-size:11px;
  width:20px;height:20px;display:flex;align-items:center;justify-content:center;
  margin-top:4px;margin-left:auto;font-weight:600}

/* --- Main --- */
#main{flex:1;display:flex;flex-direction:column;height:100vh}
#chat-header{padding:12px 20px;background:#1f2c34;border-bottom:1px solid #222d34;
  display:flex;align-items:center;gap:12px;min-height:60px}
#chat-header .avatar{width:38px;height:38px;font-size:16px}
#chat-header-name{font-size:16px;font-weight:500}
#chat-header-sub{font-size:12px;color:#8696a0}
.back-btn{display:none;background:none;border:none;color:#00a884;font-size:24px;
  cursor:pointer;padding:0 8px 0 0;line-height:1}
#messages{flex:1;overflow-y:auto;padding:20px 60px;background:#0b141a}
#empty-state{flex:1;display:flex;align-items:center;justify-content:center;
  flex-direction:column;color:#8696a0;gap:12px;font-size:15px;padding:20px}
#empty-state svg{width:60px;height:60px;fill:#8696a0}
.msg{max-width:65%;padding:8px 12px;margin-bottom:4px;border-radius:8px;
  font-size:14.2px;line-height:1.4;position:relative;word-wrap:break-word}
.msg.incoming{background:#202c33;align-self:flex-start;border-top-left-radius:0}
.msg-time{font-size:11px;color:#8696a0;float:right;margin-left:10px;margin-top:4px}
.msg-sim{font-size:10px;color:#667781;margin-top:2px}
.date-separator{text-align:center;margin:16px 0 12px;font-size:12px;color:#8696a0}
.date-separator span{background:#1b2831;padding:5px 12px;border-radius:8px}
#messages-wrap{display:flex;flex-direction:column}
#status-bar{padding:8px 20px;background:#1f2c34;border-top:1px solid #222d34;
  font-size:12px;color:#8696a0;text-align:center}

/* --- Mobile responsive --- */
@media(max-width:600px){
  #sidebar{width:100%;min-width:100%}
  #main{display:none;width:100%;min-width:100%}
  body.show-chat #sidebar{display:none}
  body.show-chat #main{display:flex}
  .back-btn{display:block}
  #messages{padding:12px 12px}
  .msg{max-width:85%}
  #chat-header{padding:10px 12px}
}
</style></head><body>
<div id="sidebar">
  <div id="sidebar-header">SMS Inbox</div>
  <div id="contact-list"></div>
</div>
<div id="main">
  <div id="empty-state">
    <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg>
    <div>Select a conversation to read messages</div>
    <div style="font-size:13px">SMS messages received via POST /sms appear here</div>
  </div>
</div>
<script>
let allMessages=[], selectedContact=null, knownCount=0;
const isMobile=()=>window.innerWidth<=600;

function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function formatPhone(n){return n||"Unknown"}
function initials(n){return(n||"?").replace(/[^0-9]/g,"").slice(-2)||"?"}
function timeStr(ts){
  if(!ts)return"";
  const d=new Date(ts);
  return d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
}
function dateStr(ts){
  if(!ts)return"";
  const d=new Date(ts);
  const today=new Date();
  if(d.toDateString()===today.toDateString())return"Today";
  const y=new Date(today);y.setDate(y.getDate()-1);
  if(d.toDateString()===y.toDateString())return"Yesterday";
  return d.toLocaleDateString([],{day:"numeric",month:"short",year:"numeric"});
}

function goBack(){
  selectedContact=null;
  document.body.classList.remove("show-chat");
  renderContacts();
  renderMessages();
}

function renderContacts(){
  const cl=document.getElementById("contact-list");
  const grouped={};
  allMessages.forEach(m=>{
    const k=m.from||"Unknown";
    if(!grouped[k])grouped[k]=[];
    grouped[k].push(m);
  });
  const contacts=Object.keys(grouped).sort((a,b)=>{
    const la=grouped[a][grouped[a].length-1], lb=grouped[b][grouped[b].length-1];
    return(lb.sent||0)-(la.sent||0);
  });
  cl.innerHTML=contacts.map(c=>{
    const msgs=grouped[c];
    const last=msgs[msgs.length-1];
    const isActive=selectedContact===c?"active":"";
    return`<div class="contact ${isActive}" onclick="selectContact('${c.replace(/'/g,"\\'")}')">
      <div class="avatar">${initials(c)}</div>
      <div class="contact-info">
        <div class="contact-name">${esc(formatPhone(c))}</div>
        <div class="contact-preview">${esc(last.text||"")}</div>
      </div>
      <div class="contact-meta">
        <div class="contact-time">${timeStr(last.sent)}</div>
        ${msgs.length>0?`<div class="badge">${msgs.length}</div>`:""}
      </div>
    </div>`;
  }).join("");
  if(!selectedContact&&contacts.length>0&&!isMobile())selectContact(contacts[0]);
}

function selectContact(c){
  selectedContact=c;
  if(isMobile())document.body.classList.add("show-chat");
  renderContacts();
  renderMessages();
}

function renderMessages(){
  const main=document.getElementById("main");
  if(!selectedContact){
    main.innerHTML=`<div id="empty-state">
      <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg>
      <div>Select a conversation to read messages</div></div>`;
    return;
  }
  const msgs=allMessages.filter(m=>(m.from||"Unknown")===selectedContact)
    .sort((a,b)=>(a.sent||0)-(b.sent||0));
  let html=`<div id="chat-header">
    <button class="back-btn" onclick="goBack()">&larr;</button>
    <div class="avatar">${initials(selectedContact)}</div>
    <div><div id="chat-header-name">${esc(formatPhone(selectedContact))}</div>
    <div id="chat-header-sub">${msgs.length} message${msgs.length!==1?"s":""}</div></div>
  </div>
  <div id="messages"><div id="messages-wrap">`;
  let lastDate="";
  msgs.forEach(m=>{
    const d=dateStr(m.sent);
    if(d!==lastDate){html+=`<div class="date-separator"><span>${d}</span></div>`;lastDate=d;}
    html+=`<div class="msg incoming">${esc(m.text||"")}
      <span class="msg-time">${timeStr(m.sent)}</span>
      ${m.sim?`<div class="msg-sim">${esc(m.sim)}</div>`:""}
    </div>`;
  });
  html+=`</div></div>
  <div id="status-bar">Listening for messages on POST /sms</div>`;
  main.innerHTML=html;
  const mc=document.getElementById("messages");
  if(mc)mc.scrollTop=mc.scrollHeight;
}

async function poll(){
  try{
    const r=await fetch("/api/messages");
    const data=await r.json();
    if(data.length!==knownCount){
      knownCount=data.length;
      allMessages=data;
      renderContacts();
      renderMessages();
    }
  }catch(e){}
  setTimeout(poll,2000);
}
poll();
</script></body></html>"""


class SMSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/messages":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(get_all_messages()).encode())
        elif self.path == "/" or self.path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/sms":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            try:
                data = json.loads(body)
                sender = data.get("from", "Unknown")
                text = data.get("text", "")
                sent = data.get("sentStamp", 0)
                received = data.get("receivedStamp", 0)
                sim = data.get("sim", "")
                insert_message(sender, text, sent, received, sim)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] SMS from {sender}: {text[:60]}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "invalid json"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence default logging


if __name__ == "__main__":
    init_db()
    port = 8888
    server = HTTPServer(("0.0.0.0", port), SMSHandler)
    local_ip = "?"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    print(f"SMS Inbox running on:")
    print(f"  http://localhost:{port}")
    print(f"  http://{local_ip}:{port}")
    print(f"Configure SMS Forwarder to POST to http://{local_ip}:{port}/sms")
    server.serve_forever()
