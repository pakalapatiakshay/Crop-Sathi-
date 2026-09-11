"""
Voice agent endpoints.

Two ways to drive the same conversation:

  /voice/listen  post recorded audio  → server transcribes with Vosk
  /voice/say     post text            → for browser-side speech, or testing

Both return the agent's next line. Audio for that line comes from /voice/speak,
kept separate so a client using the browser's own synthesiser can skip it.
"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from db.schemas import VoiceReply, VoiceStartRequest, VoiceStatusResponse
from voice import dialogue, session_store, speech
from voice.phrasebook import DEFAULT_LANGUAGE, LANGUAGES

router = APIRouter(prefix="/voice", tags=["Voice Agent"])


def _require_session(session_id: str) -> dialogue.Session:
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown or expired session. Start a new one with POST /voice/start.",
        )
    return session


def _normalise_lang(lang: str) -> str:
    lang = (lang or DEFAULT_LANGUAGE).lower()[:2]
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


@router.get("/status", response_model=VoiceStatusResponse)
def voice_status():
    """Which speech providers are active and whether their models are present."""
    return VoiceStatusResponse(success=True, **speech.status())


@router.post("/start", response_model=VoiceReply)
def start(body: VoiceStartRequest):
    """Open a conversation and get the greeting."""
    session = session_store.create(_normalise_lang(body.lang))
    reply = dialogue.start(session)
    return VoiceReply(success=True, session_id=session.session_id, **reply.to_dict())


@router.post("/say", response_model=VoiceReply)
def say(session_id: str = Form(...), text: str = Form(...)):
    """Advance the conversation with already-transcribed text."""
    session = _require_session(session_id)
    reply = dialogue.step(session, text)
    return VoiceReply(
        success=True, session_id=session.session_id, transcript=text, **reply.to_dict()
    )


@router.post("/listen", response_model=VoiceReply)
async def listen(session_id: str = Form(...), audio: UploadFile = File(...)):
    """Transcribe recorded speech, then advance the conversation."""
    session = _require_session(session_id)

    # Constrain recognition to the answers this state accepts — see
    # dialogue.expected_vocabulary. Captured before step() advances the state.
    vocabulary = dialogue.expected_vocabulary(session)

    try:
        transcript = speech.get_asr().transcribe(
            await audio.read(), session.lang, vocabulary=vocabulary
        )
    except speech.SpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read audio: {exc}")

    reply = dialogue.step(session, transcript)
    return VoiceReply(
        success=True, session_id=session.session_id, transcript=transcript,
        **reply.to_dict()
    )


DISEASE_MODELS = ("efficientnet_b4", "resnet50", "resnet9")


@router.post("/photo", response_model=VoiceReply)
async def photo(
    session_id: str = Form(...),
    file: UploadFile = File(...),
    model: str = Form("efficientnet_b4"),
):
    """
    Submit a leaf photo while the agent is waiting for one.

    Defaults to the same model ml_service prefers; it falls back on its own
    when that one is not loaded, so asking for it is safe either way.
    """
    session = _require_session(session_id)
    if model not in DISEASE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"model must be one of {', '.join(DISEASE_MODELS)}",
        )

    reply = dialogue.handle_photo(session, await file.read(), model=model)
    return VoiceReply(success=True, session_id=session.session_id, **reply.to_dict())


@router.post("/speak")
def speak(text: str = Form(...), lang: str = Form(DEFAULT_LANGUAGE)):
    """Synthesise a line to WAV. Returns 204 when the client should speak it itself."""
    try:
        audio = speech.get_tts().synthesize(text, _normalise_lang(lang))
    except speech.SpeechUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/wav")


@router.delete("/{session_id}")
def end_session(session_id: str):
    session_store.drop(session_id)
    return {"success": True}
