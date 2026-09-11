"""
Fetch the offline speech models the voice agent needs.

Downloads to backend/ml_models/voice/:
  Vosk  Hindi + Indian-English speech recognition  (~92 MB total)
  Piper Hindi + English voices                     (~90 MB total)

Nothing here needs an API key or an account. Run once, then the agent works
with no internet at all:

    python scripts/download_voice_models.py            # everything
    python scripts/download_voice_models.py --lang hi  # Hindi only

Re-running skips anything already present.
"""

import argparse
import shutil
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def _ssl_context() -> ssl.SSLContext:
    """
    A context with a working CA bundle.

    A python.org build on macOS ships without trusting the system roots unless
    "Install Certificates.command" has been run, so every HTTPS fetch fails with
    CERTIFICATE_VERIFY_FAILED. certifi is already present via requests/httpx,
    so use its bundle rather than requiring that manual step.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

BASE_DIR = Path(__file__).resolve().parent.parent
VOICE_DIR = BASE_DIR / "ml_models" / "voice"

VOSK_BASE = "https://alphacephei.com/vosk/models"
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Small Vosk models: quantised, CPU-only, good enough for the closed
# vocabulary this agent listens for, and small enough to ship on a phone.
VOSK_MODELS = {
    "hi": ("vosk-model-small-hi-0.22", f"{VOSK_BASE}/vosk-model-small-hi-0.22.zip"),
    "en": ("vosk-model-small-en-in-0.4", f"{VOSK_BASE}/vosk-model-small-en-in-0.4.zip"),
}

# Piper needs both the .onnx and its .onnx.json config beside it.
PIPER_VOICES = {
    "hi": ("hi_IN-pratham-medium.onnx", f"{PIPER_BASE}/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx"),
    "en": ("en_US-lessac-medium.onnx", f"{PIPER_BASE}/en/en_US/lessac/medium/en_US-lessac-medium.onnx"),
}


def _progress(done: int, total: int, label: str) -> None:
    if total <= 0:
        sys.stdout.write(f"\r  {label}: {done / 1e6:.1f} MB")
    else:
        pct = done * 100 // total
        bar = "#" * (pct // 4) + "." * (25 - pct // 4)
        sys.stdout.write(f"\r  {label}: [{bar}] {pct:3d}%  {done / 1e6:.1f} MB")
    sys.stdout.flush()


def download(url: str, dest: Path, label: str) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(dest.suffix + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "crop-sathi"})
        with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response, \
                open(temp, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                _progress(done, total, label)
        print()
        temp.replace(dest)
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"\n  FAILED {label}: {exc}")
        temp.unlink(missing_ok=True)
        return False


def fetch_vosk(lang: str) -> bool:
    name, url = VOSK_MODELS[lang]
    target = VOICE_DIR / name
    if target.is_dir():
        print(f"[vosk:{lang}] already present -> {target.name}")
        return True

    print(f"[vosk:{lang}] downloading {name}")
    archive = VOICE_DIR / f"{name}.zip"
    if not download(url, archive, f"vosk-{lang}"):
        return False

    print(f"  extracting {archive.name}")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(VOICE_DIR)
    archive.unlink(missing_ok=True)

    # Some archives nest the model one directory deeper than its name.
    if not target.is_dir():
        for candidate in VOICE_DIR.iterdir():
            if candidate.is_dir() and candidate.name.startswith(name):
                shutil.move(str(candidate), str(target))
                break
    return target.is_dir()


def fetch_piper(lang: str) -> bool:
    name, url = PIPER_VOICES[lang]
    model = VOICE_DIR / name
    config = VOICE_DIR / f"{name}.json"

    if model.is_file() and config.is_file():
        print(f"[piper:{lang}] already present -> {model.name}")
        return True

    print(f"[piper:{lang}] downloading {name}")
    ok = model.is_file() or download(url, model, f"piper-{lang}")
    # The .json sits next to the .onnx in the same directory upstream.
    ok = ok and (config.is_file() or download(url + ".json", config, f"piper-{lang}-cfg"))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=["hi", "en", "all"], default="all")
    parser.add_argument("--skip-asr", action="store_true", help="only fetch Piper voices")
    parser.add_argument("--skip-tts", action="store_true", help="only fetch Vosk models")
    args = parser.parse_args()

    languages = ["hi", "en"] if args.lang == "all" else [args.lang]
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Voice models -> {VOICE_DIR}\n")

    failures = []
    for lang in languages:
        if not args.skip_asr and not fetch_vosk(lang):
            failures.append(f"vosk:{lang}")
        if not args.skip_tts and not fetch_piper(lang):
            failures.append(f"piper:{lang}")

    print()
    if failures:
        print(f"Incomplete: {', '.join(failures)}")
        print("Re-run to retry — completed downloads are skipped.")
        return 1

    print("All voice models ready. Start the server and open the Voice tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
