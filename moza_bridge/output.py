"""Salida hacia el juego: un mando de Xbox 360 virtual (ViGEmBus + vgamepad).

¿Por qué Xbox y no teclado? Una tecla es todo o nada (0 % o 100 %). El mando
virtual tiene gatillos y stick analógicos, así que el juego recibe exactamente
cuánto pisaste y cuánto giraste. Casi todos los juegos de PC (Need for Speed
Heat incluido) soportan mando de Xbox de forma nativa.
"""

from __future__ import annotations

import sys

try:  # vgamepad sólo existe en Windows (y necesita el driver ViGEmBus).
    import vgamepad as vg  # type: ignore
except Exception as exc:  # pragma: no cover - depende del sistema
    vg = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _button_map() -> dict:
    if vg is None:
        return {}
    B = vg.XUSB_BUTTON
    return {
        "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B,
        "X": B.XUSB_GAMEPAD_X, "Y": B.XUSB_GAMEPAD_Y,
        "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER, "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "BACK": B.XUSB_GAMEPAD_BACK, "START": B.XUSB_GAMEPAD_START,
        "LS": B.XUSB_GAMEPAD_LEFT_THUMB, "RS": B.XUSB_GAMEPAD_RIGHT_THUMB,
        "DPAD_UP": B.XUSB_GAMEPAD_DPAD_UP, "DPAD_DOWN": B.XUSB_GAMEPAD_DPAD_DOWN,
        "DPAD_LEFT": B.XUSB_GAMEPAD_DPAD_LEFT, "DPAD_RIGHT": B.XUSB_GAMEPAD_DPAD_RIGHT,
        "GUIDE": B.XUSB_GAMEPAD_GUIDE,
    }


class NullOutput:
    """Sin salida (modo sólo monitor)."""

    active = False

    def __init__(self, reason: str = "Salida desactivada"):
        self.status = reason

    def send(self, steer: float, lt: float, rt: float, buttons: set[str]) -> None:
        pass

    def close(self) -> None:
        pass


class XboxOutput:
    active = True

    def __init__(self):
        self.pad = vg.VX360Gamepad()
        self.map = _button_map()
        self.pressed: set[str] = set()
        self.status = "Mando Xbox 360 virtual conectado"

    def send(self, steer: float, lt: float, rt: float, buttons: set[str]) -> None:
        self.pad.left_joystick_float(x_value_float=steer, y_value_float=0.0)
        self.pad.left_trigger_float(value_float=lt)
        self.pad.right_trigger_float(value_float=rt)
        for b in buttons - self.pressed:
            if b in self.map:
                self.pad.press_button(button=self.map[b])
        for b in self.pressed - buttons:
            if b in self.map:
                self.pad.release_button(button=self.map[b])
        self.pressed = set(buttons)
        self.pad.update()

    def close(self) -> None:
        try:
            self.pad.reset()
            self.pad.update()
        except Exception:
            pass


def create_output(enabled: bool):
    if not enabled:
        return NullOutput("Modo sólo monitor (sin mando virtual)")
    if vg is None:
        if sys.platform != "win32":
            return NullOutput("Sin mando virtual: sólo funciona en Windows")
        return NullOutput("Falta vgamepad/ViGEmBus: ver README (pip install vgamepad)")
    try:
        return XboxOutput()
    except Exception as exc:  # pragma: no cover - depende del driver
        return NullOutput(f"No se pudo crear el mando virtual: {exc}")
