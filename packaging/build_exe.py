"""Build a double-click app (Lumen.exe on Windows) with PyInstaller.

Run it on the operating system you want the app for (PyInstaller cannot
cross-compile): a Windows PC makes a .exe, a Mac makes a Mac program.

    pip install -r backend/requirements.txt pyinstaller
    python packaging/build_exe.py                # folder build (recommended)
    python packaging/build_exe.py --onefile      # one single file (slower to start)
    python packaging/build_exe.py --offline      # small build with the weaker TF-IDF search, no PyTorch

Nothing in the project is modified. Generated files go to packaging/_build/ and
the result to packaging/dist/.
"""
import argparse
import importlib.metadata
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"
DATA = BACKEND / "data"
BUILD = HERE / "_build"
STAGE = BUILD / "assets"

sys.path.insert(0, str(BACKEND))

# Packages that look up their own version at run time; PyInstaller must ship that info.
METADATA_PACKAGES = [
    "tqdm", "regex", "requests", "packaging", "filelock", "numpy", "tokenizers",
    "huggingface_hub", "safetensors", "transformers", "sentence_transformers",
    "torch", "pyyaml", "scikit-learn",
]


def has_dist(name: str) -> bool:
    try:
        importlib.metadata.distribution(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def ensure_index(offline: bool) -> dict:
    """Make sure a search index exists and return its info."""
    info_path = DATA / "index_info.json"
    if not (DATA / "faiss.index").exists() or not info_path.exists():
        print("No search index yet, building it (this is the same as running build_index.py)...")
        import build_index
        build_index.main(prefer_offline=offline)
    return json.loads(info_path.read_text(encoding="utf-8"))


def stage_assets(info: dict) -> None:
    """Copy exactly what the app needs at run time into one folder."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    (STAGE / "data").mkdir(parents=True)

    for name in ["movies_seed.json", "faiss.index", "index_info.json"]:
        shutil.copy2(DATA / name, STAGE / "data" / name)
    if info["backend"] == "tfidf-lsa":
        shutil.copy2(DATA / "tfidf_lsa.pkl", STAGE / "data" / "tfidf_lsa.pkl")

    shutil.copytree(ROOT / "frontend", STAGE / "frontend")

    if info["backend"] == "sentence-transformers":
        from app import config
        from sentence_transformers import SentenceTransformer

        print(f"Saving the embedding model '{config.EMBEDDING_MODEL}' into the app...")
        SentenceTransformer(config.EMBEDDING_MODEL).save(str(STAGE / "model"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="single file instead of a folder")
    parser.add_argument("--offline", action="store_true", help="use the small TF-IDF search (builds the index offline)")
    parser.add_argument("--name", default="Lumen")
    args = parser.parse_args()

    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        sys.exit("PyInstaller is missing. Install it with:  pip install pyinstaller")

    info = ensure_index(args.offline)
    uses_model = info["backend"] == "sentence-transformers"
    print(f"Search backend in this build: {info['backend']}")
    stage_assets(info)

    sep = os.pathsep  # ';' on Windows, ':' on Mac/Linux
    options = [
        str(HERE / "lumen_launcher.py"),
        "--name", args.name,
        "--noconfirm", "--clean",
        "--onefile" if args.onefile else "--onedir",
        "--console",  # shows the log window; closing it stops the app
        "--distpath", str(HERE / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--paths", str(BACKEND),
        "--hidden-import", "app.main",
        "--collect-submodules", "uvicorn",
        "--collect-all", "faiss",
        "--add-data", f"{STAGE / 'data'}{sep}data",
        "--add-data", f"{STAGE / 'frontend'}{sep}frontend",
    ]

    if uses_model:
        options += ["--add-data", f"{STAGE / 'model'}{sep}model",
                    "--collect-all", "sentence_transformers",
                    "--collect-all", "transformers",
                    "--exclude-module", "sklearn"]
    else:
        # Small build: keep the heavy deep-learning libraries out completely.
        options += ["--exclude-module", "torch",
                    "--exclude-module", "transformers",
                    "--exclude-module", "sentence_transformers"]

    for package in METADATA_PACKAGES:
        if has_dist(package):
            options += ["--copy-metadata", package]

    print("Running PyInstaller (this takes several minutes)...")
    pyinstaller.run(options)

    target = HERE / "dist" / (args.name if args.onefile else f"{args.name}")
    print("\nDone. Your app is in:", HERE / "dist")
    print("Start it by double-clicking", args.name + (".exe" if os.name == "nt" else ""), "inside that folder.")


if __name__ == "__main__":
    main()
