# 🌾 Crop-Sathi

> **An AI-powered, offline-first digital companion for smarter and more profitable farming.**

Crop-Sathi helps farmers make better decisions through **hyper-localized crop recommendations, crop disease diagnosis, and precision farming advisories** — even in environments with limited or no internet connectivity.

## ✨ Features

* 🌱 **Crop Recommendation**
  Recommends suitable crops using soil nutrients such as **N, P, K, pH** and climate-related data.

* 🤖 **AI-Powered Predictions**
  Uses an **XGBoost classifier** for crop recommendation.

* 🎙️ **Offline Voice Agent**
  Voice-based assistant supporting interactions in multiple languages without requiring a constant internet connection.

* 🦠 **Disease Diagnosis**
  Identifies crop diseases from images using localized machine learning models.

* 📍 **Hyper-Localized Advisories**
  Provides farming recommendations tailored to local soil and environmental conditions.

* 📱 **Offline-First Design**
  Designed to remain useful in areas with limited connectivity.

## 🛠️ Tech Stack

| Component           | Technology                |
| ------------------- | ------------------------- |
| Crop Recommendation | XGBoost                   |
| Machine Learning    | Python                    |
| Disease Diagnosis   | Image-based ML            |
| Voice Assistant     | Offline Voice AI          |
| Data                | Soil & Climate Parameters |

## 📸 Screenshots

<img width="1901" height="972" alt="image" src="https://github.com/user-attachments/assets/d9d1f6ed-414b-40d1-a134-2e8d10710f45" />



## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/crop-sathi.git
cd crop-sathi
```

### 2. Initialize the Crop-Sathi Module

The main source code is located inside the `Crop-sathi` directory.

If the directory is empty after cloning, initialize the Git submodule:

```bash
git submodule update --init --recursive
```

### 3. Continue with the Main Project

For detailed setup instructions, backend configuration, model training/retraining, and voice-agent configuration, refer to the project documentation:

**[Crop-Sathi Documentation](Crop-sathi/README.md)**

## 📁 Project Structure

```text
.
├── Crop-sathi/          # Main application
│   └── README.md        # Detailed project documentation
│
└── README.md            # Project overview
```

## 🔮 Future Improvements

* 🌦️ More accurate hyper-local weather integration
* 📈 Improved crop yield prediction
* 🗣️ Support for additional regional languages
* 📱 Dedicated mobile application
* ☁️ Cloud synchronization when connectivity is available
* 🧠 Continuous model improvement with new agricultural data

---

## 🌾 About

**Crop-Sathi** aims to make AI-powered agricultural assistance more **accessible, localized, and practical for farmers**, particularly in regions where reliable internet connectivity is not always available.

⭐ **If you find this project useful, consider giving it a star!**
>>>>>>> 58aef702b72e5cd149aeb0ab6c4be584446a392f
