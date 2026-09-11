"""
Deterministic slot extraction.

Nothing here generates language or infers meaning probabilistically. Every
extractor either matches speech against a closed vocabulary — the 24 real
districts, that district's real blocks, that block's real villages, the fixed
intent and season words — or it returns None so the dialogue re-asks.

The consequence is that the agent can never act on a place or a crop that does
not exist in the data, which is the property an LLM-based parser cannot give.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Optional

# ── Devanagari → Latin ───────────────────────────────────────────────────
# The Hindi speech model returns Devanagari, but the soil dataset stores place
# names in Latin. Romanising one side lets a single fuzzy matcher serve both.

_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}

_INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}

_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}

_VIRAMA = "्"
_NUKTA = "़"
_NASALS = {"ं": "n", "ँ": "n", "ः": "h"}

# A nukta may arrive as a separate combining mark rather than a precomposed
# character (ज + ़ instead of ज़), which NFC does not always merge.
_NUKTA_FORMS = {
    "क": "k", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f",
}

_DEVANAGARI_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}


def romanize(text: str) -> str:
    """Transliterate Devanagari to Latin, leaving Latin text untouched."""
    text = unicodedata.normalize("NFC", text)
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _CONSONANTS:
            # Absorb a detached nukta before deciding the consonant's sound.
            if text[i + 1: i + 2] == _NUKTA:
                out.append(_NUKTA_FORMS.get(ch, _CONSONANTS[ch]))
                i += 1
            else:
                out.append(_CONSONANTS[ch])
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if nxt in _MATRAS:
                out.append(_MATRAS[nxt])
                i += 2
                continue
            if nxt == _VIRAMA:
                i += 2
                continue
            out.append("a")  # inherent vowel
            i += 1
            continue
        if ch in _INDEPENDENT_VOWELS:
            out.append(_INDEPENDENT_VOWELS[ch])
        elif ch in _NASALS:
            out.append(_NASALS[ch])
        elif ch in _DEVANAGARI_DIGITS:
            out.append(_DEVANAGARI_DIGITS[ch])
        elif ch not in _MATRAS and ch != _VIRAMA:
            out.append(ch)
        i += 1
    return "".join(out)


# ── Latin → Devanagari ───────────────────────────────────────────────────
# The soil dataset stores all 12,014 place names in Latin. Speaking those
# characters inside a Hindi sentence makes a Hindi TTS voice mispronounce or
# skip them, so names are transliterated before they are spoken.

_LATIN_CONSONANTS = [
    ("chh", "छ"), ("sh", "श"), ("ch", "च"), ("kh", "ख"), ("gh", "घ"),
    ("jh", "झ"), ("th", "थ"), ("dh", "ध"), ("ph", "फ"), ("bh", "भ"),
    ("ng", "ंग"), ("ck", "क"),
    ("k", "क"), ("g", "ग"), ("c", "क"), ("j", "ज"), ("t", "ट"), ("d", "ड"),
    ("n", "न"), ("p", "प"), ("b", "ब"), ("m", "म"), ("y", "य"), ("r", "र"),
    ("l", "ल"), ("v", "व"), ("w", "व"), ("s", "स"), ("h", "ह"), ("z", "ज़"),
    ("f", "फ़"), ("q", "क"), ("x", "क्स"),
]

_LATIN_VOWELS = [
    ("aa", "ा", "आ"), ("ai", "ै", "ऐ"), ("au", "ौ", "औ"), ("ee", "ी", "ई"),
    ("ii", "ी", "ई"), ("oo", "ू", "ऊ"), ("uu", "ू", "ऊ"),
    ("a", "", "अ"), ("i", "ि", "इ"), ("u", "ु", "उ"),
    ("e", "े", "ए"), ("o", "ो", "ओ"),
]

_VOWEL_LETTERS = set("aeiou")


# Anusvara stands in for a nasal only before a stop (कंके), never before a
# sonorant — गुमला must not become गुंला.
_STOPS = set("कखगघचछजझटठडढतथदधपफबभ")
# ...and only where the nasal is homorganic with that stop. A dental/palatal
# 'n' assimilates to any stop, but 'm' only does before a labial: Dumka is
# दुमका, not डुंका, because anusvara before क would be read as "ng".
_LABIAL_STOPS = set("पफबभ")


def _match_consonant(word: str, i: int) -> tuple[str, int]:
    for latin, deva in _LATIN_CONSONANTS:
        if word.startswith(latin, i):
            return deva, i + len(latin)
    return "", i + 1  # unknown character (digit, apostrophe) — skip


def _transliterate_word(word: str) -> str:
    """
    Left-to-right, one consonant at a time.

    Medial clusters are written with the inherent vowel rather than a virama:
    Hindi speech synthesis applies its own schwa deletion, so लोहरदगा is read
    "Lohardaga" correctly, whereas the conjunct form लोहर्डग is not how the
    name is spelled and reads worse.
    """
    word = word.lower()
    out: list[str] = []
    i = 0

    while i < len(word):
        ch = word[i]

        if ch in _VOWEL_LETTERS:
            for latin, matra, independent in _LATIN_VOWELS:
                if word.startswith(latin, i):
                    # A vowel here is syllable-initial; a vowel following a
                    # consonant is consumed by the consonant branch below.
                    out.append(independent)
                    i += len(latin)
                    break
            else:
                i += 1
            continue

        deva, next_i = _match_consonant(word, i)
        if not deva:
            i = next_i
            continue

        # Nasal directly before a stop becomes anusvara on the previous syllable.
        if deva in ("न", "म") and out:
            following, _ = _match_consonant(word, next_i)
            homorganic = following in (_LABIAL_STOPS if deva == "म" else _STOPS)
            if homorganic:
                out.append("ं")
                i = next_i
                continue

        out.append(deva)
        i = next_i

        # Attach the following vowel as a matra, if there is one.
        if i < len(word) and word[i] in _VOWEL_LETTERS:
            for latin, matra, independent in _LATIN_VOWELS:
                if word.startswith(latin, i):
                    is_final = (i + len(latin)) >= len(word)
                    # English spellings write the final long आ as a bare "a"
                    # (Gumla, Chatra), so lengthen it rather than treating it
                    # as the silent inherent vowel.
                    if latin == "a" and is_final:
                        out.append("ा")
                    else:
                        out.append(matra)
                    i += len(latin)
                    break

    return "".join(out)


def to_devanagari(text: str) -> str:
    """Transliterate a Latin place name into Devanagari for speech."""
    if not text:
        return text
    return " ".join(_transliterate_word(w) if w.isascii() else w
                    for w in text.split())


def _fold(text: str) -> str:
    """
    Reduce a name to a spelling-insensitive skeleton so that Ranchi/राँची,
    Hazaribagh/Hazaribag and Singhbhum/Singhbum all collide.
    """
    s = romanize(text).lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    # Common Indic romanisation variants.
    for a, b in (
        ("aa", "a"), ("ii", "i"), ("ee", "i"), ("oo", "u"), ("uu", "u"),
        ("kh", "k"), ("gh", "g"), ("th", "t"), ("dh", "d"), ("bh", "b"),
        ("ph", "f"), ("chh", "ch"), ("sh", "s"), ("z", "j"), ("v", "w"),
        ("y", "i"),
    ):
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)  # collapse doubles
    # Romanised Devanagari ends in the inherent vowel ("naama" for नाम) that
    # Latin spellings omit, so drop a single trailing 'a'.
    if len(s) > 2 and s.endswith("a"):
        s = s[:-1]
    return s


def _skeleton(text: str) -> str:
    """
    Consonants only. Devanagari carries an inherent 'a' after every bare
    consonant, so बरसात romanises to "barasaata" while the dataset spells it
    "barsat". Dropping vowels makes those identical.
    """
    return re.sub(r"[aeiou]", "", _fold(text))


def similarity(a: str, b: str) -> float:
    fa, fb = _fold(a), _fold(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    ratio = SequenceMatcher(None, fa, fb).ratio()
    # Reward containment so "ranchi district" still matches "Ranchi", but only
    # for substrings long enough to be meaningful. Without the length floor,
    # noise words match anything: "kii" sits inside "kida", "men" inside
    # "recommend", and every sentence would trigger every intent.
    if fa in fb or fb in fa:
        if min(len(fa), len(fb)) >= 4:
            ratio = max(ratio, 0.90)

    # Compare consonant skeletons too, but only for words long enough that the
    # skeleton still carries information — otherwise "na" and "no" both collapse
    # to "n" and every short word matches every other.
    sa, sb = _skeleton(a), _skeleton(b)
    if len(sa) >= 3 and len(sb) >= 3:
        if sa == sb:
            ratio = max(ratio, 0.95)
        else:
            ratio = max(ratio, SequenceMatcher(None, sa, sb).ratio() * 0.90)
    return ratio


def best_match(
    spoken: str,
    candidates: list[str],
    threshold: float = 0.80,
) -> tuple[Optional[str], list[str]]:
    """
    Resolve speech to one of `candidates`.

    Returns (match, suggestions). A match is only returned when it is both above
    `threshold` and clearly ahead of the runner-up; otherwise the caller gets
    suggestions to read back as a menu. Refusing to pick between two near-ties is
    what stops the agent confidently sending a farmer to the wrong village.
    """
    if not spoken or not candidates:
        return None, []

    scored = sorted(
        ((similarity(spoken, c), c) for c in candidates),
        key=lambda t: t[0],
        reverse=True,
    )
    top_score, top_name = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    if top_score >= threshold and (top_score - runner_up) >= 0.05:
        return top_name, []
    if top_score >= threshold:
        # Genuine ambiguity — offer the tied names instead of guessing.
        return None, [name for score, name in scored[:3] if score >= threshold]
    near = [name for score, name in scored[:3] if score >= threshold - 0.15]
    return None, near


# ── Fixed vocabularies ───────────────────────────────────────────────────

_YES = {
    "haan", "han", "ha", "hanji", "haanji", "ji", "jee", "jihan", "yes", "yeah",
    "yep", "ok", "okay", "sahi", "thik", "theek", "thikhai", "bilkul", "achha",
    "acha", "hoga", "chahiye", "kro", "karo", "sure", "right", "correct",
    # Speech recognition reliably returns है for हाँ — the two are near
    # homophones. Negatives are tested first, so "नहीं है" still reads as no.
    "hai", "he", "haa", "hoon",
}
_NO = {
    "nahi", "nahin", "na", "naa", "no", "nope", "nai", "mat", "band", "cancel",
    "rehne", "rahne", "chhodo", "chodo", "not", "dont", "stop",
}

_INTENT_CROP = {
    "fasal", "phasal", "fsal", "crop", "kheti", "bona", "bonaa", "buwai",
    "bijai", "beej", "sujhav", "salah", "recommend", "recommendation",
    "suggest", "suggestion", "ugana", "lagana", "sow", "plant", "grow",
}
_INTENT_DISEASE = {
    "bimari", "bimaari", "bemari", "rog", "disease", "patti", "pati", "leaf",
    "kida", "keeda", "keet", "pest", "infection", "sankraman", "photo", "foto",
    "tasveer", "camera", "kharab", "sukh", "peela", "daag", "spot", "check",
    "jaanch", "janch", "scan", "diagnose",
}
_INTENT_EXIT = {
    "bas", "bass", "khatam", "band", "bye", "goodbye", "namaste", "dhanyavad",
    "thanks", "thank", "exit", "quit", "nothing", "kuch", "done", "finish",
}

_SEASONS = {
    # The extra spellings are what speech recognition actually returns for
    # these words, not alternate transliterations: खरीफ commonly comes back
    # as करीब. Seasons are a closed three-way choice, so accepting near
    # misses here cannot send the farmer anywhere unexpected.
    "kharif": {"kharif", "khareef", "kharief", "barsat", "barsaat", "monsoon",
               "sawan", "karib", "kareeb", "kharib", "khareed"},
    "rabi": {"rabi", "rabee", "ravi", "jada", "jaada", "sardi", "winter",
             "thand", "rabbi", "raabi"},
    "zaid": {"jayad", "jaid", "zaid", "jayd", "garmi", "garmee", "summer",
             "grishm", "jayed", "zayad"},
}

# Monthly rainfall (mm) fed to the crop model per season.
#
# The model's `rainfall` feature is MONTHLY rainfall — training values span
# 20-300 mm (mean 99), not seasonal totals. Values below are Jharkhand monthly
# means from IMD Ranchi normals, kept inside that range so the model is never
# asked to extrapolate:
#   kharif Jun-Oct (SW monsoon) · rabi Nov-Mar (dry) · zaid Apr-Jun (pre-monsoon)
SEASON_RAINFALL_MM = {"kharif": 220.0, "rabi": 25.0, "zaid": 50.0}

# Mean temperature (C) and humidity (%) per season, used only when there is no
# live weather — i.e. the offline path. Same IMD Ranchi source.
SEASON_CLIMATE = {
    "kharif": {"temperature": 27.5, "humidity": 82.0},
    "rabi": {"temperature": 19.5, "humidity": 55.0},
    "zaid": {"temperature": 31.0, "humidity": 45.0},
}

# Words stripped when a farmer answers a name question with a full sentence.
_NAME_NOISE = {
    "mera", "meraa", "naam", "nam", "hai", "he", "h", "ji", "jee", "hu", "hun",
    "hoon", "main", "mai", "my", "name", "is", "am", "i", "the", "sir", "madam",
    "call", "me", "they", "we",
}
_NAME_NOISE_FOLDED = {_fold(w) for w in _NAME_NOISE}


def _tokens(text: str) -> list[str]:
    roman = romanize(text).lower()
    return [t for t in re.split(r"[^a-z0-9]+", roman) if t]


def _vocab_score(text: str, vocab: set[str], threshold: float = 0.86) -> float:
    """Strength of the best token match against a vocabulary, 0.0 if none."""
    best = 0.0
    for token in _tokens(text):
        if token in vocab:
            return 1.0
        if len(token) <= 2:
            continue
        for word in vocab:
            score = similarity(token, word)
            if score >= threshold:
                best = max(best, score)
    return best


def _matches_any(text: str, vocab: set[str], threshold: float = 0.86) -> bool:
    return _vocab_score(text, vocab, threshold) > 0.0


def extract_yes_no(text: str) -> Optional[bool]:
    """True / False, or None when the answer is neither."""
    if not text or not text.strip():
        return None
    # Check negatives first: "nahi chahiye" contains a positive token too.
    if _matches_any(text, _NO):
        return False
    if _matches_any(text, _YES):
        return True
    return None


def extract_intent(text: str) -> Optional[str]:
    """'crop', 'disease', 'exit', or None."""
    if not text or not text.strip():
        return None
    disease = _vocab_score(text, _INTENT_DISEASE)
    crop = _vocab_score(text, _INTENT_CROP)

    # A sentence can touch both vocabularies ("which crop, and is my leaf sick").
    # Take the stronger reading only when it is clearly ahead; a genuine tie
    # returns None so the dialogue asks rather than picks a side.
    if disease or crop:
        if abs(disease - crop) < 0.05:
            return None
        return "disease" if disease > crop else "crop"

    if _matches_any(text, _INTENT_EXIT):
        return "exit"
    return None


def extract_season(text: str) -> Optional[str]:
    """
    Pick the best-scoring season rather than the first one over a fixed bar.

    The threshold is lower than elsewhere because there are only three options
    and they sound nothing alike, so a loose match is still unambiguous — and
    a clear-winner margin keeps a genuine toss-up returning None.
    """
    if not text or not text.strip():
        return None

    scores = {season: _vocab_score(text, vocab, threshold=0.78)
              for season, vocab in _SEASONS.items()}
    best = max(scores, key=lambda s: scores[s])
    if scores[best] == 0.0:
        return None

    runner_up = max((v for k, v in scores.items() if k != best), default=0.0)
    return best if scores[best] - runner_up >= 0.05 else None


def extract_name(text: str, max_words: int = 3) -> Optional[str]:
    """
    Pull a name out of a spoken answer by removing carrier words. The farmer's
    own words are echoed back verbatim — this is the only slot whose value is
    not drawn from a closed vocabulary, and it is never used for a lookup.
    """
    if not text or not text.strip():
        return None

    raw_words = [w for w in re.split(r"\s+", text.strip()) if w]
    kept: list[str] = []
    for word in raw_words:
        cleaned = re.sub(r"[^\wऀ-ॿ]+", "", word)
        if not cleaned:
            continue
        if _fold(cleaned) in _NAME_NOISE_FOLDED:
            continue
        kept.append(cleaned)

    if not kept:
        return None
    name = " ".join(kept[:max_words])
    return name if len(name) >= 2 else None


def extract_number(text: str) -> Optional[float]:
    """First number in the text, in Latin or Devanagari digits."""
    if not text:
        return None
    normalized = "".join(_DEVANAGARI_DIGITS.get(c, c) for c in text)
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    return float(match.group()) if match else None


# ── Place resolution ─────────────────────────────────────────────────────

def resolve_district(spoken: str, districts: list[str]):
    return best_match(spoken, districts, threshold=0.78)


def resolve_block(spoken: str, blocks: list[str]):
    return best_match(spoken, blocks, threshold=0.78)


def resolve_village(spoken: str, villages: list[dict[str, Any]]):
    """
    Villages carry a code, so match on name then map back. The threshold is
    higher than for districts because a block can hold hundreds of similar
    names and a wrong pick silently swaps in another village's soil test.
    """
    names = [v["village_name"] for v in villages]
    match, suggestions = best_match(spoken, names, threshold=0.85)
    if match is None:
        return None, suggestions
    for village in villages:
        if village["village_name"] == match:
            return village, []
    return None, suggestions
