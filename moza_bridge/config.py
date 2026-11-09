"""Carga y guardado de perfiles (archivos JSON en la carpeta ``perfiles``)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = ROOT / "perfiles"

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


def load_profile(path: str | Path | None) -> tuple[dict, Path]:
    """Carga un perfil. Si no existe, devuelve la configuración por defecto
    (se creará al guardar)."""
    p = Path(path) if path else PROFILES_DIR / "general.json"
    if p.suffix != ".json":
        p = p.with_suffix(".json")
    if not p.is_absolute() and not p.exists():
        # "nfs_heat" -> perfiles/nfs_heat.json
        p = PROFILES_DIR / p
    data = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    cfg = _merge(DEFAULT_CONFIG, data)
    general = PROFILES_DIR / "general.json"
    if p.resolve() != general.resolve() and general.exists():
        with open(general, encoding="utf-8") as f:
            inherit_hardware(cfg, json.load(f))
    return cfg, p


def inherit_hardware(cfg: dict, base: dict) -> None:
    """Completa la calibración de hardware (qué eje es cada cosa, reposo,
    centro, rotación de la base y botones) desde el perfil general, para no
    tener que detectar los periféricos en cada perfil de juego."""
    s, bs = cfg["steering"], base.get("steering", {})
    if not s.get("axis") and bs.get("axis"):
        for k in ("axis", "center", "invert", "hardware_rotation_deg"):
            if k in bs:
                s[k] = bs[k]
    for key, pc in cfg["pedals"].items():
        bp = base.get("pedals", {}).get(key, {})
        if not pc.get("axis") and bp.get("axis"):
            for k in ("axis", "rest", "full"):
                if k in bp:
                    pc[k] = bp[k]
    if not cfg.get("buttons") and base.get("buttons"):
        cfg["buttons"] = copy.deepcopy(base["buttons"])
    bsh = base.get("shifter", {})
    if not cfg["shifter"].get("gears") and bsh.get("gears"):
        cfg["shifter"]["gears"] = copy.deepcopy(bsh["gears"])
        if "mode" in bsh:
            cfg["shifter"]["mode"] = bsh["mode"]


def save_profile(cfg: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(path)
