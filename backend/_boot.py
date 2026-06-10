import os
import sys
import traceback

os.chdir("d:/DraftMind/backend")
os.environ["PYTHONPATH"] = "d:/DraftMind/backend"
sys.path.insert(0, "d:/DraftMind/backend")

log = "d:/DraftMind/backend/_uvicorn3.log"
sys.stdout = open(log, "w", encoding="utf-8", buffering=1)
sys.stderr = sys.stdout
print("=== START uvicorn import test ===", flush=True)
try:
    import uvicorn
    print(f"uvicorn ver: {uvicorn.__version__}", flush=True)
    print("importing app.main ...", flush=True)
    from app.main import app
    print(f"app loaded: {app}", flush=True)
    print("starting uvicorn ...", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
    sys.exit(1)
