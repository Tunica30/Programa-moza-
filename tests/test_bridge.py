import copy

import pytest

from moza_bridge.calibrate import Calibrator
from moza_bridge.config import DEFAULT_CONFIG
from moza_bridge.devices import Device, parse_guid
from moza_bridge.engine import Engine
from moza_bridge.output import NullOutput
from moza_bridge.processing import (normalize_pedal, process_pedal,
                                    process_steering)

STEER = {"hardware_rotation_deg": 900, "game_rotation_deg": 540, "center": 0.0,
         "invert": False, "deadzone": 0.0, "gamma": 1.0, "anti_deadzone": 0.0}


def test_steering_degrees_and_scaling():
    deg, out = process_steering(0.2, STEER)  # 0.2 * 450 = 90°
    assert deg == pytest.approx(90)
    assert out == pytest.approx(90 / 270)
    # Más allá del tope del juego se satura.
    assert process_steering(0.9, STEER)[1] == 1.0
    assert process_steering(-0.9, STEER)[1] == -1.0


def test_steering_invert_center_deadzone_anti():
    cfg = dict(STEER, invert=True, center=0.1)
    deg, _ = process_steering(0.1, cfg)
    assert deg == pytest.approx(0)
    assert process_steering(0.3, cfg)[1] < 0
    cfg = dict(STEER, deadzone=0.1)
    assert process_steering(0.05, cfg)[1] == 0.0
    cfg = dict(STEER, anti_deadzone=0.2)
    assert process_steering(0.0, cfg)[1] == 0.0
    assert process_steering(0.01, cfg)[1] > 0.2


def test_pedal_normalize_inverted_axis():
    # Algunos pedales reposan en +1 y bajan al pisar.
    assert normalize_pedal(1.0, 1.0, -1.0) == 0.0
    assert normalize_pedal(-1.0, 1.0, -1.0) == 1.0
    assert normalize_pedal(0.0, 1.0, -1.0) == pytest.approx(0.5)


def test_pedal_deadzone_saturation_gamma():
    cfg = {"deadzone": 0.1, "saturation": 0.9, "gamma": 2.0}
    assert process_pedal(0.05, cfg) == 0.0
    assert process_pedal(0.95, cfg) == 1.0
    assert process_pedal(0.5, cfg) == pytest.approx(0.25)


def test_parse_guid():
    assert parse_guid("030000006e3400000500000000000000") == (0x346E, 0x0005)
    assert parse_guid("05000000" + "4d4f5a41" * 6) == (None, None)


class FakeDev(Device):
    def __init__(self, name, guid, axes, buttons=0):
        super().__init__(name, guid, len(axes), buttons, 0, 0)
        self.axes = list(axes)
        self.buttons = [False] * buttons

    def get_axis(self, i):
        return self.axes[i]

    def get_button(self, i):
        return self.buttons[i]


class FakeMgr:
    def __init__(self, devices):
        self.devices = devices
        self.demo = True

    def by_key(self, key):
        return next((d for d in self.devices if d.key == key), None)

    def find(self, ref):
        return self.by_key(ref["device"]) if ref else None

    def read_axis(self, ref):
        d = self.find(ref)
        return None if d is None else d.get_axis(ref["index"])

    def snapshot_axes(self):
        return {(d.key, i): d.get_axis(i) for d in self.devices for i in range(d.num_axes)}

    def rescan(self):
        pass


def test_calibration_detects_everything():
    base = FakeDev("MOZA R9", "base", [0.0], buttons=10)
    ped = FakeDev("MOZA SR-P", "ped", [-1.0, 1.0, -1.0])  # freno reposa en +1
    mgr = FakeMgr([base, ped])
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["button_targets"] = cfg["button_targets"][:2]
    cal = Calibrator(cfg, mgr)

    cal.confirm()                     # reposo
    ped.axes[0] = 1.0; cal.confirm()  # acelerador
    ped.axes[0] = -1.0
    ped.axes[1] = -1.0; cal.confirm()  # freno (eje invertido)
    ped.axes[1] = 1.0
    cal.skip()                        # sin embrague
    base.axes[0] = 0.25; cal.confirm()  # 90° con base a 720°
    base.buttons[3] = True; cal.poll_buttons()
    base.buttons[3] = False; cal.poll_buttons()
    base.buttons[3] = True; cal.poll_buttons()  # repetido -> error
    assert cal.error
    base.buttons[3] = False; cal.poll_buttons()
    base.buttons[7] = True; cal.poll_buttons()
    assert cal.done

    res = cal.result()
    assert res["pedals"]["throttle"]["axis"]["index"] == 0
    assert res["pedals"]["brake"]["axis"]["index"] == 1
    assert res["pedals"]["brake"]["rest"] == 1.0
    assert res["pedals"]["brake"]["full"] == -1.0
    assert res["pedals"]["clutch"]["axis"] is None
    assert res["steering"]["axis"]["device"] == "base"
    assert res["steering"]["hardware_rotation_deg"] == 720
    assert [(b["index"], b["xbox"]) for b in res["buttons"]] == [(3, "A"), (7, "B")]

    # Con la configuración detectada, el motor genera la salida correcta.
    ped.axes[0] = 0.0
    ped.axes[1] = 0.0
    base.buttons[3] = True
    st = Engine(res, mgr, NullOutput()).tick()
    assert 0.4 < st.right_trigger < 0.6
    assert 0.4 < st.left_trigger < 0.6
    assert st.steering_deg == pytest.approx(90)
    assert "A" in st.xbox_buttons


def test_game_profile_inherits_hardware_calibration():
    from moza_bridge.config import inherit_hardware
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["steering"]["game_rotation_deg"] = 360
    base = copy.deepcopy(DEFAULT_CONFIG)
    base["steering"].update(axis={"device": "b", "name": "x", "index": 0},
                            hardware_rotation_deg=1080, game_rotation_deg=900)
    base["pedals"]["brake"].update(axis={"device": "p", "name": "y", "index": 1}, rest=1.0, full=-1.0)
    base["buttons"] = [{"device": "b", "name": "x", "index": 2, "xbox": "A"}]
    inherit_hardware(cfg, base)
    assert cfg["steering"]["axis"]["device"] == "b"
    assert cfg["steering"]["hardware_rotation_deg"] == 1080
    assert cfg["steering"]["game_rotation_deg"] == 360  # el ajuste del juego se respeta
    assert cfg["pedals"]["brake"]["rest"] == 1.0
    assert cfg["pedals"]["throttle"]["axis"] is None
    assert cfg["buttons"][0]["xbox"] == "A"
