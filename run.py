import os
import sys
import uvicorn

# Local development entrypoint: opt into development mode explicitly.
# Any other way of starting the app (Docker, a process manager, a direct
# uvicorn call) now defaults to production, which fails closed without a
# configured WhatsApp app secret.
os.environ.setdefault("ENVIRONMENT", "development")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

if __name__ == "__main__":
    print("=" * 60)
    print("Starting LibyAI Clinic Reception Bot & Simulator...")
    print("Access Simulator UI at: http://localhost:8000")
    print("Access API Docs at:     http://localhost:8000/docs")
    print("=" * 60)
    # Bind to localhost by default. A deployment that must listen publicly
    # sets LIBYAI_HOST explicitly (for example behind a reverse proxy);
    # silently listening on every interface was the previous default.
    host = os.getenv("LIBYAI_HOST", "127.0.0.1")
    port = int(os.getenv("LIBYAI_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
