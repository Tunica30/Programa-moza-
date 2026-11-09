"""Procesamiento de señales: convierte los valores crudos del volante y los
pedales en valores listos para el juego, aplicando rotación, zonas muertas,
saturación y curvas de respuesta.

Todas las funciones son puras (sin estado) para poder probarlas fácilmente.
"""

from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


# ---------------------------------------------------------------- volante ---

def steering_degrees(raw: float, cfg: dict) -> float:
    """Grados reales que giró el volante (0 = centro, + = derecha).

    El eje crudo va de -1 a +1 y cubre toda la rotación configurada en
    Pit House (``hardware_rotation_deg``), así que ±1 = ±rotación/2.
    """
    v = raw - cfg.get("center", 0.0)
    if cfg.get("invert", False):
        v = -v
    return v * cfg["hardware_rotation_deg"] / 2.0


def process_steering(raw: float, cfg: dict) -> tuple[float, float]:
    """Devuelve ``(grados_reales, salida)`` con salida entre -1 y +1.

    * ``game_rotation_deg``: cuántos grados de volante hacen falta para llegar
      al tope en el juego. Menos grados = dirección más rápida/sensible.
    * ``deadzone``: zona muerta en el centro (fracción 0..1 de la salida).
    * ``gamma``: curva. 1 = lineal, >1 = más suave en el centro (más
      precisión), <1 = más agresivo en el centro.
    * ``anti_deadzone``: compensa la zona muerta interna que muchos juegos
      aplican al stick analógico (fracción 0..1).
    """
    deg = steering_degrees(raw, cfg)
    game_half = max(cfg["game_rotation_deg"], 1) / 2.0
    s = clamp(deg / game_half, -1.0, 1.0)

    sign = 1.0 if s >= 0 else -1.0
    a = abs(s)
    dz = clamp(cfg.get("deadzone", 0.0), 0.0, 0.95)
    if a <= dz or a < 1e-4:
        return deg, 0.0
    a = (a - dz) / (1.0 - dz)
    a = a ** max(cfg.get("gamma", 1.0), 0.05)
    anti = clamp(cfg.get("anti_deadzone", 0.0), 0.0, 0.9)
    if anti > 0:
        a = anti + (1.0 - anti) * a
    return deg, sign * clamp(a, 0.0, 1.0)


# ---------------------------------------------------------------- pedales ---

def normalize_pedal(raw: float, rest: float, full: float) -> float:
    """Pasa el valor crudo del eje a 0..1 usando la calibración
    (``rest`` = pedal suelto, ``full`` = pedal a fondo)."""
    if abs(full - rest) < 1e-6:
        return 0.0
    return clamp((raw - rest) / (full - rest), 0.0, 1.0)


def process_pedal(p: float, cfg: dict) -> float:
    """Aplica zona muerta inicial, saturación final y curva a un pedal
    normalizado (0..1).

    * ``deadzone``: lo que se ignora al principio del recorrido.
    * ``saturation``: a partir de este punto ya se considera 100 %.
    * ``gamma``: 1 = lineal, >1 = progresivo (más control al inicio),
      <1 = agresivo (responde mucho con poco recorrido).
    """
    dz = clamp(cfg.get("deadzone", 0.0), 0.0, 0.9)
    sat = clamp(cfg.get("saturation", 1.0), dz + 0.05, 1.0)
    if p <= dz:
        return 0.0
    if p >= sat:
        return 1.0
    p = (p - dz) / (sat - dz)
    return clamp(p ** max(cfg.get("gamma", 1.0), 0.05), 0.0, 1.0)


def pedal_curve_point(x: float, cfg: dict) -> float:
    """Para dibujar la curva: entrada 0..1 -> salida 0..1."""
    return process_pedal(x, cfg)


def steering_curve_point(x: float, cfg: dict) -> float:
    """Para dibujar la curva del volante: fracción 0..1 del recorrido de
    juego -> salida 0..1 (sólo el lado positivo, es simétrica)."""
    fake = dict(cfg, center=0.0, invert=False)
    raw = x * fake["game_rotation_deg"] / max(fake["hardware_rotation_deg"], 1)
    return process_steering(raw, fake)[1]
