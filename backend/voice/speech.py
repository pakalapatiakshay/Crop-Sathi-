"""
Speech in and out, behind two small interfaces.

The dialogue never imports a provider directly — it only ever sees text — so
swapping Vosk for Bhashini changes one environment variable and nothing else.

Providers:
  vosk     offline speech recognition  (default)
  piper    offline speech synthesis    (default)
  browser  no-op; the PWA does the work with the Web Speech API
  bhashini online, for when credentials exist

Everything offline is loaded lazily. A missing model degrades to a clear error
on the voice endpoints instead of breaking server startup, so the rest of
Crop-Sathi keeps working whether or not the voice models were downloaded.
"""

import json
import os
import wave
from io import BytesIO
from pathlib import Path
from typing import Optional, Protocol

import numpy as np

from core.config import BASE_DIR

VOICE_MODELS_DIR = Path(os.getenv("VOICE_MODELS_DIR", BASE_DIR / "ml_models" / "voice"))

ASR_PROVIDER = os.getenv("VOICE_ASR_PROVIDER", "vosk").lower()
TTS_PROVIDER = os.getenv("VOICE_TTS_PROVIDER", "piper").lower()

BHASHINI_API_KEY = os.getenv("BHASHINI_API_KEY", "")
BHASHINI_USER_ID = os.getenv("BHASHINI_USER_ID", "")
BHASHINI_PIPELINE_ID = os.getenv("BHASHINI_PIPELINE_ID", "")

# Vosk model directory names, relative to VOICE_MODELS_DIR.
VOSK_MODELS = {
    "hi": os.getenv("VOSK_MODEL_HI", "vosk-model-small-hi-0.22"),
    "en": os.getenv("VOSK_MODEL_EN", "vosk-model-small-en-in-0.4"),
}

# Piper voice files (.onnx alongside its .onnx.json), relative to VOICE_MODELS_DIR.
PIPER_VOICES = {
    "hi": os.getenv("PIPER_VOICE_HI", "hi_IN-pratham-medium.onnx"),
    "en": os.getenv("PIPER_VOICE_EN", "en_US-lessac-medium.onnx"),
}


class SpeechUnavailable(RuntimeError):
    """Raised when a provider cannot serve a request (missing model or key)."""


class ASRProvider(Protocol):
    def transcribe(self, audio: bytes, lang: str,
                   vocabulary: Optional[list[str]] = None) -> str: ...
    def is_ready(self, lang: str) -> bool: ...


# Vosk grammars are limited to words the model already knows, and a grammar
# containing an unknown word yields an empty transcript for the whole turn.
# Vosk's Hindi lexicon stores plain forms, so the nukta is dropped here.
_NUKTA_CHAR = "़"
MAX_GRAMMAR_WORDS = 900


def _build_grammar(vocabulary: list[str]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for entry in vocabulary:
        cleaned = " ".join(entry.replace(_NUKTA_CHAR, "").lower().split())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            words.append(cleaned)
    if not words or len(words) > MAX_GRAMMAR_WORDS:
        return []          # too broad to help; open recognition does better
    words.append("[unk]")  # lets Vosk reject rather than force a wrong match
    return words


class TTSProvider(Protocol):
    def synthesize(self, text: str, lang: str) -> bytes: ...
    def is_ready(self, lang: str) -> bool: ...


# ── Audio helpers ────────────────────────────────────────────────────────

TARGET_SAMPLE_RATE = 16000

_SAMPLE_DTYPES = {1: np.uint8, 2: np.int16, 4: np.int32}


def _to_mono_16k_pcm(audio: bytes) -> bytes:
    """
    Normalise incoming WAV to the 16 kHz mono 16-bit PCM Vosk expects.

    Browsers hand back whatever their AudioContext produced, commonly 44.1 or
    48 kHz. Feeding that to Vosk at the wrong rate does not raise — it silently
    transcribes gibberish — so the rate is always enforced here.

    Implemented with numpy rather than the stdlib `audioop`, which was removed
    in Python 3.13.
    """
    with wave.open(BytesIO(audio), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    dtype = _SAMPLE_DTYPES.get(width)
    if dtype is None:
        raise SpeechUnavailable(f"Unsupported WAV sample width: {width} bytes")

    samples = np.frombuffer(frames, dtype=dtype).astype(np.float32)
    if width == 1:            # 8-bit WAV is unsigned, centred on 128
        samples = (samples - 128.0) * 256.0
    elif width == 4:
        samples = samples / 65536.0

    if channels > 1:
        usable = (len(samples) // channels) * channels
        samples = samples[:usable].reshape(-1, channels).mean(axis=1)

    if rate != TARGET_SAMPLE_RATE and len(samples):
        target_len = int(round(len(samples) * TARGET_SAMPLE_RATE / rate))
        if target_len > 0:
            samples = np.interp(
                np.linspace(0.0, len(samples) - 1.0, target_len, dtype=np.float32),
                np.arange(len(samples), dtype=np.float32),
                samples,
            )

    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


# ── Vosk (offline ASR) ───────────────────────────────────────────────────

class VoskASR:
    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def _model_path(self, lang: str) -> Path:
        return VOICE_MODELS_DIR / VOSK_MODELS.get(lang, VOSK_MODELS["en"])

    def is_ready(self, lang: str) -> bool:
        return self._model_path(lang).is_dir()

    def _load(self, lang: str):
        if lang in self._models:
            return self._models[lang]
        path = self._model_path(lang)
        if not path.is_dir():
            raise SpeechUnavailable(
                f"Vosk model for '{lang}' not found at {path}. "
                f"Run `python scripts/download_voice_models.py`."
            )
        try:
            from vosk import Model, SetLogLevel
        except ImportError as exc:
            raise SpeechUnavailable(
                "The 'vosk' package is not installed. Run `pip install vosk`."
            ) from exc
        SetLogLevel(-1)
        model = Model(str(path))
        self._models[lang] = model
        return model

    def transcribe(self, audio: bytes, lang: str,
                   vocabulary: Optional[list[str]] = None) -> str:
        """
        Transcribe one utterance, optionally restricted to `vocabulary`.

        Isolated proper nouns are where a small model fails worst — "रांची"
        comes back as "राजीव" in open recognition. Because the dialogue always
        knows what it is expecting, it can hand over that turn's closed
        vocabulary and Vosk will only emit those words, which fixes almost all
        of those errors.

        The constrained pass can return nothing when a word is absent from the
        model's lexicon, so open recognition runs as a fallback and the fuzzy
        matcher in slots.py sorts out what came back.
        """
        from vosk import KaldiRecognizer

        model = self._load(lang)
        pcm = _to_mono_16k_pcm(audio)

        if vocabulary:
            grammar = _build_grammar(vocabulary)
            if grammar:
                try:
                    recognizer = KaldiRecognizer(
                        model, TARGET_SAMPLE_RATE,
                        json.dumps(grammar, ensure_ascii=False),
                    )
                    recognizer.AcceptWaveform(pcm)
                    text = (json.loads(recognizer.FinalResult()).get("text") or "").strip()
                    if text and text != "[unk]":
                        return text
                except Exception:
                    pass  # fall through to open recognition

        recognizer = KaldiRecognizer(model, TARGET_SAMPLE_RATE)
        recognizer.AcceptWaveform(pcm)
        return (json.loads(recognizer.FinalResult()).get("text") or "").strip()


# ── Piper (offline TTS) ──────────────────────────────────────────────────

class PiperTTS:
    def __init__(self) -> None:
        self._voices: dict[str, object] = {}

    def _voice_path(self, lang: str) -> Path:
        return VOICE_MODELS_DIR / PIPER_VOICES.get(lang, PIPER_VOICES["en"])

    def is_ready(self, lang: str) -> bool:
        path = self._voice_path(lang)
        return path.is_file() and path.with_suffix(".onnx.json").is_file()

    def _load(self, lang: str):
        if lang in self._voices:
            return self._voices[lang]
        path = self._voice_path(lang)
        if not path.is_file():
            raise SpeechUnavailable(
                f"Piper voice for '{lang}' not found at {path}. "
                f"Run `python scripts/download_voice_models.py`."
            )
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise SpeechUnavailable(
                "The 'piper-tts' package is not installed. Run `pip install piper-tts`."
            ) from exc
        voice = PiperVoice.load(str(path))
        self._voices[lang] = voice
        return voice

    def synthesize(self, text: str, lang: str) -> bytes:
        voice = self._load(lang)
        buffer = BytesIO()
        # synthesize_wav writes the header and frames; the plain synthesize()
        # returns an audio-chunk iterator and would leave the file empty.
        with wave.open(buffer, "wb") as wav:
            voice.synthesize_wav(text, wav)
        return buffer.getvalue()


# ── Browser (the PWA handles speech itself) ──────────────────────────────

class BrowserASR:
    """The client already transcribed; the posted text passes straight through."""

    def is_ready(self, lang: str) -> bool:
        return True

    def transcribe(self, audio: bytes, lang: str,
                   vocabulary: Optional[list[str]] = None) -> str:
        raise SpeechUnavailable(
            "ASR provider is 'browser' — post the transcript to /voice/say instead "
            "of audio to /voice/listen."
        )


class BrowserTTS:
    """Returns no audio; the client speaks the reply with speechSynthesis."""

    def is_ready(self, lang: str) -> bool:
        return True

    def synthesize(self, text: str, lang: str) -> bytes:
        return b""


# ── Bhashini (online) ────────────────────────────────────────────────────

class BhashiniASR:
    """
    Adapter for Bhashini's ASR pipeline.

    Left unimplemented on purpose: the request shape depends on the pipeline ID
    issued with your credentials, and guessing it would produce code that looks
    finished but fails on first contact. Fill in `transcribe` once you have the
    ULCA config, and set VOICE_ASR_PROVIDER=bhashini.
    """

    def is_ready(self, lang: str) -> bool:
        return bool(BHASHINI_API_KEY and BHASHINI_PIPELINE_ID)

    def transcribe(self, audio: bytes, lang: str,
                   vocabulary: Optional[list[str]] = None) -> str:
        raise SpeechUnavailable(
            "Bhashini ASR is not configured. Set BHASHINI_API_KEY, BHASHINI_USER_ID "
            "and BHASHINI_PIPELINE_ID, then implement BhashiniASR.transcribe()."
        )


class BhashiniTTS:
    def is_ready(self, lang: str) -> bool:
        return bool(BHASHINI_API_KEY and BHASHINI_PIPELINE_ID)

    def synthesize(self, text: str, lang: str) -> bytes:
        raise SpeechUnavailable(
            "Bhashini TTS is not configured. Set BHASHINI_API_KEY, BHASHINI_USER_ID "
            "and BHASHINI_PIPELINE_ID, then implement BhashiniTTS.synthesize()."
        )


_ASR_PROVIDERS = {"vosk": VoskASR, "browser": BrowserASR, "bhashini": BhashiniASR}
_TTS_PROVIDERS = {"piper": PiperTTS, "browser": BrowserTTS, "bhashini": BhashiniTTS}

_asr: Optional[ASRProvider] = None
_tts: Optional[TTSProvider] = None


def get_asr() -> ASRProvider:
    global _asr
    if _asr is None:
        _asr = _ASR_PROVIDERS.get(ASR_PROVIDER, VoskASR)()
    return _asr


def get_tts() -> TTSProvider:
    global _tts
    if _tts is None:
        _tts = _TTS_PROVIDERS.get(TTS_PROVIDER, PiperTTS)()
    return _tts


def status() -> dict:
    """Which providers are active and whether their models are actually present."""
    asr, tts = get_asr(), get_tts()
    return {
        "asr_provider": ASR_PROVIDER,
        "tts_provider": TTS_PROVIDER,
        "models_dir": str(VOICE_MODELS_DIR),
        "languages": {
            lang: {"asr_ready": asr.is_ready(lang), "tts_ready": tts.is_ready(lang)}
            for lang in ("hi", "en")
        },
    }
