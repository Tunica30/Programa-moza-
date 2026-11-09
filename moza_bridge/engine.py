"""Motor principal: en cada ciclo lee los periféricos, procesa las señales y
las manda al mando virtual."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .devices import DeviceManager
from .processing import normalize_pedal, process_pedal, process_steering

HAT_TO_DPAD = {(0, 1): "DPAD_UP", (0, -1): "DPAD_DOWN",
               (-1, 0): "DPAD_LEFT", (1, 0): "DPAD_RIGHT"}


@dataclass
class PedalState:
    connected: bool = False
    raw: float = 0.0       # valor crudo del eje (-1..1)
    position: float = 0.0  # recorrido real 0..1 según la calibración
    output: float = 0.0    # lo que recibe el juego 0..1


@dataclass
class State:
    steering_connected: bool = False
    steering_raw: float = 0.0
    steering_deg: float = 0.0
    steering_out: float = 0.0
    pedals: dict[str, PedalState] = field(default_factory=dict)
    left_trigger: float = 0.0
    right_trigger: float = 0.0
    xbox_buttons: set[str] = field(default_factory=set)
    shifter_gear: int = 0          # marcha puesta en la palanca (0 = punto muerto)
    game_gear: int | None = None   # marcha que creemos que tiene el juego
    # (nombre de dispositivo, índice) de todos los botones físicos apretados
    raw_buttons: list[tuple[str, int]] = field(default_factory=list)


class ShifterEmulator:
    """Convierte una palanca H en toques de marcha arriba/abajo.

    Lleva la cuenta de en qué marcha está el juego; cuando ponés otra marcha
    en la palanca manda los toques necesarios (ej. de 2ª a 5ª = 3 toques de
    marcha arriba). Punto muerto y reversa no cambian nada.
    """

    def __init__(self):
        self.game_gear: int | None = None
        self.active: str | None = None
        self.phase = ""
        self.until = 0.0

    def resync(self, gear: int) -> None:
        self.game_gear = gear if gear > 0 else 1
        self.active = None

    def update(self, h_gear: int, cfg: dict, now: float) -> str | None:
        if cfg.get("mode") != "h_secuencial" or not cfg.get("gears"):
            self.game_gear = None
            return None
        if self.game_gear is None:
            self.resync(h_gear)
        pulse = max(0.02, cfg.get("pulse_ms", 70) / 1000.0)
        if self.active is not None:
            if now < self.until:
                return self.active if self.phase == "press" else None
            if self.phase == "press":
                self.phase, self.until = "gap", now + pulse
                return None
            self.active = None
        if h_gear > 0 and h_gear != self.game_gear:
            up = h_gear > self.game_gear
            self.game_gear += 1 if up else -1
            self.active = cfg.get("up_button", "RB") if up else cfg.get("down_button", "LB")
            self.phase, self.until = "press", now + pulse
            return self.active
        return None


class Engine:
    def __init__(self, cfg: dict, devices: DeviceManager, output):
        self.cfg = cfg
        self.devices = devices
        self.output = output
        self.state = State()
        self.shifter = ShifterEmulator()

    def current_h_gear(self) -> int:
        for g in self.cfg.get("shifter", {}).get("gears", []):
            d = self.devices.find(g)
            if d is not None and d.get_button(g["index"]):
                return int(g["gear"])
        return 0

    def compute(self, now: float | None = None) -> State:
        cfg = self.cfg
        st = State()
        now = time.monotonic() if now is None else now

        # Volante
        scfg = cfg["steering"]
        raw = self.devices.read_axis(scfg.get("axis"))
        if raw is not None:
            st.steering_connected = True
            st.steering_raw = raw
            st.steering_deg, st.steering_out = process_steering(raw, scfg)

        # Pedales
        for key, pcfg in cfg["pedals"].items():
            ps = PedalState()
            raw = self.devices.read_axis(pcfg.get("axis"))
            if raw is not None:
                ps.connected = True
                ps.raw = raw
                ps.position = normalize_pedal(raw, pcfg["rest"], pcfg["full"])
                ps.output = process_pedal(ps.position, pcfg)
                if pcfg.get("output") == "right_trigger":
                    st.right_trigger = max(st.right_trigger, ps.output)
                elif pcfg.get("output") == "left_trigger":
                    st.left_trigger = max(st.left_trigger, ps.output)
                elif pcfg.get("output") == "button" and ps.output > 0 \
                        and ps.output >= pcfg.get("threshold", 0.5):
                    st.xbox_buttons.add(pcfg.get("button", "A"))
            st.pedals[key] = ps

        # Botones físicos apretados (para mostrarlos en pantalla)
        for d in self.devices.devices:
            for i in range(d.num_buttons):
                if d.get_button(i):
                    st.raw_buttons.append((d.name, i))

        # Botones asignados
        for b in cfg.get("buttons", []):
            d = self.devices.find(b)
            if d is not None and d.get_button(b["index"]):
                st.xbox_buttons.add(b["xbox"])

        # Cruceta -> D-pad
        if cfg.get("hats_to_dpad", True):
            for d in self.devices.devices:
                if not d.is_moza:
                    continue
                for h in range(d.num_hats):
                    x, y = d.get_hat(h)
                    if x:
                        st.xbox_buttons.add(HAT_TO_DPAD[(x, 0)])
                    if y:
                        st.xbox_buttons.add(HAT_TO_DPAD[(0, y)])

        # Palanca H -> marcha arriba/abajo
        st.shifter_gear = self.current_h_gear()
        pulse_btn = self.shifter.update(st.shifter_gear, cfg.get("shifter", {}), now)
        if pulse_btn:
            st.xbox_buttons.add(pulse_btn)
        st.game_gear = self.shifter.game_gear

        self.state = st
        return st

    def tick(self) -> State:
        st = self.compute()
        self.output.send(st.steering_out, st.left_trigger, st.right_trigger,
                         st.xbox_buttons)
        return st
