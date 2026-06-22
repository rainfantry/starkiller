"""
STARKILLER SETUP — Automated Android Build Environment
22DIV / george wu

Downloads and configures:
  - Android SDK command-line tools
  - SDK platform (API 34)
  - Build tools
  - Gradle wrapper

Usage:
    python setup.py              # full setup
    python setup.py --check      # verify existing setup
"""
import os
import sys
import subprocess
import zipfile
import urllib.request
import shutil

PROJECT = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.join(PROJECT, "client")
SDK_DIR = os.path.join(PROJECT, "android-sdk")
CMDLINE_TOOLS_URL = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
GRADLE_VERSION = "8.7"
GRADLE_WRAPPER_URL = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"

G = "\033[92m"
R = "\033[91m"
A = "\033[93m"
D = "\033[90m"
W = "\033[97m"
X = "\033[0m"


def run(cmd, cwd=None, env=None):
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, env=env)
    return result.returncode, result.stdout, result.stderr


def check_java():
    rc, out, _ = run("java -version")
    if rc != 0:
        rc, out, err = run("java -version")
        out = err
    if "version" in (out + _).lower():
        ver = (out + _).split('"')[1] if '"' in (out + _) else "?"
        print(f"  {G}[+]{X} Java: {ver}")
        return True
    print(f"  {R}[!]{X} Java not found. Install JDK 17+ first.")
    return False


def check_adb():
    rc, out, _ = run("adb version")
    if rc == 0:
        print(f"  {G}[+]{X} ADB: available")
        return True
    print(f"  {A}[~]{X} ADB not found (optional for install)")
    return False


def setup_sdk():
    if os.path.exists(os.path.join(SDK_DIR, "cmdline-tools", "latest", "bin", "sdkmanager.bat")):
        print(f"  {G}[+]{X} Android SDK already set up")
        return True

    print(f"  {A}[~]{X} Downloading Android SDK command-line tools...")
    zip_path = os.path.join(PROJECT, "cmdline-tools.zip")
    try:
        urllib.request.urlretrieve(CMDLINE_TOOLS_URL, zip_path)
    except Exception as e:
        print(f"  {R}[!]{X} Download failed: {e}")
        return False

    print(f"  {A}[~]{X} Extracting...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(SDK_DIR)

    src = os.path.join(SDK_DIR, "cmdline-tools")
    dst = os.path.join(SDK_DIR, "cmdline-tools", "latest")
    if os.path.exists(src) and not os.path.exists(dst):
        temp = os.path.join(SDK_DIR, "_cmdline-tools-temp")
        os.rename(src, temp)
        os.makedirs(os.path.join(SDK_DIR, "cmdline-tools"), exist_ok=True)
        os.rename(temp, dst)

    os.remove(zip_path)

    sdkmanager = os.path.join(dst, "bin", "sdkmanager.bat")
    if not os.path.exists(sdkmanager):
        print(f"  {R}[!]{X} sdkmanager not found after extraction")
        return False

    env = os.environ.copy()
    env["ANDROID_SDK_ROOT"] = SDK_DIR

    print(f"  {A}[~]{X} Accepting licenses...")
    proc = subprocess.Popen(
        [sdkmanager, "--sdk_root=" + SDK_DIR, "--licenses"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env,
    )
    proc.communicate(input=b"y\n" * 20)

    packages = [
        "platform-tools",
        "build-tools;34.0.0",
        "platforms;android-34",
    ]

    for pkg in packages:
        print(f"  {A}[~]{X} Installing {pkg}...")
        rc, out, err = run(
            f'"{sdkmanager}" --sdk_root="{SDK_DIR}" "{pkg}"',
            env=env,
        )
        if rc != 0:
            print(f"  {R}[!]{X} Failed to install {pkg}")
            print(f"       {err[:200]}")

    print(f"  {G}[+]{X} Android SDK setup complete")
    return True


def setup_gradle_wrapper():
    gradlew = os.path.join(CLIENT_DIR, "gradlew.bat")
    if os.path.exists(gradlew):
        print(f"  {G}[+]{X} Gradle wrapper already exists")
        return True

    gradle_bin = shutil.which("gradle")
    if gradle_bin:
        print(f"  {A}[~]{X} Generating Gradle wrapper via system gradle...")
        rc, _, err = run(f'gradle wrapper --gradle-version {GRADLE_VERSION}', cwd=CLIENT_DIR)
        if rc == 0:
            print(f"  {G}[+]{X} Gradle wrapper created")
            return True

    print(f"  {A}[~]{X} Creating Gradle wrapper manually...")
    wrapper_dir = os.path.join(CLIENT_DIR, "gradle", "wrapper")
    os.makedirs(wrapper_dir, exist_ok=True)

    props = f"""distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip
networkTimeout=10000
validateDistributionUrl=true
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
"""
    with open(os.path.join(wrapper_dir, "gradle-wrapper.properties"), "w") as f:
        f.write(props)

    gradlew_bat = """@rem Gradle wrapper script for Windows
@if "%DEBUG%"=="" @echo off
set DIRNAME=%~dp0
set APP_BASE_NAME=%~n0
set APP_HOME=%DIRNAME%
set DEFAULT_JVM_OPTS="-Xmx64m" "-Xms64m"
set CLASSPATH=%APP_HOME%\\gradle\\wrapper\\gradle-wrapper.jar
java %DEFAULT_JVM_OPTS% -classpath "%CLASSPATH%" org.gradle.wrapper.GradleWrapperMain %*
"""
    with open(os.path.join(CLIENT_DIR, "gradlew.bat"), "w") as f:
        f.write(gradlew_bat)

    gradlew_sh = """#!/bin/sh
APP_HOME=$(cd "$(dirname "$0")" && pwd -P)
CLASSPATH="$APP_HOME/gradle/wrapper/gradle-wrapper.jar"
exec java -classpath "$CLASSPATH" org.gradle.wrapper.GradleWrapperMain "$@"
"""
    with open(os.path.join(CLIENT_DIR, "gradlew"), "w") as f:
        f.write(gradlew_sh)

    jar_url = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
    print(f"  {A}[~]{X} Downloading gradle-wrapper.jar...")
    try:
        wrapper_jar_url = f"https://github.com/gradle/gradle/raw/v{GRADLE_VERSION}/gradle/wrapper/gradle-wrapper.jar"
        urllib.request.urlretrieve(
            wrapper_jar_url,
            os.path.join(wrapper_dir, "gradle-wrapper.jar"),
        )
        print(f"  {G}[+]{X} Gradle wrapper created")
        return True
    except Exception as e:
        print(f"  {A}[~]{X} Wrapper JAR download failed: {e}")
        print(f"  {A}[~]{X} Run 'gradle wrapper' in client/ manually, or install Gradle")
        return False


def verify():
    print(f"\n  {W}STARKILLER — Environment Check{X}")
    print(f"  {'-'*40}")

    ok = True
    ok &= check_java()
    check_adb()

    sdkm = os.path.join(SDK_DIR, "cmdline-tools", "latest", "bin", "sdkmanager.bat")
    if os.path.exists(sdkm):
        print(f"  {G}[+]{X} Android SDK: {SDK_DIR}")
    else:
        print(f"  {R}[!]{X} Android SDK: not found")
        ok = False

    bt = os.path.join(SDK_DIR, "build-tools", "34.0.0")
    if os.path.exists(bt):
        print(f"  {G}[+]{X} Build tools: 34.0.0")
    else:
        print(f"  {R}[!]{X} Build tools: not installed")
        ok = False

    plat = os.path.join(SDK_DIR, "platforms", "android-34")
    if os.path.exists(plat):
        print(f"  {G}[+]{X} Platform: android-34")
    else:
        print(f"  {R}[!]{X} Platform: not installed")
        ok = False

    gradlew = os.path.join(CLIENT_DIR, "gradlew.bat")
    if os.path.exists(gradlew):
        print(f"  {G}[+]{X} Gradle wrapper: present")
    else:
        print(f"  {R}[!]{X} Gradle wrapper: missing")
        ok = False

    manifest = os.path.join(CLIENT_DIR, "app", "src", "main", "AndroidManifest.xml")
    if os.path.exists(manifest):
        print(f"  {G}[+]{X} Android project: present")
    else:
        print(f"  {R}[!]{X} Android project: not found")
        ok = False

    print(f"\n  {'-'*40}")
    if ok:
        print(f"  {G}[+] Environment ready. Run: python build.py --ip <your_ip>{X}")
    else:
        print(f"  {R}[!] Setup incomplete. Run: python setup.py{X}")
    print()
    return ok


def main():
    if "--check" in sys.argv:
        verify()
        return

    print(f"""
{W}  STARKILLER SETUP{X}
{D}  ------------------------------{X}
{D}  Setting up Android build environment...{X}
""")

    if not check_java():
        print(f"\n  {R}Install JDK 17+ first:{X}")
        print(f"    winget install EclipseAdoptium.Temurin.21.JDK")
        sys.exit(1)

    check_adb()
    setup_sdk()
    setup_gradle_wrapper()

    print(f"\n  {'-'*40}")
    print(f"  {G}[+] Setup complete.{X}")
    print(f"  {D}Next: python build.py --ip <your_ip>{X}\n")


if __name__ == "__main__":
    main()
