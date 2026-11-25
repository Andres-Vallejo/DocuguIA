from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
# Reviewed against Google's pricing on 2026-11-25. No paid-model fallback.
FREE_MODELS = {"gemini-3.5-flash-lite", "gemini-2.5-flash-lite"}
MAX_KEY_LENGTH = 4096


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT

    @property
    def data_dir(self):
        return self.root / "data"

    @property
    def db(self):
        return self.data_dir / "documents.sqlite3"

    def values(self):
        values = dict(dotenv_values(self.root / ".env"))
        for name in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FREE_TIER_CONFIRMED",
                     "MAX_GEMINI_CALLS_PER_DAY", "MIN_GEMINI_INTERVAL_SECONDS"):
            if name in os.environ:
                values[name] = os.environ[name]
        return values

    def runtime(self):
        v = self.values()
        model = v.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
        return {
            "api_key": v.get("GEMINI_API_KEY") or "",
            "model": model,
            "free_confirmed": str(v.get("GEMINI_FREE_TIER_CONFIRMED", "false")).lower() == "true",
            "model_allowed": model in FREE_MODELS,
            "daily_limit": max(1, min(100, int(v.get("MAX_GEMINI_CALLS_PER_DAY") or 15))),
            "interval": max(1, min(3600, int(v.get("MIN_GEMINI_INTERVAL_SECONDS") or 12))),
        }

    def save_key(self, key: str, confirmed: bool):
        # Keep the key out of URL parameters, logs and response payloads.
        import re
        # Keys are opaque: auth keys may include dots and exceed legacy lengths.
        # Reject whitespace/control characters rather than assuming an old prefix.
        if not key:
            raise ValueError("Pega la clave completa de Google AI Studio en el campo de contraseña.")
        if not 20 <= len(key) <= MAX_KEY_LENGTH:
            raise ValueError("La clave parece incompleta o supera el tamaño permitido. Copia su valor completo desde Google AI Studio.")
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", key):
            raise ValueError("La clave contiene espacios o caracteres no válidos. Pega solo su valor, sin comillas ni saltos de línea.")
        if not confirmed:
            raise ValueError("Confirma la casilla Free después de comprobar que tu proyecto de Google está en el nivel gratuito.")
        if os.environ.get("GEMINI_API_KEY"):
            raise ValueError("La clave se gestiona mediante una variable de entorno; actualízala allí.")
        from dotenv import set_key
        path = self.root / ".env"
        path.touch(exist_ok=True)
        set_key(str(path), "GEMINI_API_KEY", key)
        set_key(str(path), "GEMINI_FREE_TIER_CONFIRMED", "true")
        if not self.values().get("GEMINI_MODEL"):
            set_key(str(path), "GEMINI_MODEL", "gemini-3.5-flash-lite")
