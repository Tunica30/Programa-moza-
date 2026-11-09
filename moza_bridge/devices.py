"""Detección de periféricos (base MOZA, pedales, freno de mano, etc.).

Windows ve la base y los pedales MOZA como controladores de juego
DirectInput/HID estándar. Los leemos con SDL (vía pygame), que soporta
DirectInput, XInput y RawInput, así que también funcionan pedales o
shifters de otras marcas.
"""

from __future__ import annotations

import math
import time

import pygame

def parse_guid(guid: str) -> tuple[int | None, int | None]:
    """Extrae (VID, PID) de un GUID de SDL2 si lo contiene."""
    if not guid or len(guid) < 24:
        return None, None
    try:
        if guid[12:16] != "0000" or guid[20:24] != "0000":
            return None, None
        vid = int(guid[10:12] + guid[8:10], 16)
        pid = int(guid[18:20] + guid[16:18], 16)
        return (vid or None), (pid or None)
    except ValueError:
        return None, None


class Device:
    """Envoltorio común para un joystick real o simulado."""

    def __init__(self, name: str, guid: str, num_axes: int, num_buttons: int,
                 num_hats: int, instance_id: int):
        self.name = name
        self.guid = guid
        self.num_axes = num_axes
        self.num_buttons = num_buttons
        self.num_hats = num_hats
        self.instance_id = instance_id
        self.vid, self.pid = parse_guid(guid)
        self.is_moza = False

    @property
    def key(self) -> str:
        return self.guid

    def get_axis(self, i: int) -> float:  # pragma: no cover - interfaz
        raise NotImplementedError

    def get_button(self, i: int) -> bool:  # pragma: no cover - interfaz
        raise NotImplementedError

    def get_hat(self, i: int) -> tuple[int, int]:  # pragma: no cover
        return (0, 0)

    def ids(self) -> str:
        if self.vid is None:
            return "VID/PID desconocido"
        return f"VID {self.vid:04X} / PID {self.pid or 0:04X}"


class RealDevice(Device):
    def __init__(self, joy: "pygame.joystick.JoystickType"):
        super().__init__(joy.get_name(), joy.get_guid(), joy.get_numaxes(),
                         joy.get_numbuttons(), joy.get_numhats(),
                         joy.get_instance_id())
        self.joy = joy

    def get_axis(self, i: int) -> float:
        return self.joy.get_axis(i) if i < self.num_axes else 0.0

    def get_button(self, i: int) -> bool:
        return bool(self.joy.get_button(i)) if i < self.num_buttons else False

    def get_hat(self, i: int) -> tuple[int, int]:
        return self.joy.get_hat(i) if i < self.num_hats else (0, 0)


DEMO_GUID = "030000006e3400000c00000000000000"
DEMO_NAME = "MOZA R12 Base (DEMO)"
DEMO_GEAR_BUTTONS = 20   # botones 20..26 = marchas 1..7


class DemoDevice(Device):
    """Simula una base MOZA R12 con pedales CRP2, freno de mano y palanca H
    conectados a la base (todo aparece como un solo dispositivo)."""

    def __init__(self, instance_id: int = 0):
        super().__init__(DEMO_NAME, DEMO_GUID, 5, 40, 1, instance_id)
        self.t0 = time.monotonic()

    def get_axis(self, i: int) -> float:
        t = time.monotonic() - self.t0
        if i == 0:  # volante: ±200° con la base a 900°
            return math.sin(t * 0.6) * (200 / 450)
        cyc = t % 6.0
        if i == 1:  # acelerador
            p = max(0.0, math.sin(cyc / 3.0 * math.pi)) if cyc < 3 else 0.0
        elif i == 2:  # freno
            p = max(0.0, math.sin((cyc - 3.5) / 2.0 * math.pi)) if cyc > 3.5 else 0.0
        elif i == 4:  # freno de mano: tirón corto cada 6 s
            p = max(0.0, math.sin((cyc - 5.0) * math.pi)) if cyc > 5.0 else 0.0
        else:
            p = 0.0
        return p * 2 - 1  # reposo en -1, a fondo en +1

    def get_button(self, i: int) -> bool:
        t = time.monotonic() - self.t0
        gear = 1 + int(t / 2.5) % 4
        if DEMO_GEAR_BUTTONS <= i < DEMO_GEAR_BUTTONS + 7:
            return i - DEMO_GEAR_BUTTONS + 1 == gear and (t % 2.5) > 0.3  # 0.3 s en punto muerto
        return i == int(t) % 8 and (t % 1) < 0.3


class DeviceManager:
    def __init__(self, cfg: dict, demo: bool = False):
        self.cfg = cfg
        self.demo = demo
        self.devices: list[Device] = []
        self.rescan()

    def _is_moza(self, d: Device) -> bool:
        match = self.cfg.get("device_match", {})
        vids = {int(v, 16) for v in match.get("vendor_ids", [])}
        if d.vid is not None and d.vid in vids:
            return True
        lname = d.name.lower()
        return any(k.lower() in lname for k in match.get("name_keywords", []))

    def rescan(self) -> None:
        if self.demo:
            if not self.devices:
                self.devices = [DemoDevice(0)]
        else:
            if not pygame.joystick.get_init():
                pygame.joystick.init()
            self.devices = [RealDevice(pygame.joystick.Joystick(i))
                            for i in range(pygame.joystick.get_count())]
        for d in self.devices:
            d.is_moza = self._is_moza(d)
        # MOZA primero en la lista.
        self.devices.sort(key=lambda d: (not d.is_moza, d.name))

    def find(self, ref: dict | None) -> Device | None:
        """Busca el dispositivo de una referencia de eje/botón guardada.
        Primero por GUID; si cambió (otro puerto USB, etc.), por nombre."""
        if not ref:
            return None
        for d in self.devices:
            if d.guid == ref.get("device"):
                return d
        for d in self.devices:
            if d.name == ref.get("name"):
                return d
        return None

    def read_axis(self, ref: dict | None) -> float | None:
        d = self.find(ref)
        if d is None:
            return None
        return d.get_axis(ref["index"])

    def by_key(self, key: str) -> Device | None:
        for d in self.devices:
            if d.key == key:
                return d
        return None

    def snapshot_axes(self) -> dict[tuple[str, int], float]:
        return {(d.key, i): d.get_axis(i)
                for d in self.devices for i in range(d.num_axes)}


def describe_devices(mgr: DeviceManager) -> str:
    """Texto de diagnóstico para que el usuario lo copie y lo comparta."""
    lines = []
    if not mgr.devices:
        lines.append("No se detectó ningún controlador de juego.")
        lines.append("Revisá que Pit House reconozca la base y que el cable USB esté conectado.")
        return "\n".join(lines)
    for n, d in enumerate(mgr.devices):
        tag = "  <-- MOZA" if d.is_moza else ""
        lines.append(f"[{n}] {d.name}{tag}")
        lines.append(f"     {d.ids()}  |  GUID {d.guid}")
        lines.append(f"     ejes: {d.num_axes}  botones: {d.num_buttons}  hats: {d.num_hats}")
        if d.num_axes:
            vals = ", ".join(f"{i}:{d.get_axis(i):+.3f}" for i in range(d.num_axes))
            lines.append(f"     valores actuales de ejes -> {vals}")
    return "\n".join(lines)
