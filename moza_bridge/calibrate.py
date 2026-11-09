"""Asistente de detección automática.

Pide al usuario mover cada control y detecta solo qué eje/botón es cuál,
en qué dirección se mueve y cuánta rotación tiene el volante. Funciona aunque
los pedales estén conectados por USB aparte (cada uno es otro dispositivo).
"""

from __future__ import annotations

import copy

from .devices import DeviceManager

MIN_PEDAL_TRAVEL = 0.30   # cambio mínimo del eje para aceptar un pedal
MIN_STEER_TRAVEL = 0.05   # cambio mínimo para aceptar el volante
STEER_TEST_DEG = 90


def _ref(mgr: DeviceManager, key: str, index: int) -> dict:
    d = mgr.by_key(key)
    return {"device": key, "name": d.name if d else "", "index": index}


class Calibrator:
    def __init__(self, cfg: dict, mgr: DeviceManager):
        self.mgr = mgr
        self.work = copy.deepcopy(cfg)
        self.work["buttons"] = []
        self.rest: dict = {}
        self.used_axes: set[tuple[str, int]] = set()
        self.steps: list[tuple] = [("rest",)]
        for key, p in cfg["pedals"].items():
            self.steps.append(("pedal", key, p.get("label", key)))
        self.steps.append(("steer",))
        for t in cfg.get("button_targets", []):
            self.steps.append(("button", t["label"], t["xbox"]))
        self.i = 0
        self.error = ""
        self.done = False
        self.log: list[str] = []
        self.prev_buttons = self._buttons_now()

    # ----------------------------------------------------------- textos ---
    @property
    def step(self) -> tuple:
        return self.steps[self.i]

    def instruction(self) -> list[str]:
        s = self.step
        n = f"Paso {self.i + 1}/{len(self.steps)}"
        if s[0] == "rest":
            return [n, "Soltá TODOS los pedales y dejá el volante CENTRADO.",
                    "Después presioná ESPACIO."]
        if s[0] == "pedal":
            return [n, f"Pisá el {s[2].upper()} A FONDO y mantenelo.",
                    "Presioná ESPACIO sin soltarlo.  (S = no tengo este pedal)"]
        if s[0] == "steer":
            return [n, f"Girá el volante {STEER_TEST_DEG}° a la DERECHA",
                    "(la marca de arriba del aro apuntando a las 3 en punto).",
                    "Mantenelo ahí y presioná ESPACIO."]
        return [n, f"Apretá en el volante el botón para: {s[1]}  (-> Xbox {s[2]})",
                "S = saltar este botón"]

    # --------------------------------------------------------- acciones ---
    def _buttons_now(self) -> set[tuple[str, int]]:
        return {(d.key, i) for d in self.mgr.devices
                for i in range(d.num_buttons) if d.get_button(i)}

    def _advance(self) -> None:
        self.error = ""
        self.i += 1
        if self.i >= len(self.steps):
            self.done = True

    def skip(self) -> None:
        s = self.step
        if s[0] == "pedal":
            self.work["pedals"][s[1]]["axis"] = None
            self.log.append(f"{s[2]}: omitido")
        elif s[0] == "button":
            self.log.append(f"{s[1]}: omitido")
        elif s[0] in ("rest", "steer"):
            self.error = "Este paso no se puede saltar."
            return
        self._advance()

    def _biggest_change(self, exclude: set) -> tuple[tuple[str, int] | None, float]:
        now = self.mgr.snapshot_axes()
        best, best_delta = None, 0.0
        for k, v in now.items():
            if k in exclude or k not in self.rest:
                continue
            delta = v - self.rest[k]
            if abs(delta) > abs(best_delta):
                best, best_delta = k, delta
        return best, best_delta

    def confirm(self) -> None:
        """Se llama al presionar ESPACIO."""
        s = self.step
        if s[0] == "rest":
            self.rest = self.mgr.snapshot_axes()
            if not self.rest:
                self.error = "No hay ejes: ¿está conectado el volante?"
                return
            self._advance()
        elif s[0] == "pedal":
            axis, delta = self._biggest_change(self.used_axes)
            if axis is None or abs(delta) < MIN_PEDAL_TRAVEL:
                self.error = "No detecté movimiento. Pisalo a fondo y probá de nuevo."
                return
            p = self.work["pedals"][s[1]]
            p["axis"] = _ref(self.mgr, *axis)
            p["rest"] = round(self.rest[axis], 4)
            p["full"] = round(self.rest[axis] + delta, 4)
            self.used_axes.add(axis)
            self.log.append(f"{s[2]}: {p['axis']['name']} eje {axis[1]}")
            self._advance()
        elif s[0] == "steer":
            axis, delta = self._biggest_change(self.used_axes)
            if axis is None or abs(delta) < MIN_STEER_TRAVEL:
                self.error = "No detecté el giro. Girá más el volante y probá de nuevo."
                return
            sc = self.work["steering"]
            sc["axis"] = _ref(self.mgr, *axis)
            sc["center"] = round(self.rest[axis], 4)
            sc["invert"] = delta < 0
            # Si giró 90°, el eje se movió 90 / (rotación/2).
            est = STEER_TEST_DEG * 2 / abs(delta)
            sc["hardware_rotation_deg"] = int(round(est / 10.0) * 10)
            self.used_axes.add(axis)
            self.log.append(f"Volante: {sc['axis']['name']} eje {axis[1]}, "
                            f"rotación estimada {sc['hardware_rotation_deg']}°")
            self._advance()

    def poll_buttons(self) -> None:
        """Llamar en cada frame: detecta botones nuevos apretados."""
        now = self._buttons_now()
        new = now - self.prev_buttons
        self.prev_buttons = now
        if self.done or self.step[0] != "button" or not new:
            return
        key, idx = sorted(new)[0]
        s = self.step
        taken = {(b["device"], b["index"]) for b in self.work["buttons"]}
        if (key, idx) in taken:
            self.error = "Ese botón ya está asignado, usá otro (o S para saltar)."
            return
        ref = _ref(self.mgr, key, idx)
        ref["xbox"] = s[2]
        self.work["buttons"].append(ref)
        self.log.append(f"{s[1]}: botón {idx} -> {s[2]}")
        self._advance()

    def result(self) -> dict:
        return self.work
