"""Carga y guardado de perfiles (archivos JSON en la carpeta ``perfiles``)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Perfiles que vienen con el programa (sólo lectura, sirven de base).
PROFILES_DIR = ROOT / "perfiles"


def user_profiles_dir() -> Path:
    """Carpeta donde se guardan TUS perfiles y la detección. Está fuera de la
    carpeta del programa para no perderlos al bajar una versión nueva.
    En Windows: %APPDATA%\\MozaBridge\\perfiles"""
    override = os.environ.get("MOZA_BRIDGE_HOME")
    if override:
        return Path(override) / "perfiles"
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "MozaBridge" / "perfiles"
    return Path.home() / ".moza_bridge" / "perfiles"

# Botones de mando Xbox disponibles como destino.
XBOX_BUTTONS = [
    "A", "B", "X", "Y", "LB", "RB", "BACK", "START",
    "LS", "RS", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "GUIDE",
]

PEDAL_OUTPUTS = ["right_trigger", "left_trigger", "button", "none"]

SHIFTER_MODES = ["h_secuencial", "none"]

MIN_ROTATION_DEG = 90
MAX_ROTATION_DEG = 2700

DEFAULT_CONFIG: dict = {
    "profile_name": "General",
    "device_match": {
        # 346E = Gudsen Technology (fabricante de MOZA Racing).
        "vendor_ids": ["346E"],
        "name_keywords": ["moza", "gudsen"],
    },
    "output": {"enabled": True, "update_hz": 250},
    "steering": {
        "axis": None,               # {"device": guid, "name": str, "index": int}
        "hardware_rotation_deg": 900,
        "game_rotation_deg": 540,
        "invert": False,
        "center": 0.0,
        "deadzone": 0.0,
        "gamma": 1.0,
        "anti_deadzone": 0.0,
    },
    "pedals": {
        "throttle": {"label": "Acelerador", "axis": None, "rest": -1.0, "full": 1.0,
                     "deadzone": 0.03, "saturation": 0.97, "gamma": 1.0,
                     "output": "right_trigger"},
        "brake": {"label": "Freno", "axis": None, "rest": -1.0, "full": 1.0,
                  "deadzone": 0.03, "saturation": 0.90, "gamma": 1.0,
                  "output": "left_trigger"},
        "clutch": {"label": "Embrague", "axis": None, "rest": -1.0, "full": 1.0,
                   "deadzone": 0.05, "saturation": 0.95, "gamma": 1.0,
                   "output": "none"},
        # Freno de mano analógico (MOZA HBP en modo eje). Los juegos de mando
        # usan el freno de mano como botón: se aprieta al pasar el umbral.
        "handbrake": {"label": "Freno de mano", "axis": None, "rest": -1.0, "full": 1.0,
                      "deadzone": 0.05, "saturation": 0.90, "gamma": 1.0,
                      "output": "button", "button": "A", "threshold": 0.30},
    },
    # Palanca H (MOZA HGP): cada marcha es un botón. En modo "h_secuencial"
    # se convierte en toques de marcha arriba/abajo para juegos que sólo
    # tienen cambios secuenciales (como NFS Heat).
    "shifter": {
        "mode": "none",
        "gears": [],          # [{"device", "name", "index", "gear": 1}, ...]
        "up_button": "RB",
        "down_button": "LB",
        "pulse_ms": 70,
    },
    # Lista de acciones que el asistente pide asignar a botones del volante.
    "button_targets": [
        {"label": "Freno de mano", "xbox": "A"},
        {"label": "Nitro", "xbox": "B"},
        {"label": "Cambiar cámara", "xbox": "Y"},
        {"label": "Mirar atrás", "xbox": "X"},
        {"label": "Marcha arriba / acción RB", "xbox": "RB"},
        {"label": "Marcha abajo / acción LB", "xbox": "LB"},
        {"label": "Pausa / menú", "xbox": "START"},
        {"label": "Mapa / atrás", "xbox": "BACK"},
    ],
    # Lista de {"device": guid, "name": str, "index": int, "xbox": "A"}.
    "buttons": [],
    # Mapear la cruceta (hat) de los dispositivos MOZA al D-pad del mando.
    "hats_to_dpad": True,
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_profile(path: str | Path | None) -> tuple[dict, Path]:
    """Carga un perfil por nombre ("nfs_heat") o ruta a un .json.

    Por nombre, primero busca en tu carpeta de usuario y si no está usa el
    que viene con el programa. Siempre se guarda en tu carpeta de usuario.
    Si no existe, devuelve la configuración por defecto."""
    name = Path(path) if path else Path("general")
    if name.suffix != ".json":
        name = name.with_suffix(".json")
    user_dir = user_profiles_dir()
    if name.is_absolute() or len(name.parts) > 1:
        src = save_path = name
    else:
        save_path = user_dir / name
        src = save_path if save_path.exists() else PROFILES_DIR / name
    data = _read(src) if src.exists() else {}
    cfg = _merge(DEFAULT_CONFIG, data)
    if name.name != "general.json":
        for general in (user_dir / "general.json", PROFILES_DIR / "general.json"):
            if general.exists():
                inherit_hardware(cfg, _read(general))
                break
    return cfg, save_path


def inherit_hardware(cfg: dict, base: dict, force: bool = False) -> None:
    """Copia la calibración de hardware (qué eje es cada cosa, reposo,
    centro, rotación de la base, botones y palanca) desde ``base``.

    Sin ``force`` sólo completa lo que falta (así un perfil de juego usa la
    detección del perfil general); con ``force`` la reemplaza."""
    s, bs = cfg["steering"], base.get("steering", {})
    if bs.get("axis") and (force or not s.get("axis")):
        for k in ("axis", "center", "invert", "hardware_rotation_deg"):
            if k in bs:
                s[k] = bs[k]
    for key, pc in cfg["pedals"].items():
        bp = base.get("pedals", {}).get(key, {})
        if force or (not pc.get("axis") and bp.get("axis")):
            for k in ("axis", "rest", "full"):
                if k in bp:
                    pc[k] = bp[k]
    if base.get("buttons") and (force or not cfg.get("buttons")):
        cfg["buttons"] = copy.deepcopy(base["buttons"])
    bsh = base.get("shifter", {})
    if force or (not cfg["shifter"].get("gears") and bsh.get("gears")):
        cfg["shifter"]["gears"] = copy.deepcopy(bsh.get("gears", []))
        if "mode" in bsh:
            cfg["shifter"]["mode"] = bsh["mode"]


def share_hardware(cfg: dict) -> None:
    """Guarda la detección también en el perfil general, para que todos los
    perfiles de juego la usen sin volver a detectar."""
    general, path = load_profile("general")
    inherit_hardware(general, cfg, force=True)
    save_profile(general, path)


def save_profile(cfg: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
