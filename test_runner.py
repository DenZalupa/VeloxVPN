import subprocess
import time

p = subprocess.Popen(
    ["cmd.exe", "/c", "run.bat"],
    cwd=r"C:\Users\Admin\.gemini\antigravity\scratch\fast-vpn-configurator",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)
time.sleep(2)
p.terminate()
out, _ = p.communicate()
print("OUTPUT FROM RUN.BAT:")
print(out)
