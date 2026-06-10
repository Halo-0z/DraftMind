"""Write a marker file to confirm Python execution works."""
import os
import sys

# Write to user temp dir
marker = os.path.join(os.environ.get("TEMP", "C:\\Windows\\Temp"), "draftmind_marker.txt")
try:
    with open(marker, "w", encoding="utf-8") as f:
        f.write("python executed\n")
        f.write(f"argv: {sys.argv}\n")
        f.write(f"python: {sys.version}\n")
        f.write(f"cwd: {os.getcwd()}\n")
        f.write(f"marker: {marker}\n")
except Exception as e:
    err_marker = marker + ".err"
    with open(err_marker, "w", encoding="utf-8") as f:
        f.write(f"failed: {e}\n")
