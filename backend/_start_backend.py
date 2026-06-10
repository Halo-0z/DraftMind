import os, sys, traceback
os.environ["PYTHONPATH"] = r"D:\DraftMind\backend"
os.environ["PYTHONUNBUFFERED"] = "1"
sys.path.insert(0, r"D:\DraftMind\backend")
log_path = r"D:\DraftMind\backend_LOG"
try:
    sys.stdout = open(log_path, "w", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout
    import logging
    # Surface INFO messages from the news service so the smoke output
    # actually shows how many raw items each source returned.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    import uvicorn
    print("[boot] uvicorn ver:", uvicorn.__version__, flush=True)
    print("[boot] importing app.main ...", flush=True)
    from app.main import app
    print("[boot] app loaded:", app, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
    sys.exit(1)
