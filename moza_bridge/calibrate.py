"""Asistente de detección automática.

Pide al usuario mover cada control y detecta solo qué eje/botón es cuál,
en qué dirección se mueve y cuánta rotación tiene el volante. Funciona tanto
si los pedales, freno de mano y palanca van conectados a la base (aparecen
como ejes/botones de la base) como si van por USB aparte.
"""

from __future__ import annotations

import copy

from .config import MAX_ROTATION_DEG, MIN_ROTATION_DEG
from .devices import DeviceManager

MIN_PEDAL_TRAVEL = 0.30   # cambio mínimo del eje para aceptar un pedal
MIN_STEER_TRAVEL = 0.05   # cambio mínimo para aceptar el volante
STEER_TEST_DEG = 90
MAX_GEARS = 7


def _ref(mgr: DeviceManager, key: str, index: int) -> dict:
    d = mgr.by_key(key)
    return {"device": key, "name": d.name if d else "", "index": index}


def gear_name(n: int) -> str:
    return f"{n}ª"


class Calibrator:
    def __init__(self, cfg: dict, mgr: DeviceManager):
        self.mgr = mgr
        self.work = copy.deepcopy(cfg)
        self.work["buttons"] = []
        self.work["shifter"]["gears"] = []
        self.rest: dict = {}
        self.rest_buttons: set = set()
        self.used_axes: set[tuple[str, int]] = set()
        self.steps: list[tuple] = [("rest",)]
        for key, p in cfg["pedals"].items():
            self.steps.append(("pedal", key, p.get("label", key)))
        self.steps.append(("steer",))
        self.steps.append(("rotation",))
        for g in range(1, MAX_GEARS + 1):
            self.steps.append(("gear", g))
        for t in cfg.get("button_targets", []):
            self.steps.append(("button", t["label"], t["xbox"]))
        self.i = 0
        self.error = ""
        self.done = False
        self.typed = ""          # texto tipeado en el paso de rotación
        self.estimated_rotation = int(cfg["steering"]["hardware_rotation_deg"])
        self.log: list[str] = []
        self.prev_buttons = self._buttons_now()

    # ----------------------------------------------------------- textos ---
    @property
    def step(self) -> tuple:
        return self.steps[self.i]

    @property
    def wants_text(self) -> bool:
        return not self.done and self.step[0] == "rotation"

    def instruction(self) -> list[str]:
        s = self.step
        n = f"Paso {self.i + 1}/{len(self.steps)}"
        if s[0] == "rest":
            return [n, "Soltá pedales y freno de mano, palanca en PUNTO MUERTO,",
                    "volante CENTRADO. Después presioná ESPACIO."]
        if s[0] == "pedal":
            if s[1] == "handbrake":
                return [n, "Tirá del FRENO DE MANO a fondo y mantenelo.",
                        "Presioná ESPACIO.  (S = no tengo / lo uso en modo botón)"]
            return [n, f"Pisá el {s[2].upper()} A FONDO y mantenelo.",
                    "Presioná ESPACIO sin soltarlo.  (S = no tengo este pedal)"]
        if s[0] == "steer":
            return [n, f"Girá el volante {STEER_TEST_DEG}° a la DERECHA",
                    "(la marca de arriba del aro apuntando a las 3 en punto).",
                    "Mantenelo ahí y presioná ESPACIO."]
        if s[0] == "rotation":
            shown = self.typed if self.typed else f"{self.estimated_rotation}"
            return [n, f"Rotación configurada en Pit House:  {shown}°",
                    f"Escribí el número (ej. 900, 1080) y ENTER.  Estimado: "
                    f"{self.estimated_rotation}°",
                    f"Rango {MIN_ROTATION_DEG}-{MAX_ROTATION_DEG}°. ENTER sin escribir = usar estimado."]
        if s[0] == "gear":
            if s[1] == 1:
                return [n, "Palanca H: poné PRIMERA (1ª) y presioná ESPACIO.",
                        "S = no tengo palanca H / la uso en modo secuencial"]
            return [n, f"Poné la marcha {gear_name(s[1])} y presioná ESPACIO.",
                    "S = no tengo más marchas"]
        return [n, f"Apretá en el volante el botón para: {s[1]}  (-> Xbox {s[2]})",
                "S = saltar este botón"]

    # --------------------------------------------------------- acciones ---
    def _buttons_now(self) -> set[tuple[str, int]]:
        return {(d.key, i) for d in self.mgr.devices
                for i in range(d.num_buttons) if d.get_button(i)}

    def _gear_buttons(self) -> set[tuple[str, int]]:
        return {(g["device"], g["index"]) for g in self.work["shifter"]["gears"]}

    def _redundant(self, s: tuple) -> bool:
        """Un botón ya cubierto por el freno de mano analógico se salta."""
        if s[0] != "button":
            return False
        hb = self.work["pedals"].get("handbrake")
        return bool(hb and hb.get("axis") and hb.get("output") == "button"
                    and hb.get("button") == s[2])

    def _advance(self) -> None:
        self.error = ""
        self.i += 1
        while self.i < len(self.steps) and self._redundant(self.steps[self.i]):
            self.log.append(f"{self.steps[self.i][1]}: ya lo maneja el freno de mano")
            self.i += 1
        if self.i >= len(self.steps):
            self.done = True

    def _skip_gears(self) -> None:
        while self.i < len(self.steps) and self.steps[self.i][0] == "gear":
            self.i += 1
        self.i -= 1
        self._advance()

    def skip(self) -> None:
        s = self.step
        if s[0] == "pedal":
            self.work["pedals"][s[1]]["axis"] = None
            self.log.append(f"{s[2]}: omitido")
        elif s[0] == "button":
            self.log.append(f"{s[1]}: omitido")
        elif s[0] == "gear":
            if s[1] == 1:
                self.work["shifter"]["mode"] = "none"
                self.log.append("Palanca H: omitida")
            else:
                self.log.append(f"Palanca H: {s[1] - 1} marchas")
            self._skip_gears()
            return
        else:
            self.error = "Este paso no se puede saltar."
            return
        self._advance()

    def type_char(self, ch: str) -> None:
        if self.wants_text and ch.isdigit() and len(self.typed) < 4:
            self.typed += ch

    def backspace(self) -> None:
        if self.wants_text:
            self.typed = self.typed[:-1]

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
        """Se llama al presionar ESPACIO o ENTER."""
        s = self.step
        if s[0] == "rest":
            self.rest = self.mgr.snapshot_axes()
            self.rest_buttons = self._buttons_now()
            if not self.rest:
                self.error = "No hay ejes: ¿está conectado el volante?"
                return
            self._advance()
        elif s[0] == "pedal":
            axis, delta = self._biggest_change(self.used_axes)
            if axis is None or abs(delta) < MIN_PEDAL_TRAVEL:
                self.error = "No detecté movimiento. Llevalo a fondo y probá de nuevo."
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
            est = int(round(est / 10.0) * 10)
            self.estimated_rotation = max(MIN_ROTATION_DEG, min(MAX_ROTATION_DEG, est))
            self.used_axes.add(axis)
            self.log.append(f"Volante: {sc['axis']['name']} eje {axis[1]}")
            self._advance()
        elif s[0] == "rotation":
            val = int(self.typed) if self.typed else self.estimated_rotation
            if not MIN_ROTATION_DEG <= val <= MAX_ROTATION_DEG:
                self.error = f"Tiene que estar entre {MIN_ROTATION_DEG} y {MAX_ROTATION_DEG}°."
                self.typed = ""
                return
            self.work["steering"]["hardware_rotation_deg"] = val
            self.log.append(f"Rotación de la base: {val}°")
            self._advance()
        elif s[0] == "gear":
            cand = sorted(self._buttons_now() - self.rest_buttons - self._gear_buttons())
            if not cand:
                self.error = "No detecté la marcha. Enganchala bien y presioná ESPACIO."
                return
            ref = _ref(self.mgr, *cand[0])
            ref["gear"] = s[1]
            self.work["shifter"]["gears"].append(ref)
            self.work["shifter"]["mode"] = "h_secuencial"
            if s[1] == MAX_GEARS:
                self.log.append(f"Palanca H: {MAX_GEARS} marchas")
            self._advance()

    def poll_buttons(self) -> None:
        """Llamar en cada frame: detecta botones nuevos apretados."""
        now = self._buttons_now()
        new = now - self.prev_buttons - self._gear_buttons()
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
