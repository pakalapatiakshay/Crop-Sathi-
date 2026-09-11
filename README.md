# Crop-sathi
Crop-Sathi is an AI-powered, offline-first digital companion that empowers farmers with hyper-localized crop recommendations, real-time disease diagnosis, and precision farming advisories to maximize their yield and profitability.

## Crop recommendation model

The recommender is an XGBoost classifier over
`N, P, K, temperature, humidity, ph, rainfall` → one of 22 crops. Its Jharkhand
soil characteristics come from the **Soil Health Card "Soil Nutrient Analysis"**
export (data.gov.in): 429,178 rows covering 12,029 villages across 24 districts,
surveyed in 2023-24 and 2024-25.

### Reading the raw export

That file is in **long format** — one row per
`(year × village × nutrient × nutrient level)`, where `value` is the *number of
soil samples* in that level, not a measurement. A single village legitimately
produces ~29 rows that share state/district/village and differ only in
nutrient/level/value. They look like duplicates but are a histogram; dropping
them would destroy the distribution. There are zero exact duplicate rows. The
pipeline pivots them into one row per village instead.

Because the export reports categories (Low/Medium/High) while the model consumes
continuous N/P/K on a different scale, levels are anchored by *distribution*:
Low → 15th percentile of that feature in the model's own training data, Medium →
50th, High → 85th, then averaged per village weighted by sample counts. pH is a
shared physical scale, so Acidic/Neutral/Alkaline map to real agronomic values.

### Retraining

```bash
cd backend
python scripts/build_soil_profiles.py      # raw export -> 12,014 village soil profiles
python scripts/augment_jharkhand_data.py   # village profiles -> training set
python scripts/train_xgboost.py            # train + evaluate on a held-out 20%
```

Step 1 needs `scripts/data/raw/soil_nutrient_analysis_jharkhand.csv` (gitignored;
re-downloadable from data.gov.in). It writes the village lookup the API serves.

The train/test split is stratified by crop and written to
`scripts/data/crop_recommendation_{train,test}.csv`. Current held-out test
accuracy is **0.977** (metrics land in
`ml_models/crop-recommendation/training_metrics.json`).

### Village soil auto-fill

Rather than asking a farmer for lab numbers, the wizard has district → block →
village dropdowns that pull that village's measured soil from the API:

| Endpoint | Purpose |
| --- | --- |
| `GET /soil/coverage` | districts / blocks / villages available |
| `GET /soil/districts` | list districts |
| `GET /soil/districts/{district}/blocks` | blocks in a district |
| `GET /soil/districts/{district}/blocks/{block}/villages` | villages in a block |
| `GET /soil/village/{village_code}` | measured N/P/K/pH for one village |

The values stay editable — a farmer with their own soil test can override them.

## Voice agent

A farmer can hold a spoken conversation with the app in Hindi or English, and
it runs with no internet and no API key. The agent asks their name, resolves
their village against the Soil Health Card data, and answers using the same
crop and disease models the rest of the app uses.

```bash
cd backend
pip install -r requirements.txt
python scripts/download_voice_models.py   # ~254 MB, once
uvicorn main:app --reload
```

Then open the app and go to **Voice Assistant**.

### Why there is no LLM in it

The requirement was that the agent must not hallucinate, so nothing generative
sits in the conversation path. The agent is a state machine:

| Layer | File | Guarantee |
| --- | --- | --- |
| What it says | `voice/phrasebook.py` | Every sentence is a fixed template. An unknown key raises rather than improvising. |
| What it understands | `voice/slots.py` | Answers are matched against closed vocabularies — the 24 real districts, that block's real villages, fixed intent and season words. |
| What it does | `voice/dialogue.py` | Calls `ml_service` directly. Every number spoken comes from a model's own output. |

A crop, a village or a confidence figure that is not in the data has no code
path by which it could be spoken. Ambiguous speech re-asks or offers a menu; it
never guesses. After three failed attempts the agent stops insisting and points
the farmer at the touch UI.

### Speech stack

Providers sit behind one interface in `voice/speech.py`, and the dialogue only
ever sees text, so swapping one is an environment variable:

| | Offline default | Alternatives |
| --- | --- | --- |
| Speech → text | Vosk | `browser` (Web Speech API), `bhashini` |
| Text → speech | Piper | `browser`, `bhashini` |

Bhashini adapters are stubbed, not implemented — the ULCA request shape depends
on the pipeline ID issued with your credentials, and guessing it would produce
code that looks finished and fails on first contact. The PWA falls back to the
browser's own speech APIs automatically when the offline models are absent, so
the page works before the download finishes.

### Recognition is constrained per question

A small offline model mishears isolated proper nouns — open recognition turns
"रांची" into "राजीव". Because the dialogue always knows what it is expecting,
`dialogue.expected_vocabulary()` hands that turn's closed answer set to Vosk as
a grammar, which fixes districts, seasons and yes/no.

It cannot fix everything: Vosk grammars only accept words already in the model's
lexicon, and most of the 12,014 village names are not. Those questions therefore
return an `options` list that the UI shows as tappable answers — the farmer
speaks their district and taps their village.

### Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /voice/status` | Which providers are active and whether their models are present |
| `POST /voice/start` | Open a conversation, get the greeting |
| `POST /voice/listen` | Post recorded audio; the server transcribes and replies |
| `POST /voice/say` | Post text instead of audio (browser speech, taps, testing) |
| `POST /voice/photo` | Submit a leaf photo while the agent is waiting for one |
| `POST /voice/speak` | Synthesise a line to WAV (204 when the client should speak it) |

### How the voice agent guards the disease path

The voice agent will not state a diagnosis below 75% confidence, and says so
plainly instead. That floor is deliberately stricter than the `/analyze-disease`
default, and it refuses on two separate grounds.

**Low confidence.** The serving preprocessing used to disagree with the training
transforms, which makes a model produce confident nonsense — on a photograph of
a field with no leaf in it, it returned "Bell Pepper, Healthy" at 66% while the
API's own `is_confident` flag reported `true`. `services/ml_service.py` now
applies ImageNet normalisation and the per-architecture input size, which fixes
the mismatch; the floor stays because a wrongly sprayed field is worse than a
retaken photo.

**Unusable labels.** `DISEASE_CLASSES` is built from `disease_classes.json`,
which is gitignored and so absent on a fresh clone. When it is missing the list
is empty and predictions come back as `class_19` / `Unknown`. The agent detects
that and declines rather than announcing "Class 19" as a plant — see
`_diagnosis_is_speakable()` in `voice/dialogue.py`. To get real diagnoses,
place `disease_classes.json` in `backend/ml_models/plant-disease/` alongside the
`.onnx` files.

The crop path is unaffected by any of this.
