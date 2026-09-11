/* ================================================================
   db.js — Mock data layer + IndexedDB offline storage
   Port of Temporary/lovable-project-b2ad097c/src/lib/mock.ts
   ================================================================ */

// ── API Configuration ──
const API_BASE = "http://127.0.0.1:8000";
const ENDPOINTS = {
  predictCrop: `${API_BASE}/predict-crop`,
  analyzeDis: `${API_BASE}/analyze-disease`,
  sync: `${API_BASE}/sync`,
  health: `${API_BASE}/health`,
  // Measured Jharkhand soil (Soil Health Card) used to pre-fill the form.
  soilDistricts: `${API_BASE}/soil/districts`,
  soilBlocks: (d) => `${API_BASE}/soil/districts/${encodeURIComponent(d)}/blocks`,
  soilVillages: (d, b) =>
    `${API_BASE}/soil/districts/${encodeURIComponent(d)}/blocks/${encodeURIComponent(b)}/villages`,
  soilVillage: (code) => `${API_BASE}/soil/village/${encodeURIComponent(code)}`,
};

// ── Fallback crop cards ──
// Used ONLY when the live /predict-crop API is unreachable while online.
// Clearly labeled "sample recommendation" in the UI — never shown as if it
// were a real prediction. Real results come from buildRecResultForDisplay()
// in cropData.js, driven entirely by the API response.
const FALLBACK_CROPS = [
  {
    id: "rice",
    name: "Rice (Paddy)",
    scientific: "Oryza sativa",
    emoji: "🌾",
    confidence: 94,
    suitability: 92,
    duration: "120–140 days",
    idealPh: "4.5–7.87",
    water: "High (1200 mm)",
    profit: "High",
    investment: "Medium",
    difficulty: "Moderate",
    sowing: "June – July",
    harvest: "October – November",
    reasons: [
      "Soil pH 6.4 is within the ideal 5.5–7.0 range",
      "Nitrogen level is optimal for vegetative growth",
      "Forecast rainfall of 180 mm suits water demand",
      "Kharif season conditions match crop calendar",
    ],
    soil: "Clay loam with good water retention",
    temperature: "21–37 °C",
    rainfall: "1000–1500 mm",
    demand: "Very high — stable MSP support",
    diseases: ["Blast", "Bacterial leaf blight", "Sheath rot"],
    prevention: ["Use certified seed", "Balanced nitrogen dosing", "Field drainage during heavy rain"],
  },
  {
    id: "maize",
    name: "Maize",
    scientific: "Zea mays",
    emoji: "🌽",
    confidence: 88,
    suitability: 86,
    duration: "90–110 days",
    idealPh: "4.5–7.0",
    water: "Medium (600 mm)",
    profit: "High",
    investment: "Low",
    difficulty: "Easy",
    sowing: "June – July",
    harvest: "September – October",
    reasons: [
      "Well-drained loam matches maize requirements",
      "Phosphorus level supports strong root growth",
      "Short duration fits your rotation plan",
    ],
    soil: "Well-drained sandy loam",
    temperature: "18–32 °C",
    rainfall: "500–800 mm",
    demand: "High — feed and starch industry",
    diseases: ["Turcicum leaf blight", "Stem borer"],
    prevention: ["Crop rotation", "Timely sowing", "Pheromone traps"],
  },
  {
    id: "groundnut",
    name: "Groundnut",
    scientific: "Arachis hypogaea",
    emoji: "🥜",
    confidence: 81,
    suitability: 79,
    duration: "100–120 days",
    idealPh: "5.5–7.0",
    water: "Low (450 mm)",
    profit: "Medium",
    investment: "Low",
    difficulty: "Easy",
    sowing: "June – July",
    harvest: "October",
    reasons: [
      "Low water requirement suits your irrigation",
      "Improves soil nitrogen naturally",
    ],
    soil: "Sandy loam, well drained",
    temperature: "20–34 °C",
    rainfall: "450–700 mm",
    demand: "Medium — oil mills nearby",
    diseases: ["Tikka leaf spot", "Collar rot"],
    prevention: ["Seed treatment", "Gypsum application at pegging"],
  },
  {
    id: "cotton",
    name: "Cotton",
    scientific: "Gossypium hirsutum",
    emoji: "☁️",
    confidence: 76,
    suitability: 74,
    duration: "160–180 days",
    idealPh: "5.8–7.99",
    water: "Medium (700 mm)",
    profit: "High",
    investment: "High",
    difficulty: "Hard",
    sowing: "May – June",
    harvest: "November – January",
    reasons: [
      "Black soil retains moisture well",
      "Strong market price trend this season",
    ],
    soil: "Black cotton soil",
    temperature: "21–35 °C",
    rainfall: "600–900 mm",
    demand: "High — export driven",
    diseases: ["Pink bollworm", "Wilt"],
    prevention: ["Bt refuge planting", "Regular scouting"],
  },
];

// ── 7-day Forecast ──
const forecast = [
  { day: "Mon", temp: 31, min: 23, rain: 10, icon: "sun" },
  { day: "Tue", temp: 29, min: 22, rain: 60, icon: "rain" },
  { day: "Wed", temp: 28, min: 22, rain: 80, icon: "rain" },
  { day: "Thu", temp: 30, min: 23, rain: 20, icon: "cloud" },
  { day: "Fri", temp: 32, min: 24, rain: 5, icon: "sun" },
  { day: "Sat", temp: 33, min: 25, rain: 0, icon: "sun" },
  { day: "Sun", temp: 31, min: 24, rain: 30, icon: "cloud" },
];

// ── Market Prices ──
let marketPrices = [];

async function fetchMarketPrices() {
  try {
    const res = await fetch(`${API_BASE}/market/prices`);
    if (!res.ok) throw new Error("Failed to fetch market prices");
    const json = await res.json();
    if (json.success && json.data) {
      marketPrices = json.data;
      return true;
    }
  } catch (err) {
    console.error("Market prices fetch error:", err);
    // Use fallback if fetch fails
    marketPrices = [
      { crop: "Rice (Paddy)", market: "Ranchi Mandi", price: 2320, prev: 2280, unit: "₹/quintal" },
      { crop: "Maize", market: "Dhanbad APMC", price: 2145, prev: 2190, unit: "₹/quintal" }
    ];
  }
  return false;
}

// ── Price Trend (5 weeks) ──
const priceTrend = [
  { week: "W1", rice: 2210, maize: 2050, cotton: 7100 },
  { week: "W2", rice: 2245, maize: 2110, cotton: 7220 },
  { week: "W3", rice: 2260, maize: 2160, cotton: 7180 },
  { week: "W4", rice: 2280, maize: 2190, cotton: 7395 },
  { week: "W5", rice: 2320, maize: 2145, cotton: 7480 },
];

// ── Government Schemes ──
let schemes = [];

async function fetchSchemes() {
  try {
    const res = await fetch(`${API_BASE}/schemes`);
    if (!res.ok) throw new Error("Failed to fetch schemes");
    const json = await res.json();
    if (json.success && json.data) {
      schemes = json.data;
      return true;
    }
  } catch (err) {
    console.error("Schemes fetch error:", err);
    // Use fallback if fetch fails
    schemes = [
      {
        name: "PM-KISAN",
        benefit: "₹6,000 per year direct income support in three instalments.",
        eligibility: "All landholding farmer families with cultivable land records.",
        link: "https://pmkisan.gov.in",
      },
      {
        name: "Pradhan Mantri Fasal Bima Yojana",
        benefit: "Crop insurance against drought, flood, pest and yield loss.",
        eligibility: "Farmers growing notified crops in notified areas.",
        link: "https://pmfby.gov.in",
      },
      {
        name: "Jharkhand Rajya Fasal Rahat Yojana",
        benefit: "Financial assistance in case of crop loss due to natural calamities.",
        eligibility: "All landholding and landless farmers in Jharkhand.",
        link: "https://jrfry.jharkhand.gov.in/",
      }
    ];
  }
  return false;
}

// ── Recommendation History ──
const recommendHistory = [
  { date: "12 Jul 2026", crop: "Rice (Paddy)", confidence: 94, weather: "Monsoon", yield: "5.1 t/ha" },
  { date: "03 Mar 2026", crop: "Groundnut", confidence: 86, weather: "Dry", yield: "2.3 t/ha" },
  { date: "18 Nov 2025", crop: "Wheat", confidence: 91, weather: "Cool", yield: "4.4 t/ha" },
  { date: "22 Jun 2025", crop: "Maize", confidence: 83, weather: "Humid", yield: "5.8 t/ha" },
];

// ── Notifications ──
const notifications = [
  { title: "Heavy rain alert", body: "80 mm rainfall expected Wednesday. Avoid irrigation today.", tone: "warn" },
  { title: "Market price up", body: "Paddy up ₹40/quintal at Ranchi Mandi.", tone: "good" },
  { title: "Pest advisory", body: "Stem borer activity reported in your district.", tone: "warn" },
  { title: "Government update", body: "PM-KISAN 19th instalment credited this week.", tone: "good" },
];

// ── Fertilizers ──
const fertilizers = [
  { name: "Farmyard manure", type: "Organic", qty: "8 t/ha", when: "2 weeks before sowing", cost: "₹4,000" },
  { name: "Urea", type: "Chemical", qty: "110 kg/ha", when: "Split: basal + tillering", cost: "₹740" },
  { name: "DAP", type: "Chemical", qty: "60 kg/ha", when: "Basal dose", cost: "₹1,620" },
  { name: "Muriate of potash", type: "Chemical", qty: "40 kg/ha", when: "Basal dose", cost: "₹680" },
  { name: "Vermicompost", type: "Organic", qty: "2 t/ha", when: "At land preparation", cost: "₹6,000" },
];

// ── FAQ ──
const faqs = [
  { q: "Is Crop Sathi free?", a: "Yes. The recommendation engine, weather and mandi prices are free for all farmers." },
  { q: "Do I need a soil test?", a: "It helps accuracy, but you can start with your soil type and we use district averages." },
  { q: "Which languages are supported?", a: "English, Hindi, Tamil, Telugu, Marathi, Kannada, Bengali, Gujarati, Punjabi and Odia." },
  { q: "Does it work offline?", a: "Your last recommendation, weather advisory and schemes stay available without a network." },
];

// ── IndexedDB Offline Storage ──
const CropSathiDB = (() => {
  const DB_NAME = "CropSathiDB";
  const DB_VERSION = 1;

  function open() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("recommendations")) {
          db.createObjectStore("recommendations", { keyPath: "id", autoIncrement: true });
        }
        if (!db.objectStoreNames.contains("formData")) {
          db.createObjectStore("formData", { keyPath: "key" });
        }
        if (!db.objectStoreNames.contains("syncQueue")) {
          db.createObjectStore("syncQueue", { keyPath: "id", autoIncrement: true });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function put(storeName, data) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, "readwrite");
      tx.objectStore(storeName).put(data);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async function getAll(storeName) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, "readonly");
      const req = tx.objectStore(storeName).getAll();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function clear(storeName) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, "readwrite");
      tx.objectStore(storeName).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  return { open, put, getAll, clear };
})();

// ── Offline Queue Helpers ──

/**
 * Queue an action for background sync when offline.
 * @param {string} type - "crop_recommendation" or "disease_detection"
 * @param {object} payload - The request payload
 * @returns {Promise<void>}
 */
async function queueSyncAction(type, payload) {
  const action = {
    type,
    payload,
    client_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    queued_at: new Date().toISOString(),
  };
  await CropSathiDB.put("syncQueue", action);
  requestBackgroundSync();
  return action.client_id;
}

/**
 * Save a recommendation result to IndexedDB for history + dashboard.
 * @param {object} result - The API response
 * @param {object} inputs - The form inputs used
 */
async function saveRecommendation(result, inputs) {
  const record = {
    ...result,
    user_inputs: inputs,
    saved_at: new Date().toISOString(),
  };
  await CropSathiDB.put("recommendations", record);
}

/**
 * Get the last saved recommendation for the dashboard card.
 * @returns {Promise<object|null>}
 */
async function getLastRecommendation() {
  const all = await CropSathiDB.getAll("recommendations");
  if (!all.length) return null;
  return all[all.length - 1];
}

/**
 * Request a background sync from the Service Worker.
 */
function requestBackgroundSync() {
  if ("serviceWorker" in navigator && "SyncManager" in window) {
    navigator.serviceWorker.ready.then((reg) => {
      reg.sync.register("crop-sathi-sync").catch(() => { });
    });
  }
}
