"""Motor principal: en cada ciclo lee los periféricos, procesa las señales y
las manda al mando virtual."""

from __future__ import annotations

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
    # (nombre de dispositivo, índice) de todos los botones físicos apretados
    raw_buttons: list[tuple[str, int]] = field(default_factory=list)


class Engine:
    def __init__(self, cfg: dict, devices: DeviceManager, output):
        self.cfg = cfg
        self.devices = devices
        self.output = output
        self.state = State()

    def compute(self) -> State:
        cfg = self.cfg
        st = State()

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

        self.state = st
        return st

    def tick(self) -> State:
        st = self.compute()
        self.output.send(st.steering_out, st.left_trigger, st.right_trigger,
                         st.xbox_buttons)
        return st
