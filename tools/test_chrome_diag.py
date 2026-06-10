"""Standalone diagnostic: can we launch the user's Chrome with CDP on the
debugging port and connect to it?

This is NOT a pytest — it actually kills and relaunches Chrome. Run it by hand
when CDP connection is failing:

    python tools/test_chrome_diag.py
    python tools/test_chrome_diag.py --chrome-path "C:\\path\\to\\chrome.exe" --profile "Profile 1"

It auto-detects Chrome and the user-data dir the same way the scraper does, so
nothing is hardcoded to one machine.
"""

import argparse
import subprocess
import sys
import time
import urllib.request

# Allow running directly from the repo without installing the package.
sys.path.insert(0, __file__.rsplit("tools", 1)[0])

from web_crawler.chrome import default_user_data_dir, find_chrome_executable  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Chrome + CDP launch diagnostic")
    ap.add_argument("--chrome-path", default=None)
    ap.add_argument("--user-data-dir", default=None)
    ap.add_argument("--profile", default="Profile 11")
    ap.add_argument("--cdp-port", type=int, default=9222)
    args = ap.parse_args()

    chrome_exe = find_chrome_executable(args.chrome_path)
    user_data = args.user_data_dir or default_user_data_dir()
    print(f"Chrome:       {chrome_exe}")
    print(f"User data:    {user_data}")
    print(f"Profile:      {args.profile}")
    print(f"CDP port:     {args.cdp_port}")

    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    time.sleep(4)

    print("=== Launching Chrome ===")
    p = subprocess.Popen([
        chrome_exe,
        f"--remote-debugging-port={args.cdp_port}",
        f"--user-data-dir={user_data}",
        f"--profile-directory={args.profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ])
    print(f"PID: {p.pid}")

    url = f"http://127.0.0.1:{args.cdp_port}/json/version"
    for i in range(15):
        time.sleep(1)
        try:
            r = urllib.request.urlopen(url, timeout=2)
            print(f"CDP OK after {i + 1}s: {r.read().decode()[:100]}")
            break
        except Exception as e:
            print(f"  {i + 1}s: {e}")
    else:
        print("FAILED after 15s")

    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                            capture_output=True, text=True)
    print(f"Chrome processes running: {result.stdout.lower().count('chrome.exe')}")


if __name__ == "__main__":
    main()
