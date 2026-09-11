/* ================================================================
   cropData.js — Real crop reference data for the recommendation UI.

   CROP_IDEAL_RANGES was computed directly from the model's own
   training data (backend/scripts/data/crop_recommendation_jharkhand.csv):
   for every crop, the [min, max, mean] the model actually saw for
   N, P, K, temperature, humidity, ph and rainfall. This is what
   drives the "why this crop" explanations — they compare the
   farmer's real input against the real distribution the model
   learned from, per predicted crop, so the explanation always
   matches whatever the model returns (not a fixed set of 4 crops).

   CROP_PROFILES holds general agronomic reference facts (typical
   duration, water need, sowing/harvest window, etc.) for all 22
   crops the model can output. These are independent of any single
   prediction — display-only context, not model output.
   ================================================================ */

const CROP_IDEAL_RANGES = {
  apple:       { N: [0, 40, 20.8],    P: [120, 145, 134.2], K: [195, 205, 199.9], temperature: [21, 24, 22.6],   humidity: [90, 94.9, 92.3], ph: [5.51, 6.5, 5.93],  rainfall: [100.1, 125, 112.7] },
  banana:      { N: [80, 120, 100.2], P: [70, 95, 82],      K: [45, 55, 50],      temperature: [25, 29.9, 27.4], humidity: [75, 85, 80.4],   ph: [5.51, 6.49, 5.98], rainfall: [90.1, 119.8, 104.6] },
  blackgram:   { N: [19, 64, 39.8],   P: [50, 88, 66.8],    K: [10, 28, 19.4],    temperature: [24.1, 36.7, 29.9], humidity: [55.8, 76.9, 65.7], ph: [4.5, 7.78, 6.19], rainfall: [30.9, 86.2, 62.4] },
  chickpea:    { N: [18, 66, 39.1],   P: [46, 96, 68.2],    K: [61, 102, 79.5],   temperature: [15.6, 21.9, 18.9], humidity: [13.1, 21.5, 16.8], ph: [4.5, 8.87, 6.23], rainfall: [36, 101.7, 72.2] },
  coconut:     { N: [0, 40, 22],      P: [5, 30, 16.9],     K: [25, 35, 30.6],    temperature: [25, 29.9, 27.4], humidity: [90, 100, 94.8],  ph: [5.5, 6.47, 5.98],  rainfall: [131.1, 225.6, 175.7] },
  coffee:      { N: [80, 120, 101.2], P: [15, 40, 28.7],    K: [25, 35, 29.9],    temperature: [23.1, 27.9, 25.5], humidity: [50, 69.9, 58.9], ph: [6.02, 7.49, 6.79], rainfall: [115.2, 199.5, 158.1] },
  cotton:      { N: [100, 140, 117.8],P: [35, 60, 46.2],    K: [15, 25, 19.6],    temperature: [22, 26, 24],     humidity: [75, 84.9, 79.8], ph: [5.8, 7.99, 6.91],  rainfall: [60.7, 99.9, 80.4] },
  grapes:      { N: [0, 40, 23.2],    P: [120, 145, 132.5], K: [195, 205, 200.1], temperature: [8.8, 41.9, 23.8], humidity: [80, 84, 81.9],  ph: [5.51, 6.5, 6.03],  rainfall: [65, 74.9, 69.6] },
  jute:        { N: [49, 109, 77.4],  P: [31, 67, 46.9],    K: [31, 52, 40.3],    temperature: [21.4, 29.2, 25], humidity: [65.2, 98.1, 79.3], ph: [4.5, 7.49, 5.99], rainfall: [76.9, 225.2, 157.6] },
  kidneybeans: { N: [0, 43, 20.6],    P: [46, 95, 67.8],    K: [13, 30, 20.1],    temperature: [14.5, 28.7, 19.9], humidity: [16.8, 26.9, 21.6], ph: [4.5, 6.5, 5.6], rainfall: [32.5, 164.8, 96.5] },
  lentil:      { N: [0, 44, 19.1],    P: [52, 90, 68.9],    K: [13, 28, 19.5],    temperature: [17.2, 32.8, 24.2], humidity: [55.3, 73, 64.7], ph: [4.5, 7.84, 6.11], rainfall: [20.7, 61.5, 41.8] },
  maize:       { N: [51, 110, 77.5],  P: [29, 67, 48.6],    K: [12, 28, 19.7],    temperature: [16, 29.1, 22.6], humidity: [49.9, 81.9, 65.4], ph: [4.5, 7, 5.79],   rainfall: [39, 118.7, 77.6] },
  mango:       { N: [0, 40, 20.1],    P: [15, 40, 27.2],    K: [25, 35, 29.9],    temperature: [27, 36, 31.2],   humidity: [45, 55, 50.2],   ph: [4.51, 6.97, 5.77], rainfall: [89.3, 100.8, 94.7] },
  mothbeans:   { N: [0, 45, 21.8],    P: [33, 72, 49.2],    K: [13, 30, 20.4],    temperature: [22.7, 33.8, 28.4], humidity: [37.2, 66.7, 53.2], ph: [3.5, 9.94, 6.09], rainfall: [20, 81.8, 46.9] },
  mungbean:    { N: [0, 47, 21.9],    P: [29, 68, 46.9],    K: [12, 27, 19.5],    temperature: [24.1, 32, 28.4], humidity: [74.1, 96.3, 85.2], ph: [4.5, 7.2, 6.05], rainfall: [20, 66.7, 43.7] },
  muskmelon:   { N: [80, 120, 100.3], P: [5, 30, 17.7],     K: [45, 55, 50.1],    temperature: [27, 29.9, 28.7], humidity: [90, 95, 92.3],   ph: [6, 6.78, 6.36],   rainfall: [20.2, 29.9, 24.7] },
  orange:      { N: [0, 40, 19.6],    P: [5, 30, 16.6],     K: [5, 15, 10],       temperature: [10, 34.9, 22.8], humidity: [90, 95, 92.2],   ph: [6.01, 8, 7.02],   rainfall: [100.2, 119.7, 110.5] },
  papaya:      { N: [31, 70, 49.9],   P: [46, 70, 59],      K: [45, 55, 50],      temperature: [23, 43.7, 33.7], humidity: [90, 94.9, 92.4], ph: [6.5, 6.99, 6.74], rainfall: [40.4, 248.9, 142.6] },
  pigeonpeas:  { N: [0, 45, 21.1],    P: [48, 92, 67.9],    K: [14, 29, 20.3],    temperature: [17.7, 38, 28],   humidity: [29.3, 71.6, 48], ph: [4.5, 7.45, 5.56], rainfall: [54.9, 226.7, 138.2] },
  pomegranate: { N: [0, 40, 18.9],    P: [5, 30, 18.8],     K: [35, 45, 40.2],    temperature: [18.1, 25, 21.8], humidity: [85.1, 95, 90.1], ph: [5.56, 7.2, 6.43], rainfall: [102.5, 112.5, 107.5] },
  rice:        { N: [52, 111, 80.6],  P: [28, 68, 48],      K: [29, 54, 39.8],    temperature: [19.1, 29.1, 23.6], humidity: [71.5, 92.5, 82.2], ph: [4.5, 7.87, 5.85], rainfall: [110.4, 300, 213] },
  watermelon:  { N: [80, 120, 99.4],  P: [5, 30, 17],       K: [45, 55, 50.2],    temperature: [24, 27, 25.6],   humidity: [80, 90, 85.2],   ph: [6, 6.96, 6.5],    rainfall: [40.1, 59.8, 50.8] },
};

const CROP_PROFILES = {
  rice:        { name: "Rice (Paddy)",  scientific: "Oryza sativa",       emoji: "🌾", duration: "120–140 days", water: "High",   profit: "High",   investment: "Medium", difficulty: "Moderate", sowing: "June – July",      harvest: "October – November" },
  maize:       { name: "Maize",         scientific: "Zea mays",           emoji: "🌽", duration: "90–110 days",  water: "Medium", profit: "High",   investment: "Low",    difficulty: "Easy",     sowing: "June – July",      harvest: "September – October" },
  chickpea:    { name: "Chickpea (Gram)",scientific: "Cicer arietinum",   emoji: "🫘", duration: "90–120 days",  water: "Low",    profit: "Medium",  investment: "Low",    difficulty: "Easy",     sowing: "October – November", harvest: "February – March" },
  kidneybeans: { name: "Kidney Beans (Rajma)", scientific: "Phaseolus vulgaris", emoji: "🫘", duration: "90–120 days", water: "Medium", profit: "Medium", investment: "Low", difficulty: "Easy", sowing: "October – November", harvest: "February – March" },
  pigeonpeas:  { name: "Pigeon Peas (Arhar/Tur)", scientific: "Cajanus cajan", emoji: "🌱", duration: "150–180 days", water: "Low", profit: "Medium", investment: "Low", difficulty: "Easy", sowing: "June – July", harvest: "December – January" },
  mothbeans:   { name: "Moth Beans",    scientific: "Vigna aconitifolia", emoji: "🌱", duration: "75–90 days",   water: "Low",    profit: "Low",     investment: "Low",    difficulty: "Easy",     sowing: "June – July",      harvest: "September" },
  mungbean:    { name: "Mung Bean (Green Gram)", scientific: "Vigna radiata", emoji: "🌱", duration: "60–75 days", water: "Low",  profit: "Medium",  investment: "Low",    difficulty: "Easy",     sowing: "March or June",    harvest: "May or September" },
  blackgram:   { name: "Black Gram (Urad)", scientific: "Vigna mungo",    emoji: "🌱", duration: "80–100 days",  water: "Low",    profit: "Medium",  investment: "Low",    difficulty: "Easy",     sowing: "June – July",      harvest: "September – October" },
  lentil:      { name: "Lentil (Masoor)", scientific: "Lens culinaris",   emoji: "🌱", duration: "100–120 days", water: "Low",    profit: "Medium",  investment: "Low",    difficulty: "Easy",     sowing: "October – November", harvest: "February – March" },
  pomegranate: { name: "Pomegranate",   scientific: "Punica granatum",    emoji: "🍎", duration: "5–7 months (fruiting)", water: "Medium", profit: "High", investment: "High", difficulty: "Moderate", sowing: "Year-round (saplings)", harvest: "Twice a year" },
  banana:      { name: "Banana",        scientific: "Musa spp.",          emoji: "🍌", duration: "10–12 months", water: "High",   profit: "High",   investment: "High",   difficulty: "Moderate", sowing: "Year-round",       harvest: "10–12 months after planting" },
  mango:       { name: "Mango",         scientific: "Mangifera indica",   emoji: "🥭", duration: "Perennial (3–5 yrs to bear)", water: "Medium", profit: "High", investment: "High", difficulty: "Moderate", sowing: "June – August (saplings)", harvest: "March – June" },
  grapes:      { name: "Grapes",        scientific: "Vitis vinifera",     emoji: "🍇", duration: "Perennial (2–3 yrs to bear)", water: "Medium", profit: "High", investment: "High", difficulty: "Hard", sowing: "January – February", harvest: "February – April" },
  watermelon:  { name: "Watermelon",    scientific: "Citrullus lanatus",  emoji: "🍉", duration: "80–100 days",  water: "Medium", profit: "Medium", investment: "Medium", difficulty: "Easy", sowing: "February – March", harvest: "May – June" },
  muskmelon:   { name: "Muskmelon",     scientific: "Cucumis melo",       emoji: "🍈", duration: "80–100 days",  water: "Medium", profit: "Medium", investment: "Medium", difficulty: "Easy", sowing: "February – March", harvest: "May – June" },
  apple:       { name: "Apple",         scientific: "Malus domestica",    emoji: "🍎", duration: "Perennial (4–5 yrs to bear)", water: "Medium", profit: "High", investment: "High", difficulty: "Hard", sowing: "December – February", harvest: "August – October" },
  orange:      { name: "Orange",        scientific: "Citrus sinensis",    emoji: "🍊", duration: "Perennial (3–4 yrs to bear)", water: "Medium", profit: "High", investment: "High", difficulty: "Moderate", sowing: "July – August (saplings)", harvest: "December – February" },
  papaya:      { name: "Papaya",        scientific: "Carica papaya",      emoji: "🥭", duration: "9–11 months",  water: "Medium", profit: "High",   investment: "Medium", difficulty: "Easy", sowing: "February – March or July – August", harvest: "9–11 months after sowing" },
  coconut:     { name: "Coconut",       scientific: "Cocos nucifera",     emoji: "🥥", duration: "Perennial (5–6 yrs to bear)", water: "High", profit: "High", investment: "High", difficulty: "Moderate", sowing: "Year-round (saplings)", harvest: "Year-round once mature" },
  cotton:      { name: "Cotton",        scientific: "Gossypium hirsutum", emoji: "☁️", duration: "160–180 days", water: "Medium", profit: "High",   investment: "High",   difficulty: "Hard",     sowing: "May – June",       harvest: "November – January" },
  jute:        { name: "Jute",          scientific: "Corchorus olitorius",emoji: "🌿", duration: "100–120 days", water: "High",   profit: "Medium",  investment: "Low",    difficulty: "Moderate", sowing: "March – May",      harvest: "July – September" },
  coffee:      { name: "Coffee",        scientific: "Coffea spp.",        emoji: "☕", duration: "Perennial (3–4 yrs to bear)", water: "Medium", profit: "High", investment: "High", difficulty: "Hard", sowing: "June – July (saplings)", harvest: "November – February" },
};

// Generic fallback profile for any crop id the model returns that
// isn't in CROP_PROFILES yet, so the UI never silently breaks.
function getCropProfile(id) {
  const key = (id || "").toLowerCase().trim();
  return CROP_PROFILES[key] || {
    name: key ? key.charAt(0).toUpperCase() + key.slice(1) : "Unknown crop",
    scientific: "", emoji: "🌱", duration: "—", water: "—", profit: "—",
    investment: "—", difficulty: "—", sowing: "—", harvest: "—",
  };
}

/**
 * Build "why this crop" reasons by comparing the farmer's actual
 * input values against the real [min, max, mean] range the model
 * was trained on for the predicted crop. Falls back to a generic
 * note if we have no range data for that crop id.
 */
function buildCropReasons(cropId, inputs) {
  const ranges = CROP_IDEAL_RANGES[(cropId || "").toLowerCase().trim()];
  if (!ranges) return ["This crop matched your soil and weather profile best among the model's candidates."];

  const FIELD_LABELS = {
    N: "Nitrogen (N)", P: "Phosphorus (P)", K: "Potassium (K)",
    ph: "Soil pH", rainfall: "Rainfall", temperature: "Temperature", humidity: "Humidity",
  };
  const FIELD_UNITS = { N: "kg/ha", P: "kg/ha", K: "kg/ha", ph: "", rainfall: "mm", temperature: "°C", humidity: "%" };

  const order = ["N", "P", "K", "ph", "rainfall", "temperature", "humidity"];
  const reasons = [];

  for (const field of order) {
    const val = inputs[field];
    const range = ranges[field];
    if (val === null || val === undefined || Number.isNaN(val) || !range) continue;

    const [min, max] = range;
    const unit = FIELD_UNITS[field];
    const label = FIELD_LABELS[field];
    const shown = Number.isInteger(val) ? val : Math.round(val * 100) / 100;

    if (val >= min && val <= max) {
      reasons.push(`${label} of ${shown}${unit} is within the ${min}–${max}${unit} range this crop performs best in.`);
    } else if (val < min) {
      const diff = Math.round((min - val) * 10) / 10;
      reasons.push(`${label} of ${shown}${unit} is ${diff}${unit} below this crop's typical ${min}–${max}${unit} range — still the best available match.`);
    } else {
      const diff = Math.round((val - max) * 10) / 10;
      reasons.push(`${label} of ${shown}${unit} is ${diff}${unit} above this crop's typical ${min}–${max}${unit} range — still the best available match.`);
    }
  }

  // Keep the strongest (in-range) matches first, cap at 4 for readability.
  reasons.sort((a, b) => (a.includes("within") ? -1 : 0) - (b.includes("within") ? -1 : 0));
  return reasons.slice(0, 4);
}

/**
 * Suitability score (0-100): the share of the farmer's input values
 * that fall inside this crop's real training-data range. This is a
 * second, independent signal from the model's own confidence —
 * both are computed from real numbers, never hardcoded.
 */
function computeSuitability(cropId, inputs) {
  const ranges = CROP_IDEAL_RANGES[(cropId || "").toLowerCase().trim()];
  if (!ranges) return null;

  const fields = ["N", "P", "K", "ph", "rainfall", "temperature", "humidity"];
  let checked = 0, matched = 0;
  for (const f of fields) {
    const val = inputs[f];
    const range = ranges[f];
    if (val === null || val === undefined || Number.isNaN(val) || !range) continue;
    checked++;
    if (val >= range[0] && val <= range[1]) matched++;
  }
  if (checked === 0) return null;
  return Math.round((matched / checked) * 100);
}

/**
 * Turn a raw /predict-crop API response into the display-ready
 * { best, alternatives } shape the Recommend page renders, for
 * whichever crop(s) the model actually returned — not a fixed list.
 */
function buildRecResultForDisplay(apiData, payload) {
  const ids = apiData.top_3 && apiData.top_3.length ? apiData.top_3 : [apiData.prediction];
  const confidences = apiData.top_3_confidence && apiData.top_3_confidence.length
    ? apiData.top_3_confidence
    : ids.map(() => apiData.confidence || 0);

  const list = ids.map((id, i) => {
    const profile = getCropProfile(id);
    const ranges = CROP_IDEAL_RANGES[(id || "").toLowerCase().trim()];
    const confidence = Math.round((confidences[i] ?? 0) * 100);
    const suitability = computeSuitability(id, payload);
    return {
      id,
      name: profile.name,
      scientific: profile.scientific,
      emoji: profile.emoji,
      duration: profile.duration,
      water: profile.water,
      profit: profile.profit,
      investment: profile.investment,
      difficulty: profile.difficulty,
      sowing: profile.sowing,
      harvest: profile.harvest,
      idealPh: ranges ? `${ranges.ph[0]}–${ranges.ph[1]}` : "—",
      confidence,
      suitability: suitability === null ? confidence : suitability,
      reasons: buildCropReasons(id, payload),
    };
  });

  return {
    source: "live",
    best: list[0],
    alternatives: list.slice(1),
  };
}
