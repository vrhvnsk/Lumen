"""Starts Lumen (API + website) in one go and opens it in the browser.

This is the entry point of the packaged app (Lumen.exe on Windows). It does not
change any project file; it only points the existing app at its bundled data
through the environment variables that app/config.py already understands:

    MOVIE_DATA_DIR       dataset + search index
    MOVIE_FRONTEND_DIR   the website
    EMBEDDING_MODEL      local folder with the embedding model (bundled, so no internet needed)

It also works unpackaged, for testing:  python packaging/lumen_launcher.py
"""
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def resource_root() -> Path:
    """Folder that holds the bundled files (packaged) or the repository (unpackaged)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def configure_environment(root: Path) -> None:
    if getattr(sys, "frozen", False):
        os.environ.setdefault("MOVIE_DATA_DIR", str(root / "data"))
        os.environ.setdefault("MOVIE_FRONTEND_DIR", str(root / "frontend"))
        model_dir = root / "model"
        if model_dir.is_dir():
            os.environ["EMBEDDING_MODEL"] = str(model_dir)
            # Everything is bundled: never try to reach the internet.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
    else:
        sys.path.insert(0, str(root / "backend"))


def find_free_port(preferred: int = 8000) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:  # nothing is listening there
                return port
    raise RuntimeError("No free port found between 8000 and 8049.")


def open_browser_when_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 300  # loading the model can take a while on a slow PC
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=2):
                print(f"\nLumen is ready: {url}")
                print("Keep this window open while you use it. Close it to stop Lumen.\n")
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(1)


def main() -> None:
    root = resource_root()
    configure_environment(root)

    print("Starting Lumen... (the first start loads the search model and can take a minute)")

    import uvicorn
    from app.main import app  # imported only now, after the environment is set

    port = find_free_port()
    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()

    # asyncio + h11 are pure-Python choices, which keeps the packaged app simpler.
    uvicorn.run(app, host="127.0.0.1", port=port, loop="asyncio", http="h11", log_level="warning")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed for packaged apps on Windows
    try:
        main()
    except Exception as exc:  # keep the window open so the error can be read
        print(f"\nLumen could not start:\n{exc}\n")
        input("Press Enter to close this window...")
        raise
