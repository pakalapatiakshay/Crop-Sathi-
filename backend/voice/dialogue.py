"""
The dialogue state machine.

One `step()` call takes the farmer's transcribed speech, advances exactly one
state, and returns the sentence to speak plus what the client should do next.
There is no model in this loop: the reply is always a phrasebook template, and
the only free values substituted into it come from a validated slot or from a
prediction the ML service actually returned.

Failure is explicit. Every state counts its own retries, re-asks with a more
specific prompt, and after MAX_RETRIES hands off to the touch UI rather than
accepting a low-confidence guess.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from services import ml_service, soil_service
from voice import phrasebook, slots
from voice.phrasebook import DEFAULT_LANGUAGE, render

MAX_RETRIES = 3

# Below this, a crop recommendation is spoken with an explicit hedge.
CROP_CONFIDENCE_FLOOR = 0.60
# Below this, a diagnosis is not spoken at all — see `_handle_photo`.
DISEASE_CONFIDENCE_FLOOR = 0.75


class State(str, Enum):
    WELCOME = "welcome"
    ASK_NAME = "ask_name"
    ASK_INTENT = "ask_intent"
    ASK_DISTRICT = "ask_district"
    ASK_BLOCK = "ask_block"
    ASK_VILLAGE = "ask_village"
    ASK_SEASON = "ask_season"
    OFFER_DISEASE = "offer_disease"
    AWAIT_PHOTO = "await_photo"
    ASK_ANYTHING_ELSE = "ask_anything_else"
    DONE = "done"


class Action(str, Enum):
    """What the client should do after speaking the reply."""
    LISTEN = "listen"        # capture the next utterance
    CAPTURE_PHOTO = "capture_photo"
    END = "end"


@dataclass
class Session:
    session_id: str
    lang: str = DEFAULT_LANGUAGE
    state: State = State.WELCOME
    retries: int = 0

    name: Optional[str] = None
    district: Optional[str] = None
    block: Optional[str] = None
    village: Optional[dict[str, Any]] = None
    soil: Optional[dict[str, Any]] = None
    season: Optional[str] = None
    intent: Optional[str] = None

    last_crop: Optional[dict[str, Any]] = None
    last_disease: Optional[dict[str, Any]] = None
    transcript: list[dict[str, str]] = field(default_factory=list)

    def slots_snapshot(self) -> dict[str, Any]:
        """Filled slots, surfaced so the UI can mirror the conversation."""
        return {
            "name": self.name,
            "district": self.district,
            "block": self.block,
            "village": self.village["village_name"] if self.village else None,
            "village_code": self.village["village_code"] if self.village else None,
            "season": self.season,
            "soil": self.soil,
            "intent": self.intent,
        }


@dataclass
class Reply:
    text: str
    action: Action
    state: State
    slots: dict[str, Any]
    data: Optional[dict[str, Any]] = None   # model output, for on-screen display
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "action": self.action.value,
            "state": self.state.value,
            "slots": self.slots,
            "data": self.data,
            "options": self.options,
        }


def _say(session: Session, *keys: str, **fmt: Any) -> str:
    """Concatenate one or more phrasebook lines into a single spoken turn."""
    return " ".join(render(key, session.lang, **fmt) for key in keys)


def _spoken_pct(confidence: float) -> int:
    """
    Confidence as a percentage for speech, never rounded up to 100.

    The crop model routinely returns 0.9993, and "the model is 100 percent
    confident" is a claim no model should make out loud to a farmer.
    """
    return min(99, int(confidence * 100))


def start(session: Session) -> Reply:
    """Opening turn. Speaks the greeting and asks for a name."""
    session.state = State.ASK_NAME
    session.retries = 0
    text = _say(session, "welcome", "ask_name")
    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())


def step(session: Session, utterance: str) -> Reply:
    """Advance the conversation by one turn."""
    utterance = (utterance or "").strip()
    session.transcript.append({"role": "farmer", "text": utterance})

    handler = _HANDLERS.get(session.state)
    if handler is None:
        reply = _finish(session)
    else:
        reply = handler(session, utterance)

    session.transcript.append({"role": "agent", "text": reply.text})
    return reply


def expected_vocabulary(session: Session) -> list[str]:
    """
    The closed set of answers valid for the current state, in the spoken
    language, or [] when the answer is open-ended.

    The speech layer uses this as a recognition grammar. It is derived from the
    same data the extractors validate against, so the recogniser and the
    dialogue can never disagree about what counts as a legal answer.
    """
    lang = session.lang

    if session.state == State.ASK_DISTRICT:
        return [phrasebook.speakable_place(d, lang)
                for d in soil_service.list_districts()]

    if session.state == State.ASK_BLOCK:
        blocks = soil_service.list_blocks(session.district) or []
        return [phrasebook.speakable_place(b, lang) for b in blocks]

    if session.state == State.ASK_VILLAGE:
        villages = soil_service.list_villages(session.district, session.block) or []
        return [phrasebook.speakable_place(v["village_name"], lang) for v in villages]

    if session.state == State.ASK_SEASON:
        return phrasebook.listen_vocabulary("season", lang)

    if session.state in (State.OFFER_DISEASE, State.AWAIT_PHOTO):
        return phrasebook.listen_vocabulary("yes_no", lang)

    if session.state in (State.ASK_INTENT, State.ASK_ANYTHING_ELSE):
        return phrasebook.listen_vocabulary("intent", lang)

    # ASK_NAME is deliberately open — a name cannot come from a fixed list.
    return []


def _retry(session: Session, retry_key: str, *, fallback_state: Optional[State] = None) -> Reply:
    """
    Re-ask the current question. After MAX_RETRIES, stop insisting and point the
    farmer at the touch UI — repeating a question a farmer cannot answer is worse
    than admitting the speech layer is struggling.
    """
    session.retries += 1
    if session.retries >= MAX_RETRIES:
        session.retries = 0
        if fallback_state is not None:
            session.state = fallback_state
        text = _say(session, "give_up")
        return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())
    text = _say(session, retry_key)
    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())


# ── Handlers ─────────────────────────────────────────────────────────────

def _handle_name(session: Session, utterance: str) -> Reply:
    name = slots.extract_name(utterance)
    if not name:
        return _retry(session, "ask_name_retry")

    session.name = name
    session.retries = 0
    session.state = State.ASK_INTENT
    text = _say(session, "greet_name", name=name) + " " + _say(session, "ask_intent")
    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())


def _handle_intent(session: Session, utterance: str) -> Reply:
    intent = slots.extract_intent(utterance)
    if intent is None:
        return _retry(session, "ask_intent_retry")

    session.retries = 0
    session.intent = intent

    if intent == "exit":
        return _finish(session)

    if intent == "disease":
        session.state = State.AWAIT_PHOTO
        text = _say(session, "ask_photo")
        return Reply(text, Action.CAPTURE_PHOTO, session.state, session.slots_snapshot())

    # Crop path needs a location before it can use measured soil.
    session.state = State.ASK_DISTRICT
    text = _say(session, "ask_district")
    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())


def _handle_district(session: Session, utterance: str) -> Reply:
    districts = soil_service.list_districts()
    match, suggestions = slots.resolve_district(utterance, districts)

    if match is None:
        if suggestions:
            session.retries += 1
            text = _say(
                session, "district_options",
                options=phrasebook.join_options(
                    [phrasebook.speakable_place(s, session.lang) for s in suggestions],
                    session.lang),
            )
            return Reply(text, Action.LISTEN, session.state,
                         session.slots_snapshot(), options=suggestions)
        return _retry(session, "ask_district_retry")

    session.district = match
    session.retries = 0
    session.state = State.ASK_BLOCK
    text = _say(session, "ask_block",
                district=phrasebook.speakable_place(match, session.lang))
    blocks = soil_service.list_blocks(match) or []
    return Reply(text, Action.LISTEN, session.state,
                 session.slots_snapshot(), options=blocks)


def _handle_block(session: Session, utterance: str) -> Reply:
    blocks = soil_service.list_blocks(session.district) or []
    match, suggestions = slots.resolve_block(utterance, blocks)

    if match is None:
        if suggestions:
            session.retries += 1
            text = _say(
                session, "district_options",
                options=phrasebook.join_options(
                    [phrasebook.speakable_place(s, session.lang) for s in suggestions],
                    session.lang),
            )
            return Reply(text, Action.LISTEN, session.state,
                         session.slots_snapshot(), options=suggestions)
        return _retry(session, "ask_block_retry")

    session.block = match
    session.retries = 0
    session.state = State.ASK_VILLAGE
    text = _say(session, "ask_village")
    villages = soil_service.list_villages(session.district, match) or []
    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot(),
                 options=[v["village_name"] for v in villages])


def _handle_village(session: Session, utterance: str) -> Reply:
    villages = soil_service.list_villages(session.district, session.block) or []
    match, suggestions = slots.resolve_village(utterance, villages)

    if match is None:
        if suggestions:
            session.retries += 1
            text = _say(
                session, "district_options",
                options=phrasebook.join_options(
                    [phrasebook.speakable_place(s, session.lang) for s in suggestions],
                    session.lang),
            )
            return Reply(text, Action.LISTEN, session.state,
                         session.slots_snapshot(), options=suggestions)
        return _retry(session, "ask_village_retry")

    session.village = match
    session.soil = soil_service.get_profile(match["village_code"])
    session.retries = 0
    session.state = State.ASK_SEASON

    if session.soil is None:
        text = _say(session, "no_soil_data") + " " + _say(session, "ask_season")
    else:
        text = _say(
            session, "soil_found",
            village=phrasebook.speakable_place(match["village_name"], session.lang),
            n=session.soil["N"], p=session.soil["P"], k=session.soil["K"],
            ph=session.soil["ph"],
        ) + " " + _say(session, "ask_season")

    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())


def _handle_season(session: Session, utterance: str) -> Reply:
    season = slots.extract_season(utterance)
    if season is None:
        return _retry(session, "ask_season_retry")

    session.season = season
    session.retries = 0
    return _recommend_crop(session)


def _recommend_crop(session: Session) -> Reply:
    """Call the real model and speak only what it returned."""
    soil = session.soil
    if soil is None:
        # No measured village soil: fall back to the dataset medians rather
        # than inventing numbers. Kept inside the model's training range.
        soil = {"N": 34, "P": 55, "K": 26, "ph": 6.3}

    climate = slots.SEASON_CLIMATE[session.season]

    try:
        result = ml_service.predict_crop(
            n=int(soil["N"]), p=int(soil["P"]), k=int(soil["K"]),
            ph=float(soil["ph"]),
            rainfall=slots.SEASON_RAINFALL_MM[session.season],
            temperature=climate["temperature"],
            humidity=climate["humidity"],
        )
    except Exception:
        session.state = State.ASK_ANYTHING_ELSE
        text = _say(session, "crop_failed") + " " + _say(session, "offer_anything_else")
        return Reply(text, Action.LISTEN, session.state, session.slots_snapshot())

    session.last_crop = result
    confidence = float(result.get("confidence") or 0.0)
    crop = phrasebook.crop_name(result["prediction"], session.lang)
    confidence_pct = _spoken_pct(confidence)

    key = "crop_result_high" if confidence >= CROP_CONFIDENCE_FLOOR else "crop_result_low"
    text = _say(session, key, crop=crop, confidence=confidence_pct)

    # Read out runners-up only when they came back from the model.
    top_3 = result.get("top_3") or []
    if len(top_3) >= 3:
        text += " " + _say(
            session, "crop_alternatives",
            second=phrasebook.crop_name(top_3[1], session.lang),
            third=phrasebook.crop_name(top_3[2], session.lang),
        )

    session.state = State.OFFER_DISEASE
    text += " " + _say(session, "offer_disease")
    return Reply(text, Action.LISTEN, session.state, session.slots_snapshot(), data=result)


def _handle_offer_disease(session: Session, utterance: str) -> Reply:
    answer = slots.extract_yes_no(utterance)
    if answer is None:
        return _retry(session, "yes_no_retry")

    session.retries = 0
    if not answer:
        return _finish(session)

    session.state = State.AWAIT_PHOTO
    text = _say(session, "ask_photo")
    return Reply(text, Action.CAPTURE_PHOTO, session.state, session.slots_snapshot())


def _handle_await_photo(session: Session, utterance: str) -> Reply:
    """
    Reached when the farmer speaks instead of sending a photo — usually to back
    out. Anything else just re-states the instruction.
    """
    if slots.extract_yes_no(utterance) is False or slots.extract_intent(utterance) == "exit":
        return _finish(session)
    text = _say(session, "ask_photo")
    return Reply(text, Action.CAPTURE_PHOTO, session.state, session.slots_snapshot())


def _diagnosis_is_speakable(result: dict[str, Any]) -> bool:
    """
    Whether a diagnosis carries a real label rather than a bare class index.

    ml_service builds DISEASE_CLASSES from disease_classes.json, which is
    gitignored and therefore absent on a fresh clone. When it is missing the
    list is empty and predictions come back as "class_19" / "Unknown", which
    must never be read out as if it named a plant or a disease.
    """
    label = str(result.get("predicted_class") or "")
    plant = str(result.get("plant_name") or "").strip()
    status = str(result.get("disease_status") or "").strip()

    if not label or re.fullmatch(r"class[_ ]?\d+", label.strip(), re.IGNORECASE):
        return False
    if not plant or re.fullmatch(r"class[_ ]?\d+", plant, re.IGNORECASE):
        return False
    return status.lower() != "unknown"


def handle_photo(session: Session, image_bytes: bytes,
                 model: str = "efficientnet_b4") -> Reply:
    """
    Diagnose a leaf photo.

    The confidence gate here is deliberately strict. The disease models are the
    weak part of this system (their serving preprocessing does not match how
    they were trained), so anything below DISEASE_CONFIDENCE_FLOOR is reported
    as "I could not tell" rather than spoken as a diagnosis. A farmer who
    sprays the wrong chemical because the agent sounded certain is a far worse
    outcome than being asked to retake the photo.
    """
    try:
        result = ml_service.predict_disease(image_bytes, model_name=model)
    except Exception:
        session.state = State.ASK_ANYTHING_ELSE
        text = _say(session, "disease_failed") + " " + _say(session, "offer_anything_else")
        reply = Reply(text, Action.LISTEN, session.state, session.slots_snapshot())
        session.transcript.append({"role": "agent", "text": reply.text})
        return reply

    session.last_disease = result
    confidence = float(result.get("confidence") or 0.0)
    session.state = State.ASK_ANYTHING_ELSE

    if confidence < DISEASE_CONFIDENCE_FLOOR or not _diagnosis_is_speakable(result):
        text = _say(session, "disease_uncertain")
    else:
        plant = phrasebook.plant_name(result.get("plant_name", ""), session.lang)
        status = result.get("disease_status", "")
        if status.strip().lower() == "healthy":
            text = _say(session, "disease_healthy", plant=plant)
        else:
            text = _say(
                session, "disease_found",
                plant=plant,
                disease=phrasebook.disease_name(status, session.lang),
                confidence=_spoken_pct(confidence),
            )

    text += " " + _say(session, "offer_anything_else")
    reply = Reply(text, Action.LISTEN, session.state, session.slots_snapshot(), data=result)
    session.transcript.append({"role": "agent", "text": reply.text})
    return reply


def _handle_anything_else(session: Session, utterance: str) -> Reply:
    intent = slots.extract_intent(utterance)
    if intent == "crop":
        session.retries = 0
        session.intent = "crop"
        # Location already known — go straight back to the model.
        if session.village is not None and session.season is not None:
            return _recommend_crop(session)
        session.state = State.ASK_DISTRICT
        return Reply(_say(session, "ask_district"), Action.LISTEN,
                     session.state, session.slots_snapshot())

    if intent == "disease":
        session.retries = 0
        session.intent = "disease"
        session.state = State.AWAIT_PHOTO
        return Reply(_say(session, "ask_photo"), Action.CAPTURE_PHOTO,
                     session.state, session.slots_snapshot())

    if intent == "exit" or slots.extract_yes_no(utterance) is False:
        return _finish(session)

    return _retry(session, "ask_intent_retry")


def _finish(session: Session) -> Reply:
    session.state = State.DONE
    text = _say(session, "goodbye", name=session.name or "")
    return Reply(text, Action.END, session.state, session.slots_snapshot())


_HANDLERS = {
    State.ASK_NAME: _handle_name,
    State.ASK_INTENT: _handle_intent,
    State.ASK_DISTRICT: _handle_district,
    State.ASK_BLOCK: _handle_block,
    State.ASK_VILLAGE: _handle_village,
    State.ASK_SEASON: _handle_season,
    State.OFFER_DISEASE: _handle_offer_disease,
    State.AWAIT_PHOTO: _handle_await_photo,
    State.ASK_ANYTHING_ELSE: _handle_anything_else,
    State.DONE: _finish,
}
