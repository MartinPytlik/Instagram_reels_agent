"""
Konfigurace Instagram Reels Bota.

Proměnné prostředí (environment variables):
  PREDICTOR_URL        URL prediktoru (výchozí: http://localhost:8000/api/predict_actions)
  PREDICTOR_ENABLED    Zapnout/vypnout prediktor: "1" / "0" (výchozí: zapnuto)
  PREDICTOR_TIMEOUT_S  Timeout pro volání prediktoru v sekundách (výchozí: 60)
"""

import os

# ---------------------------------------------------------------------------
# Prediktor
# ---------------------------------------------------------------------------

PREDICTOR_URL: str = os.getenv("PREDICTOR_URL", "http://localhost:8000/api/predict_actions")
PREDICTOR_ENABLED: bool = os.getenv("PREDICTOR_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
PREDICTOR_TIMEOUT_S: float = float(os.getenv("PREDICTOR_TIMEOUT_S", "60"))

# ---------------------------------------------------------------------------
# Časy sledování (sekundy) – rozsah (min, max) pro reklamy a overlaye
# ---------------------------------------------------------------------------

WATCH_TIME_AD_OR_OVERLAY = (0.5, 1.5)  # reklama / overlay – krátká pauza před přeskočením

# ---------------------------------------------------------------------------
# Zařízení
# ---------------------------------------------------------------------------

DEVICES: list[dict] = [
    {"serial": "R58Y90R811Y", "name": "Device1", "session_id": "fa8d3bde-9fe2-48ce-8911-976d4c77f1a6"},
    {"serial": "R58Y90R6JWV", "name": "Device2", "session_id": "305f7081-da0e-48ca-8d44-81247da49b08"},
]

# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

INSTAGRAM_PACKAGE: str = "com.instagram.android"
