"""Quick test: launch Chrome with CDP and check if port 9222 responds."""
import subprocess
import time
import urllib.request

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA = r"C:\Users\DELL\AppData\Local\Google\Chrome\User Data"
PROFILE = "Profile 11"

# Kill existing
subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
time.sleep(4)

# Try approach 1: Popen with list (no shell)
print("=== Approach 1: Popen list ===")
p = subprocess.Popen([
    CHROME_EXE,
    "--remote-debugging-port=9222",
    f"--user-data-dir={USER_DATA}",
    f"--profile-directory={PROFILE}",
    "--no-first-run",
    "--no-default-browser-check",
])
print(f"PID: {p.pid}")

for i in range(15):
    time.sleep(1)
    try:
        r = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
        print(f"CDP OK after {i+1}s: {r.read().decode()[:100]}")
        break
    except Exception as e:
        print(f"  {i+1}s: {e}")
else:
    print("FAILED after 15s")

# Check if chrome is actually running
result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"], capture_output=True, text=True)
chrome_count = result.stdout.lower().count("chrome.exe")
print(f"Chrome processes running: {chrome_count}")

# Cleanup
subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
