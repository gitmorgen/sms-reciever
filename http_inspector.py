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
            sim TEXT NOT NULL DEFAULT '',
            is_read INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS contacts (
            sender TEXT PRIMARY KEY,
            archived INTEGER NOT NULL DEFAULT 0
        )""")
        # Migration: add is_read if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "is_read" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def insert_message(sender, text, sent, received, sim):
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO messages (sender, text, sent_stamp, received_stamp, sim) VALUES (?,?,?,?,?)",
                (sender, text, sent, received, sim),
            )
            # Unarchive contact on new message
            conn.execute(
                "INSERT INTO contacts (sender, archived) VALUES (?, 0) ON CONFLICT(sender) DO UPDATE SET archived=0",
                (sender,),
            )
            conn.commit()


def get_all_messages():
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id, sender, text, sent_stamp, received_stamp, sim, is_read FROM messages ORDER BY sent_stamp"
            ).fetchall()
            contacts = {r[0]: r[1] for r in conn.execute("SELECT sender, archived FROM contacts").fetchall()}
    return [
        {"id": r[0], "from": r[1], "text": r[2], "sent": r[3], "received": r[4], "sim": r[5], "read": bool(r[6]),
         "archived": bool(contacts.get(r[1], 0))}
        for r in rows
    ]


def mark_read(sender):
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE messages SET is_read=1 WHERE sender=? AND is_read=0", (sender,))
            conn.commit()


def set_archived(sender, archived):
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO contacts (sender, archived) VALUES (?, ?) ON CONFLICT(sender) DO UPDATE SET archived=?",
                (sender, int(archived), int(archived)),
            )
            conn.commit()


HTML_PAGE = r"""<!DOCTYPE html><html><head><title>SMS Inbox</title>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  height:100vh;display:flex;background:#111b21;color:#e9edef;overflow:hidden}

#sidebar{width:320px;min-width:320px;background:#111b21;border-right:1px solid #222d34;
  display:flex;flex-direction:column;height:100vh}
#sidebar-header{padding:12px 16px;font-size:20px;font-weight:600;color:#e9edef;
  background:#1f2c34;border-bottom:1px solid #222d34;display:flex;align-items:center;
  justify-content:space-between}
#sidebar-header .read-only{font-size:10px;color:#8696a0;background:#222d34;
  padding:3px 8px;border-radius:10px;font-weight:400}
.tab-bar{display:flex;background:#1f2c34;border-bottom:1px solid #222d34}
.tab{flex:1;padding:10px;text-align:center;font-size:13px;color:#8696a0;cursor:pointer;
  border-bottom:2px solid transparent;transition:all .15s}
.tab.active{color:#00a884;border-bottom-color:#00a884}
.tab .tab-count{font-size:11px;background:#2a3942;padding:1px 6px;border-radius:8px;margin-left:4px}
#contact-list{flex:1;overflow-y:auto}
.contact{padding:14px 16px;display:flex;align-items:center;gap:12px;cursor:pointer;
  border-bottom:1px solid #222d34;transition:background .15s}
.contact:hover{background:#202c33}
.contact.active{background:#2a3942}
.contact.has-unread .contact-name{font-weight:700}
.contact.has-unread .contact-preview{color:#e9edef}
.avatar{width:44px;height:44px;border-radius:50%;background:#00a884;display:flex;
  align-items:center;justify-content:center;font-size:18px;font-weight:600;
  color:#111b21;flex-shrink:0}
.avatar.archived-av{background:#667781}
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

#main{flex:1;display:flex;flex-direction:column;height:100vh}
#chat-header{padding:12px 20px;background:#1f2c34;border-bottom:1px solid #222d34;
  display:flex;align-items:center;gap:12px;min-height:60px}
#chat-header .avatar{width:38px;height:38px;font-size:16px}
#chat-header-name{font-size:16px;font-weight:500}
#chat-header-sub{font-size:12px;color:#8696a0}
.header-actions{margin-left:auto;display:flex;gap:8px}
.hdr-btn{background:none;border:1px solid #333d45;color:#8696a0;padding:5px 10px;
  border-radius:6px;font-size:12px;cursor:pointer;transition:all .15s}
.hdr-btn:hover{background:#2a3942;color:#e9edef}
.back-btn{display:none;background:none;border:none;color:#00a884;font-size:24px;
  cursor:pointer;padding:0 8px 0 0;line-height:1}
#messages{flex:1;overflow-y:auto;padding:20px 60px;background:#0b141a}
#empty-state{flex:1;display:flex;align-items:center;justify-content:center;
  flex-direction:column;color:#8696a0;gap:12px;font-size:15px;padding:20px;text-align:center}
#empty-state svg{width:60px;height:60px;fill:#8696a0}
.msg{max-width:65%;padding:8px 12px;margin-bottom:4px;border-radius:8px;
  font-size:14.2px;line-height:1.4;position:relative;word-wrap:break-word}
.msg.incoming{background:#202c33;align-self:flex-start;border-top-left-radius:0}
.msg.unread{border-left:3px solid #00a884}
.msg-time{font-size:11px;color:#8696a0;float:right;margin-left:10px;margin-top:4px}
.msg-sim{font-size:10px;color:#667781;margin-top:2px}
.unread-divider{text-align:center;margin:12px 0;font-size:12px;color:#00a884}
.unread-divider span{background:#0b2018;padding:4px 14px;border-radius:8px;border:1px solid #00a884}
.date-separator{text-align:center;margin:16px 0 12px;font-size:12px;color:#8696a0}
.date-separator span{background:#1b2831;padding:5px 12px;border-radius:8px}
#messages-wrap{display:flex;flex-direction:column}
#status-bar{padding:8px 20px;background:#1f2c34;border-top:1px solid #222d34;
  font-size:12px;color:#8696a0;text-align:center}

@media(max-width:600px){
  #sidebar{width:100%;min-width:100%}
  #main{display:none;width:100%;min-width:100%}
  body.show-chat #sidebar{display:none}
  body.show-chat #main{display:flex}
  .back-btn{display:block}
  #messages{padding:12px 12px}
  .msg{max-width:85%}
  #chat-header{padding:10px 12px}
  .header-actions{gap:4px}
  .hdr-btn{padding:4px 8px;font-size:11px}
}
</style></head><body>
<div id="sidebar">
  <div id="sidebar-header">
    <span>SMS Inbox</span>
    <span class="read-only">READ-ONLY</span>
  </div>
  <div class="tab-bar">
    <div class="tab active" id="tab-inbox" onclick="switchTab('inbox')">Inbox <span class="tab-count" id="inbox-count">0</span></div>
    <div class="tab" id="tab-archive" onclick="switchTab('archive')">Archived <span class="tab-count" id="archive-count">0</span></div>
  </div>
  <div id="contact-list"></div>
</div>
<div id="main">
  <div id="empty-state">
    <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg>
    <div>Select a conversation to read messages</div>
    <div style="font-size:13px">This is a read-only inbox &mdash; you cannot send SMS from here</div>
  </div>
</div>
<script>
let allMessages=[],selectedContact=null,knownHash="",currentTab="inbox";
const isMobile=()=>window.innerWidth<=600;

function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function formatPhone(n){return n||"Unknown"}
function initials(n){return(n||"?").replace(/[^0-9]/g,"").slice(-2)||"?"}
function timeStr(ts){
  if(!ts)return"";
  return new Date(ts).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
}
function dateStr(ts){
  if(!ts)return"";
  const d=new Date(ts),today=new Date();
  if(d.toDateString()===today.toDateString())return"Today";
  const y=new Date(today);y.setDate(y.getDate()-1);
  if(d.toDateString()===y.toDateString())return"Yesterday";
  return d.toLocaleDateString([],{day:"numeric",month:"short",year:"numeric"});
}

function groupByContact(){
  const g={};
  allMessages.forEach(m=>{
    const k=m.from||"Unknown";
    if(!g[k])g[k]=[];
    g[k].push(m);
  });
  return g;
}

function switchTab(tab){
  currentTab=tab;
  selectedContact=null;
  document.getElementById("tab-inbox").classList.toggle("active",tab==="inbox");
  document.getElementById("tab-archive").classList.toggle("active",tab==="archive");
  renderContacts();
  renderMessages();
}

function goBack(){
  selectedContact=null;
  document.body.classList.remove("show-chat");
  renderContacts();
  renderMessages();
}

function renderContacts(){
  const cl=document.getElementById("contact-list");
  const grouped=groupByContact();
  const isArchived=c=>{const msgs=grouped[c];return msgs.some(m=>m.archived);};
  const contacts=Object.keys(grouped)
    .filter(c=>currentTab==="archive"?isArchived(c):!isArchived(c))
    .sort((a,b)=>{
      const la=grouped[a][grouped[a].length-1],lb=grouped[b][grouped[b].length-1];
      return(lb.sent||0)-(la.sent||0);
    });

  // Update tab counts
  const allContacts=Object.keys(grouped);
  const archivedContacts=allContacts.filter(c=>isArchived(c));
  const inboxContacts=allContacts.filter(c=>!isArchived(c));
  const totalUnread=inboxContacts.reduce((s,c)=>s+grouped[c].filter(m=>!m.read).length,0);
  document.getElementById("inbox-count").textContent=totalUnread>0?totalUnread:inboxContacts.length;
  document.getElementById("archive-count").textContent=archivedContacts.length;

  cl.innerHTML=contacts.map(c=>{
    const msgs=grouped[c];
    const last=msgs[msgs.length-1];
    const unread=msgs.filter(m=>!m.read).length;
    const isActive=selectedContact===c?"active":"";
    const hasUnread=unread>0?"has-unread":"";
    const avClass=currentTab==="archive"?"avatar archived-av":"avatar";
    return`<div class="contact ${isActive} ${hasUnread}" onclick="selectContact('${c.replace(/'/g,"\\'")}')">
      <div class="${avClass}">${initials(c)}</div>
      <div class="contact-info">
        <div class="contact-name">${esc(formatPhone(c))}</div>
        <div class="contact-preview">${esc(last.text||"")}</div>
      </div>
      <div class="contact-meta">
        <div class="contact-time">${timeStr(last.sent)}</div>
        ${unread>0?`<div class="badge">${unread}</div>`:""}
      </div>
    </div>`;
  }).join("");
  if(!contacts.length){
    cl.innerHTML=`<div style="padding:40px 20px;text-align:center;color:#667781;font-size:14px">${
      currentTab==="archive"?"No archived conversations":"No messages yet"}</div>`;
  }
  if(!selectedContact&&contacts.length>0&&!isMobile())selectContact(contacts[0]);
}

function selectContact(c){
  selectedContact=c;
  if(isMobile())document.body.classList.add("show-chat");
  // Mark as read
  fetch("/api/mark-read",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({sender:c})});
  allMessages.forEach(m=>{if((m.from||"Unknown")===c)m.read=true;});
  renderContacts();
  renderMessages();
}

function archiveContact(c){
  const grouped=groupByContact();
  const isCurrentlyArchived=grouped[c]&&grouped[c].some(m=>m.archived);
  const newState=!isCurrentlyArchived;
  fetch("/api/archive",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({sender:c,archived:newState})});
  allMessages.forEach(m=>{if((m.from||"Unknown")===c)m.archived=newState;});
  selectedContact=null;
  if(isMobile())document.body.classList.remove("show-chat");
  renderContacts();
  renderMessages();
}

function renderMessages(){
  const main=document.getElementById("main");
  if(!selectedContact){
    main.innerHTML=`<div id="empty-state">
      <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg>
      <div>Select a conversation to read messages</div>
      <div style="font-size:13px">This is a read-only inbox &mdash; you cannot send SMS from here</div></div>`;
    return;
  }
  const msgs=allMessages.filter(m=>(m.from||"Unknown")===selectedContact)
    .sort((a,b)=>(a.sent||0)-(b.sent||0));
  const isArch=msgs.some(m=>m.archived);
  const archLabel=isArch?"Unarchive":"Archive";
  let html=`<div id="chat-header">
    <button class="back-btn" onclick="goBack()">&larr;</button>
    <div class="avatar${isArch?" archived-av":""}">${initials(selectedContact)}</div>
    <div><div id="chat-header-name">${esc(formatPhone(selectedContact))}</div>
    <div id="chat-header-sub">${msgs.length} message${msgs.length!==1?"s":""} &middot; read-only</div></div>
    <div class="header-actions">
      <button class="hdr-btn" onclick="archiveContact('${selectedContact.replace(/'/g,"\\'")}')">${archLabel}</button>
    </div>
  </div>
  <div id="messages"><div id="messages-wrap">`;
  let lastDate="",shownUnreadDivider=false;
  const firstUnreadIdx=msgs.findIndex(m=>!m.read);
  msgs.forEach((m,i)=>{
    const d=dateStr(m.sent);
    if(d!==lastDate){html+=`<div class="date-separator"><span>${d}</span></div>`;lastDate=d;}
    if(!shownUnreadDivider&&firstUnreadIdx>=0&&i===firstUnreadIdx){
      const unreadCount=msgs.filter(x=>!x.read).length;
      html+=`<div class="unread-divider"><span>${unreadCount} unread message${unreadCount!==1?"s":""}</span></div>`;
      shownUnreadDivider=true;
    }
    html+=`<div class="msg incoming${!m.read?" unread":""}">${esc(m.text||"")}
      <span class="msg-time">${timeStr(m.sent)}</span>
      ${m.sim?`<div class="msg-sim">${esc(m.sim)}</div>`:""}
    </div>`;
  });
  html+=`</div></div>
  <div id="status-bar">Read-only inbox &mdash; listening for messages on POST /sms</div>`;
  main.innerHTML=html;
  const mc=document.getElementById("messages");
  if(mc)mc.scrollTop=mc.scrollHeight;
}

async function poll(){
  try{
    const r=await fetch("/api/messages");
    const data=await r.json();
    const h=JSON.stringify(data);
    if(h!==knownHash){
      knownHash=h;
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
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _json_response(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/api/messages":
            self._json_response(200, get_all_messages())
        elif self.path in ("/", ""):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/sms":
            try:
                data = json.loads(self._read_body())
                sender = data.get("from", "Unknown")
                text = data.get("text", "")
                sent = data.get("sentStamp", 0)
                received = data.get("receivedStamp", 0)
                sim = data.get("sim", "")
                insert_message(sender, text, sent, received, sim)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] SMS from {sender}: {text[:60]}")
                self._json_response(200, {"status": "ok"})
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid json"})
        elif self.path == "/api/mark-read":
            try:
                data = json.loads(self._read_body())
                sender = data.get("sender", "")
                if sender:
                    mark_read(sender)
                self._json_response(200, {"status": "ok"})
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid json"})
        elif self.path == "/api/archive":
            try:
                data = json.loads(self._read_body())
                sender = data.get("sender", "")
                archived = data.get("archived", True)
                if sender:
                    set_archived(sender, archived)
                self._json_response(200, {"status": "ok"})
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid json"})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


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
