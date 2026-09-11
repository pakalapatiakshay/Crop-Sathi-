"""
Every sentence the voice agent is capable of speaking.

The agent has no generative model in its response path: `render()` looks up a
fixed template by key and substitutes slots that came from validated user input
or from a model's own output. A crop, a district or a confidence figure that is
not in the data cannot appear in speech, because there is no code path that
produces a sentence any other way.

Adding a language means adding a key to each entry here plus the vocabulary in
slots.py. It does not require touching dialogue.py.
"""

import re
from typing import Any

LANGUAGES = ("hi", "en")
DEFAULT_LANGUAGE = "hi"

LANGUAGE_NAMES = {
    "hi": "हिंदी",
    "en": "English",
}

# Vosk/Piper model tags per language, resolved by speech providers.
LANGUAGE_LOCALES = {
    "hi": "hi-IN",
    "en": "en-IN",
}


PHRASES: dict[str, dict[str, str]] = {
    # ── Opening ──────────────────────────────────────────────────────────
    "welcome": {
        "hi": "नमस्ते! मैं क्रॉप साथी हूँ। मैं आपको फसल चुनने में मदद करूँगा। "
              "क्या आप हिंदी में बात करना चाहते हैं?",
        "en": "Hello! I am Crop Sathi. I will help you choose a crop. "
              "Shall we continue in English?",
    },
    "language_set": {
        "hi": "ठीक है, हम हिंदी में बात करेंगे।",
        "en": "Alright, we will continue in English.",
    },
    "ask_name": {
        "hi": "आपका नाम क्या है?",
        "en": "What is your name?",
    },
    "ask_name_retry": {
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। कृपया सिर्फ़ अपना नाम बोलिए।",
        "en": "Sorry, I did not catch that. Please say just your name.",
    },
    "greet_name": {
        "hi": "नमस्ते {name} जी।",
        "en": "Hello {name}.",
    },

    # ── Location ─────────────────────────────────────────────────────────
    "ask_district": {
        "hi": "आपका खेत किस ज़िले में है?",
        "en": "Which district is your farm in?",
    },
    "ask_district_retry": {
        "hi": "मुझे वह ज़िला नहीं मिला। कृपया झारखंड के ज़िले का नाम दोबारा बोलिए, "
              "जैसे रांची, गुमला, या हज़ारीबाग़।",
        "en": "I could not find that district. Please say a Jharkhand district again, "
              "for example Ranchi, Gumla, or Hazaribagh.",
    },
    "district_options": {
        "hi": "क्या आपका मतलब इनमें से किसी एक से है? {options}",
        "en": "Did you mean one of these? {options}",
    },
    "ask_block": {
        "hi": "{district} ज़िले में आपका प्रखंड कौन सा है?",
        "en": "Which block in {district} district?",
    },
    "ask_block_retry": {
        "hi": "वह प्रखंड मुझे नहीं मिला। कृपया दोबारा बोलिए।",
        "en": "I could not find that block. Please say it again.",
    },
    "ask_village": {
        "hi": "आपका गाँव कौन सा है?",
        "en": "Which village?",
    },
    "ask_village_retry": {
        "hi": "वह गाँव मुझे नहीं मिला। कृपया दोबारा बोलिए।",
        "en": "I could not find that village. Please say it again.",
    },
    "soil_found": {
        "hi": "{village} की मिट्टी की जाँच मिल गई। नाइट्रोजन {n}, फॉस्फोरस {p}, "
              "पोटैशियम {k}, और पी एच {ph}।",
        "en": "I found the soil test for {village}. Nitrogen {n}, phosphorus {p}, "
              "potassium {k}, and pH {ph}.",
    },

    # ── Season ───────────────────────────────────────────────────────────
    "ask_season": {
        "hi": "आप किस मौसम में बुवाई करना चाहते हैं — खरीफ, रबी, या ज़ायद?",
        "en": "Which season do you want to sow in — kharif, rabi, or zaid?",
    },
    "ask_season_retry": {
        "hi": "कृपया खरीफ, रबी, या ज़ायद में से एक बोलिए।",
        "en": "Please say one of kharif, rabi, or zaid.",
    },

    # ── Intent ───────────────────────────────────────────────────────────
    "ask_intent": {
        "hi": "मैं आपकी क्या मदद कर सकता हूँ? फसल की सलाह चाहिए, "
              "या पत्ती की बीमारी की जाँच?",
        "en": "How can I help you? Do you want a crop recommendation, "
              "or a leaf disease check?",
    },
    "ask_intent_retry": {
        "hi": "कृपया बोलिए — फसल की सलाह, या बीमारी की जाँच?",
        "en": "Please say — crop recommendation, or disease check?",
    },

    # ── Crop result ──────────────────────────────────────────────────────
    "crop_thinking": {
        "hi": "एक पल रुकिए, मैं आपकी मिट्टी के हिसाब से फसल चुन रहा हूँ।",
        "en": "One moment, I am matching a crop to your soil.",
    },
    "crop_result_high": {
        "hi": "आपकी मिट्टी के लिए सबसे अच्छी फसल है {crop}। "
              "मॉडल को इस पर {confidence} प्रतिशत भरोसा है।",
        "en": "The best crop for your soil is {crop}. "
              "The model is {confidence} percent confident.",
    },
    "crop_result_low": {
        "hi": "मैं पूरी तरह निश्चित नहीं हूँ। सबसे संभावित फसल {crop} है, "
              "पर भरोसा सिर्फ़ {confidence} प्रतिशत है। "
              "कृपया कृषि अधिकारी से भी सलाह लीजिए।",
        "en": "I am not fully certain. The most likely crop is {crop}, "
              "but confidence is only {confidence} percent. "
              "Please also consult your agriculture officer.",
    },
    "crop_alternatives": {
        "hi": "दूसरे विकल्प हैं {second} और {third}।",
        "en": "Other options are {second} and {third}.",
    },
    "crop_failed": {
        "hi": "माफ़ कीजिए, अभी फसल की सलाह नहीं निकल पाई। कृपया बाद में कोशिश कीजिए।",
        "en": "Sorry, I could not produce a recommendation right now. Please try again later.",
    },

    # ── Disease ──────────────────────────────────────────────────────────
    "ask_photo": {
        "hi": "कृपया बीमार पत्ती की एक साफ़ फ़ोटो खींचिए। "
              "पत्ती को अच्छी रोशनी में, कैमरे के पास रखिए।",
        "en": "Please take a clear photo of the affected leaf. "
              "Hold the leaf close to the camera in good light.",
    },
    "disease_thinking": {
        "hi": "फ़ोटो मिल गई। मैं जाँच कर रहा हूँ।",
        "en": "I have the photo. I am checking it now.",
    },
    "disease_healthy": {
        "hi": "अच्छी ख़बर। यह {plant} की पत्ती स्वस्थ दिख रही है। "
              "कोई बीमारी नहीं मिली।",
        "en": "Good news. This {plant} leaf looks healthy. "
              "No disease was found.",
    },
    "disease_found": {
        "hi": "इस {plant} की पत्ती में {disease} के लक्षण दिख रहे हैं। "
              "भरोसा {confidence} प्रतिशत है।",
        "en": "This {plant} leaf shows signs of {disease}. "
              "Confidence is {confidence} percent.",
    },
    # Spoken whenever the diagnosis is not trustworthy enough to act on.
    "disease_uncertain": {
        "hi": "मैं इस फ़ोटो से बीमारी ठीक से नहीं पहचान पाया। "
              "कृपया बेहतर रोशनी में दोबारा फ़ोटो लीजिए, "
              "या नज़दीकी कृषि केंद्र से सलाह लीजिए। "
              "मैं ग़लत जानकारी देकर आपकी फसल का नुक़सान नहीं करना चाहता।",
        "en": "I could not identify the disease reliably from this photo. "
              "Please retake it in better light, "
              "or consult your nearest agriculture centre. "
              "I do not want to risk your crop by guessing.",
    },
    "disease_advice_prefix": {
        "hi": "सुझाव: {advice}",
        "en": "Advice: {advice}",
    },
    "disease_failed": {
        "hi": "माफ़ कीजिए, फ़ोटो की जाँच नहीं हो पाई। कृपया दोबारा कोशिश कीजिए।",
        "en": "Sorry, I could not analyse the photo. Please try again.",
    },

    # ── Follow-up ────────────────────────────────────────────────────────
    "offer_disease": {
        "hi": "क्या आप किसी पत्ती की बीमारी भी जाँचना चाहते हैं?",
        "en": "Would you also like to check a leaf for disease?",
    },
    "offer_anything_else": {
        "hi": "क्या मैं आपकी और कोई मदद कर सकता हूँ?",
        "en": "Can I help you with anything else?",
    },
    "goodbye": {
        "hi": "धन्यवाद {name} जी। आपकी फसल अच्छी हो। नमस्ते।",
        "en": "Thank you {name}. I wish you a good harvest. Goodbye.",
    },

    # ── Generic fallbacks ────────────────────────────────────────────────
    "not_understood": {
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया।",
        "en": "Sorry, I did not understand.",
    },
    "yes_no_retry": {
        "hi": "कृपया हाँ या नहीं बोलिए।",
        "en": "Please say yes or no.",
    },
    "give_up": {
        "hi": "कोई बात नहीं। आप स्क्रीन पर टच करके भी जानकारी भर सकते हैं।",
        "en": "No problem. You can also fill this in by touching the screen.",
    },
    "no_soil_data": {
        "hi": "इस गाँव की मिट्टी की जाँच उपलब्ध नहीं है। "
              "मैं ज़िले के औसत से काम चला रहा हूँ।",
        "en": "No soil test is available for this village. "
              "I am using the district average instead.",
    },
    "offline_notice": {
        "hi": "मैं बिना इंटरनेट के भी काम कर रहा हूँ।",
        "en": "I am working without internet.",
    },
}


# ── Crop names ───────────────────────────────────────────────────────────
# Keys are exactly the 22 labels in ml_models/crop-recommendation/label_mapping.json.
# A prediction whose label is missing here is spoken in English rather than
# guessed at, so a retrained model with new classes degrades safely.
CROP_NAMES: dict[str, dict[str, str]] = {
    "apple":        {"hi": "सेब",          "en": "apple"},
    "banana":       {"hi": "केला",          "en": "banana"},
    "blackgram":    {"hi": "उड़द",          "en": "black gram"},
    "chickpea":     {"hi": "चना",           "en": "chickpea"},
    "coconut":      {"hi": "नारियल",        "en": "coconut"},
    "coffee":       {"hi": "कॉफ़ी",          "en": "coffee"},
    "cotton":       {"hi": "कपास",          "en": "cotton"},
    "grapes":       {"hi": "अंगूर",         "en": "grapes"},
    "jute":         {"hi": "जूट",           "en": "jute"},
    "kidneybeans":  {"hi": "राजमा",         "en": "kidney beans"},
    "lentil":       {"hi": "मसूर",          "en": "lentil"},
    "maize":        {"hi": "मक्का",         "en": "maize"},
    "mango":        {"hi": "आम",            "en": "mango"},
    "mothbeans":    {"hi": "मोठ",           "en": "moth beans"},
    "mungbean":     {"hi": "मूंग",          "en": "mung bean"},
    "muskmelon":    {"hi": "खरबूजा",        "en": "muskmelon"},
    "orange":       {"hi": "संतरा",         "en": "orange"},
    "papaya":       {"hi": "पपीता",         "en": "papaya"},
    "pigeonpeas":   {"hi": "अरहर",          "en": "pigeon peas"},
    "pomegranate":  {"hi": "अनार",          "en": "pomegranate"},
    "rice":         {"hi": "धान",           "en": "rice"},
    "watermelon":   {"hi": "तरबूज़",         "en": "watermelon"},
}


# ── Disease vocabulary ───────────────────────────────────────────────────
# Split halves of the PlantVillage "Plant___Disease" labels, translated
# separately so a new label combination still speaks correctly.
PLANT_NAMES: dict[str, dict[str, str]] = {
    "Apple":       {"hi": "सेब",      "en": "apple"},
    "Blueberry":   {"hi": "ब्लूबेरी",  "en": "blueberry"},
    "Cherry":      {"hi": "चेरी",     "en": "cherry"},
    "Corn":        {"hi": "मक्का",    "en": "corn"},
    "Grape":       {"hi": "अंगूर",    "en": "grape"},
    "Orange":      {"hi": "संतरा",    "en": "orange"},
    "Peach":       {"hi": "आड़ू",      "en": "peach"},
    "Pepper":      {"hi": "शिमला मिर्च", "en": "bell pepper"},
    "Potato":      {"hi": "आलू",      "en": "potato"},
    "Raspberry":   {"hi": "रसभरी",    "en": "raspberry"},
    "Soybean":     {"hi": "सोयाबीन",  "en": "soybean"},
    "Squash":      {"hi": "कद्दू",     "en": "squash"},
    "Strawberry":  {"hi": "स्ट्रॉबेरी", "en": "strawberry"},
    "Tomato":      {"hi": "टमाटर",    "en": "tomato"},
}

DISEASE_NAMES: dict[str, dict[str, str]] = {
    "Apple Scab":              {"hi": "एप्पल स्कैब",           "en": "apple scab"},
    "Black Rot":               {"hi": "ब्लैक रॉट",             "en": "black rot"},
    "Cedar Apple Rust":        {"hi": "सीडर एप्पल रस्ट",        "en": "cedar apple rust"},
    "Powdery Mildew":          {"hi": "चूर्णिल आसिता",          "en": "powdery mildew"},
    "Common Rust":             {"hi": "सामान्य रतुआ",           "en": "common rust"},
    "Northern Leaf Blight":    {"hi": "उत्तरी पत्ती झुलसा",      "en": "northern leaf blight"},
    "Bacterial Spot":          {"hi": "जीवाणु धब्बा",           "en": "bacterial spot"},
    "Early Blight":            {"hi": "अगेती झुलसा",            "en": "early blight"},
    "Late Blight":             {"hi": "पिछेती झुलसा",           "en": "late blight"},
    "Leaf Mold":               {"hi": "पत्ती फफूंदी",           "en": "leaf mold"},
    "Septoria Leaf Spot":      {"hi": "सेप्टोरिया पत्ती धब्बा",  "en": "septoria leaf spot"},
    "Target Spot":             {"hi": "टारगेट स्पॉट",           "en": "target spot"},
    "Leaf Scorch":             {"hi": "पत्ती झुलसन",            "en": "leaf scorch"},
    "Esca":                    {"hi": "एस्का",                 "en": "esca"},
    "Haunglongbing":           {"hi": "सिट्रस ग्रीनिंग",        "en": "citrus greening"},
}


# ── Listening vocabularies ───────────────────────────────────────────────
# Handed to the speech recogniser as a grammar for turns whose answers come
# from a closed set, which stops a small model inventing a word that sounds
# vaguely similar. Place names are supplied separately from the soil dataset.
LISTEN_VOCAB: dict[str, dict[str, list[str]]] = {
    "yes_no": {
        "hi": ["हाँ", "हां", "जी", "जी हाँ", "बिल्कुल", "ठीक है", "नहीं", "ना", "नहीं जी"],
        "en": ["yes", "yeah", "yep", "sure", "okay", "correct", "no", "nope", "not"],
    },
    "season": {
        "hi": ["खरीफ", "रबी", "ज़ायद", "जायद", "बरसात", "सर्दी", "गर्मी", "मानसून"],
        "en": ["kharif", "rabi", "zaid", "monsoon", "winter", "summer"],
    },
    "intent": {
        "hi": ["फसल", "फसल की सलाह", "सलाह", "बीमारी", "बीमारी की जाँच", "पत्ती",
               "रोग", "जाँच", "बस", "धन्यवाद", "कुछ नहीं"],
        "en": ["crop", "crop recommendation", "recommendation", "disease",
               "disease check", "leaf", "check", "nothing", "thanks", "done"],
    },
}


def listen_vocabulary(kind: str, lang: str) -> list[str]:
    entry = LISTEN_VOCAB.get(kind, {})
    return entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or []


def render(key: str, lang: str, **slots: Any) -> str:
    """
    Look up a template and fill it. Raises on an unknown key rather than
    returning improvised text, so a missing phrase fails loudly in tests
    instead of silently reaching a farmer.
    """
    entry = PHRASES.get(key)
    if entry is None:
        raise KeyError(f"No phrase registered for key '{key}'")
    template = entry.get(lang) or entry[DEFAULT_LANGUAGE]
    return template.format(**slots)


def crop_name(label: str, lang: str) -> str:
    """Speak a model crop label. Unknown labels fall back to the raw label."""
    entry = CROP_NAMES.get(label.strip().lower())
    if entry is None:
        return label.replace("_", " ")
    return entry.get(lang, entry["en"])


def plant_name(raw: str, lang: str) -> str:
    key = raw.split("(")[0].strip().rstrip(",").strip()
    entry = PLANT_NAMES.get(key)
    if entry is None:
        return raw.replace("_", " ")
    return entry.get(lang, entry["en"])


def disease_name(raw: str, lang: str) -> str:
    key = raw.split("(")[0].strip()
    entry = DISEASE_NAMES.get(key)
    if entry is None:
        return raw.replace("_", " ")
    return entry.get(lang, entry["en"])


# Hand-checked Devanagari for the 24 districts. Transliteration cannot recover
# vowel length from Latin ("Ranchi" gives रंचि, not रांची), and these are the
# names farmers hear most often, so they are spelled out rather than derived.
# Blocks and villages fall back to transliteration — there are 12,014 of them.
DISTRICT_NAMES_HI = {
    "Bokaro": "बोकारो",
    "Chatra": "चतरा",
    "Deoghar": "देवघर",
    "Dhanbad": "धनबाद",
    "Dumka": "दुमका",
    "East Singhbum": "पूर्वी सिंहभूम",
    "Garhwa": "गढ़वा",
    "Giridih": "गिरिडीह",
    "Godda": "गोड्डा",
    "Gumla": "गुमला",
    "Hazaribagh": "हज़ारीबाग़",
    "Jamtara": "जामताड़ा",
    "Khunti": "खूंटी",
    "Koderma": "कोडरमा",
    "Latehar": "लातेहार",
    "Lohardaga": "लोहरदगा",
    "Pakur": "पाकुड़",
    "Palamu": "पलामू",
    "Ramgarh": "रामगढ़",
    "Ranchi": "रांची",
    "Sahebganj": "साहिबगंज",
    "Saraikela Kharsawan": "सरायकेला खरसावां",
    "Simdega": "सिमडेगा",
    "West Singhbhum": "पश्चिमी सिंहभूम",
}


def speakable_place(name: str, lang: str) -> str:
    """
    Prepare a place name from the soil dataset for speech.

    Every one of the 12,014 names is stored in Latin, so a Hindi voice needs
    them transliterated or it mispronounces them. "(Ct)" is a census
    Census-Town marker rather than part of the name and is dropped; other
    parentheticals are genuine alternate names and are kept.
    """
    from voice import slots  # imported here to keep the phrasebook dependency-free

    cleaned = re.sub(r"\s*\(\s*ct\.?\s*\)", "", name, flags=re.IGNORECASE).strip()
    if lang != "hi":
        return cleaned
    return DISTRICT_NAMES_HI.get(cleaned) or slots.to_devanagari(cleaned)


def join_options(items: list[str], lang: str) -> str:
    """Join a short list for speech, e.g. 'A, B या C'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conjunction = "या" if lang == "hi" else "or"
    return f"{', '.join(items[:-1])} {conjunction} {items[-1]}"
