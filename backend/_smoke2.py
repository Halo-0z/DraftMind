"""Write a marker file to confirm Python execution works."""
import sys
import os

# Use a relative path
marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_marker.txt")
with open(marker, "w", encoding="utf-8") as f:
    f.write("python executed\n")
    f.write(f"argv: {sys.argv}\n")
    f.write(f"python: {sys.version}\n")
    f.write(f"cwd: {os.getcwd()}\n")
    try:
        from app.main import app
        f.write("app.main import: ok\n")
        f.write(f"routes: {len(app.routes)}\n")
        for r in app.routes:
            if hasattr(r, "path"):
                f.write(f"  {r.path}\n")
    except Exception as e:
        import traceback
        f.write(f"app.main import: FAIL\n{e}\n{traceback.format_exc()}\n")
