"""
In-memory session store.

Conversations are short and disposable, and the server is meant to run on the
same machine (or village-level box) as the app, so there is no database here.
Sessions expire so a long-running server does not accumulate them.
"""

import time
import uuid
from threading import Lock
from typing import Optional

from voice.dialogue import Session

SESSION_TTL_SECONDS = 30 * 60
MAX_SESSIONS = 500

_sessions: dict[str, tuple[Session, float]] = {}
_lock = Lock()


def create(lang: str) -> Session:
    session = Session(session_id=uuid.uuid4().hex, lang=lang)
    with _lock:
        _prune_locked()
        _sessions[session.session_id] = (session, time.time())
    return session


def get(session_id: str) -> Optional[Session]:
    with _lock:
        entry = _sessions.get(session_id)
        if entry is None:
            return None
        session, created = entry
        if time.time() - created > SESSION_TTL_SECONDS:
            del _sessions[session_id]
            return None
        return session


def drop(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def _prune_locked() -> None:
    now = time.time()
    expired = [sid for sid, (_, created) in _sessions.items()
               if now - created > SESSION_TTL_SECONDS]
    for sid in expired:
        del _sessions[sid]

    # Hard cap as a backstop against a client that never stops creating sessions.
    if len(_sessions) >= MAX_SESSIONS:
        oldest = sorted(_sessions.items(), key=lambda kv: kv[1][1])
        for sid, _ in oldest[: len(_sessions) - MAX_SESSIONS + 1]:
            del _sessions[sid]
