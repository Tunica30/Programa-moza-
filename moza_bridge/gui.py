"""Ventana principal: muestra en vivo cuánto giraste el volante y cuánto
pisaste cada pedal (real vs. lo que recibe el juego), la curva de respuesta,
un historial de los últimos segundos y permite ajustar todo con el teclado.
"""

from __future__ import annotations

import math
import time
from collections import deque

import pygame

from .calibrate import Calibrator
from .config import (MAX_ROTATION_DEG, MIN_ROTATION_DEG, PEDAL_OUTPUTS,
                     SHIFTER_MODES, XBOX_BUTTONS, save_profile)
from .devices import DeviceManager
from .engine import Engine
from .processing import pedal_curve_point, steering_curve_point

W, H = 1180, 720
BG = (18, 20, 26)
PANEL = (30, 33, 42)
TEXT = (225, 228, 235)
MUTED = (130, 136, 150)
ACCENT = (255, 140, 40)    # naranja MOZA-ish
GREEN = (70, 200, 120)
RED = (235, 75, 75)
BLUE = (80, 160, 255)
YELLOW = (240, 200, 60)
PURPLE = (190, 120, 255)
PEDAL_COLORS = {"throttle": GREEN, "brake": RED, "clutch": BLUE, "handbrake": PURPLE}

HISTORY_SECONDS = 6.0

# Parámetros ajustables: (clave, etiqueta, paso, mínimo, máximo, formato)
# ENTER sobre un parámetro numérico permite escribir el valor exacto.
STEER_PARAMS = [
    ("hardware_rotation_deg", "Rotación de la base (Pit House)", 10,
     MIN_ROTATION_DEG, MAX_ROTATION_DEG, "{:.0f}°"),
    ("game_rotation_deg", "Rotación en el juego (°)", 10,
     MIN_ROTATION_DEG, MAX_ROTATION_DEG, "{:.0f}°"),
    ("deadzone", "Zona muerta central", 0.01, 0.0, 0.5, "{:.0%}"),
    ("gamma", "Curva (1 = lineal)", 0.05, 0.3, 3.0, "{:.2f}"),
    ("anti_deadzone", "Anti zona muerta del juego", 0.01, 0.0, 0.5, "{:.0%}"),
    ("invert", "Invertir", None, None, None, "{}"),
]
PEDAL_PARAMS = [
    ("deadzone", "Zona muerta inicial", 0.01, 0.0, 0.5, "{:.0%}"),
    ("saturation", "Saturación (100% en)", 0.01, 0.3, 1.0, "{:.0%}"),
    ("gamma", "Curva (1 = lineal)", 0.05, 0.3, 3.0, "{:.2f}"),
    ("output", "Salida al mando", None, None, None, "{}"),
    ("button", "Botón (si salida = botón)", None, None, None, "{}"),
    ("threshold", "Umbral del botón", 0.01, 0.05, 0.95, "{:.0%}"),
]
SHIFTER_PARAMS = [
    ("mode", "Modo de la palanca H", None, None, None, "{}"),
    ("up_button", "Marcha arriba -> botón", None, None, None, "{}"),
    ("down_button", "Marcha abajo -> botón", None, None, None, "{}"),
    ("pulse_ms", "Duración del toque (ms)", 10, 20, 300, "{:.0f} ms"),
]
OUTPUT_NAMES = {"right_trigger": "Gatillo RT", "left_trigger": "Gatillo LT",
                "button": "Botón", "none": "Ninguna"}
MODE_NAMES = {"h_secuencial": "H -> secuencial", "none": "Apagada"}
CYCLE_OPTIONS = {"output": PEDAL_OUTPUTS, "mode": SHIFTER_MODES,
                 "button": XBOX_BUTTONS, "up_button": XBOX_BUTTONS,
                 "down_button": XBOX_BUTTONS}


class App:
    def __init__(self, cfg: dict, profile_path, devices: DeviceManager, output):
        pygame.display.init()
        pygame.font.init()
        pygame.joystick.init()
        pygame.display.set_caption(f"MOZA Bridge - {cfg['profile_name']}")
        self.screen = pygame.display.set_mode((W, H))
        self.f_small = pygame.font.Font(None, 20)
        self.f = pygame.font.Font(None, 24)
        self.f_big = pygame.font.Font(None, 38)
        self.cfg = cfg
        self.path = profile_path
        self.devices = devices
        self.output = output
        self.engine = Engine(cfg, devices, output)
        self.controls = ["steering"] + list(cfg["pedals"].keys()) + ["shifter"]
        self.sel_control = 0
        self.sel_param = 0
        self.editing: str | None = None   # texto tipeado al editar un valor
        self.dirty = False
        self.toast = ("", 0.0)
        self.calib: Calibrator | None = None
        self.history: deque = deque()
        self.peak_deg = 0.0
        if cfg["steering"].get("axis") is None and devices.devices and not devices.demo:
            self.start_calibration()

    # ------------------------------------------------------------ helpers --
    def text(self, s, pos, color=TEXT, font=None, center=False):
        surf = (font or self.f).render(str(s), True, color)
        rect = surf.get_rect()
        if center:
            rect.center = pos
        else:
            rect.topleft = pos
        self.screen.blit(surf, rect)
        return rect

    def panel(self, rect, title=None):
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=10)
        if title:
            self.text(title, (rect[0] + 14, rect[1] + 10), MUTED, self.f)

    def notify(self, msg):
        self.toast = (msg, time.monotonic() + 3.0)

    def control_label(self, c):
        if c == "steering":
            return "Volante"
        if c == "shifter":
            return "Palanca"
        return self.cfg["pedals"][c].get("label", c)

    def current_cfg(self):
        c = self.controls[self.sel_control]
        if c == "steering":
            return self.cfg["steering"], STEER_PARAMS
        if c == "shifter":
            return self.cfg["shifter"], SHIFTER_PARAMS
        return self.cfg["pedals"][c], PEDAL_PARAMS

    # -------------------------------------------------------- calibración --
    def start_calibration(self):
        self.devices.rescan()
        self.editing = None
        self.calib = Calibrator(self.cfg, self.devices)

    def finish_calibration(self):
        new = self.calib.result()
        self.cfg.clear()
        self.cfg.update(new)
        self.engine.cfg = self.cfg
        self.engine.shifter.resync(self.engine.current_h_gear())
        self.calib = None
        save_profile(self.cfg, self.path)
        self.dirty = False
        self.notify(f"Detección completa. Guardado en {self.path.name}")

    # ------------------------------------------------------------ teclado --
    def adjust(self, direction, big=False):
        c, params = self.current_cfg()
        key, _, step, lo, hi, _ = params[self.sel_param]
        if key == "invert":
            c[key] = not c.get(key, False)
        elif key in CYCLE_OPTIONS:
            opts = CYCLE_OPTIONS[key]
            cur = c.get(key, opts[0])
            i = opts.index(cur) if cur in opts else 0
            c[key] = opts[(i + direction) % len(opts)]
        else:
            v = c.get(key, 0) + direction * step * (5 if big else 1)
            c[key] = round(min(hi, max(lo, v)), 4)
        self.dirty = True

    def commit_edit(self):
        """Aplica el valor tipeado (los porcentajes se escriben como 5 = 5 %)."""
        c, params = self.current_cfg()
        key, label, _step, lo, hi, fmt = params[self.sel_param]
        txt, self.editing = self.editing, None
        try:
            v = float(txt.replace(",", "."))
        except (ValueError, AttributeError):
            return
        if "%" in fmt:
            v /= 100.0
        if not lo <= v <= hi:
            shown = (f"{lo:.0%} y {hi:.0%}" if "%" in fmt else f"{lo:g} y {hi:g}")
            self.notify(f"{label}: tiene que estar entre {shown}")
            return
        c[key] = int(round(v)) if "{:.0f}" in fmt else round(v, 4)
        self.dirty = True

    def on_key(self, ev) -> bool:
        k = ev.key
        if self.calib:
            if k in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.calib.confirm()
            elif k == pygame.K_BACKSPACE:
                self.calib.backspace()
            elif self.calib.wants_text and ev.unicode.isdigit():
                self.calib.type_char(ev.unicode)
            elif k == pygame.K_s:
                self.calib.skip()
            elif k == pygame.K_ESCAPE:
                self.calib = None
                self.notify("Detección cancelada")
            if self.calib and self.calib.done:
                self.finish_calibration()
            return True
        if self.editing is not None:
            if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.commit_edit()
            elif k == pygame.K_ESCAPE:
                self.editing = None
            elif k == pygame.K_BACKSPACE:
                self.editing = self.editing[:-1]
            elif ev.unicode and ev.unicode in "0123456789.," and len(self.editing) < 6:
                self.editing += ev.unicode
            return True
        if k == pygame.K_ESCAPE:
            return False
        shift = bool(ev.mod & pygame.KMOD_SHIFT)
        if k == pygame.K_TAB:
            self.sel_control = (self.sel_control + (-1 if shift else 1)) % len(self.controls)
            self.sel_param = 0
        elif pygame.K_1 <= k <= pygame.K_9 and k - pygame.K_1 < len(self.controls):
            self.sel_control = k - pygame.K_1
            self.sel_param = 0
        elif k in (pygame.K_UP, pygame.K_DOWN):
            n = len(self.current_cfg()[1])
            self.sel_param = (self.sel_param + (1 if k == pygame.K_DOWN else -1)) % n
        elif k in (pygame.K_LEFT, pygame.K_RIGHT):
            self.adjust(1 if k == pygame.K_RIGHT else -1, shift)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            _c, params = self.current_cfg()
            if params[self.sel_param][2] is not None:   # parámetro numérico
                self.editing = ""
        elif k == pygame.K_g:
            save_profile(self.cfg, self.path)
            self.dirty = False
            self.notify(f"Perfil guardado: {self.path.name}")
        elif k == pygame.K_c:
            self.start_calibration()
        elif k == pygame.K_r:
            sc = self.cfg["steering"]
            st = self.engine.state
            if st.steering_connected:
                sc["center"] = round(st.steering_raw, 4)
                self.dirty = True
                self.notify("Centro del volante reajustado")
        elif k == pygame.K_m:
            self.engine.shifter.resync(self.engine.current_h_gear())
            self.notify("Marcha del juego sincronizada con la palanca")
        elif k == pygame.K_p:
            self.peak_deg = 0.0
        return True

    # -------------------------------------------------------------- dibujo --
    def draw_header(self):
        self.text("MOZA Bridge", (20, 14), ACCENT, self.f_big)
        self.text(f"Perfil: {self.cfg['profile_name']}" + ("  *sin guardar*" if self.dirty else ""),
                  (230, 22), YELLOW if self.dirty else MUTED)
        col = GREEN if self.output.active else YELLOW
        self.text(self.output.status, (W - 20 - self.f.size(self.output.status)[0], 22), col)
        y = 52
        if not self.devices.devices:
            self.text("No se detectan periféricos. Conectá la base/pedales.", (20, y), RED)
            return
        x = 20
        for d in self.devices.devices:
            s = f"{'[MOZA] ' if d.is_moza else ''}{d.name}  ({d.num_axes} ejes, {d.num_buttons} bot.)"
            r = self.text(s, (x, y), ACCENT if d.is_moza else MUTED, self.f_small)
            x = r.right + 24
            if x > W - 200:
                break

    def draw_wheel(self, st):
        rect = (20, 80, 380, 330)
        self.panel(rect, "Volante  [1]")
        cx, cy, r = 210, 235, 105
        sc = self.cfg["steering"]
        if not st.steering_connected:
            self.text("Sin asignar - presioná C", (cx, cy), MUTED, center=True)
            return
        # Límite de rotación del juego (arco)
        half = sc["game_rotation_deg"] / 2
        if half < 180:
            a0 = math.radians(90 - half)
            a1 = math.radians(90 + half)
            pygame.draw.arc(self.screen, (60, 64, 78),
                            (cx - r - 12, cy - r - 12, 2 * r + 24, 2 * r + 24), a0, a1, 6)
        pygame.draw.circle(self.screen, (70, 74, 88), (cx, cy), r, 10)
        ang = math.radians(st.steering_deg)
        for off, w in ((0, 6), (math.pi / 2, 4), (-math.pi / 2, 4)):
            ex = cx + math.sin(ang + off) * (r - 5)
            ey = cy - math.cos(ang + off) * (r - 5)
            pygame.draw.line(self.screen, TEXT if off else ACCENT, (cx, cy), (ex, ey), w)
        pygame.draw.circle(self.screen, PANEL, (cx, cy), 22)
        self.peak_deg = max(self.peak_deg, abs(st.steering_deg))
        self.text(f"{st.steering_deg:+.1f}°", (cx, cy), TEXT, self.f, center=True)
        self.text(f"máx: {self.peak_deg:.0f}°  (P reinicia)", (34, 112), MUTED, self.f_small)
        self.text(f"tope en juego: ±{half:.0f}°", (250, 112), MUTED, self.f_small)
        # Barra de salida
        bx, by, bw = 50, 370, 320
        pygame.draw.rect(self.screen, (50, 54, 66), (bx, by, bw, 16), border_radius=4)
        mid = bx + bw / 2
        end = mid + st.steering_out * bw / 2
        pygame.draw.rect(self.screen, ACCENT, (min(mid, end), by, abs(end - mid), 16), border_radius=4)
        pygame.draw.line(self.screen, TEXT, (mid, by - 3), (mid, by + 19), 2)
        self.text(f"Salida al juego: {st.steering_out * 100:+.0f}%", (cx, by - 14), TEXT,
                  self.f_small, center=True)
        self.text(f"Base: {sc['hardware_rotation_deg']:.0f}°  (cambiala en Ajustes del volante)",
                  (cx, by + 28), MUTED, self.f_small, center=True)

    def draw_pedals(self, st):
        rect = (410, 80, 360, 330)
        self.panel(rect, "Pedales y freno de mano  [2-5]")
        keys = list(self.cfg["pedals"].keys())
        colw = 340 // max(len(keys), 1)
        short = {"handbrake": "F. de mano"}
        for n, key in enumerate(keys):
            pc = self.cfg["pedals"][key]
            ps = st.pedals.get(key)
            x = 420 + n * colw
            cx = x + colw / 2
            col = PEDAL_COLORS.get(key, YELLOW)
            self.text(short.get(key, pc.get("label", key)), (cx, 120), TEXT, self.f_small, center=True)
            top, height, bw = 135, 225, 28 if len(keys) > 3 else 34
            bx1 = cx - bw - 3
            bx2 = cx + 3
            for bx in (bx1, bx2):
                pygame.draw.rect(self.screen, (50, 54, 66), (bx, top, bw, height), border_radius=5)
            if not ps or not ps.connected:
                self.text("-", (cx, top + height / 2), MUTED, self.f, center=True)
                continue
            # zona muerta / saturación como marcas
            for frac in (pc["deadzone"], pc["saturation"]):
                yy = top + height - frac * height
                pygame.draw.line(self.screen, MUTED, (bx1 - 3, yy), (bx1 + bw + 3, yy), 1)
            hpos = ps.position * height
            pygame.draw.rect(self.screen, (150, 155, 170),
                             (bx1, top + height - hpos, bw, hpos), border_radius=5)
            hout = ps.output * height
            pygame.draw.rect(self.screen, col, (bx2, top + height - hout, bw, hout), border_radius=5)
            self.text(f"{ps.position * 100:.0f}%", (bx1 + bw / 2, top + height + 12), MUTED,
                      self.f_small, center=True)
            if pc.get("output") == "button":
                yy = top + height - pc.get("threshold", 0.5) * height
                pygame.draw.line(self.screen, TEXT, (bx2 - 3, yy), (bx2 + bw + 3, yy), 2)
                on = pc.get("button", "A") in st.xbox_buttons
                self.text(pc.get("button", "A"), (bx2 + bw / 2, top + height + 12),
                          col if on else MUTED, self.f_small, center=True)
            else:
                self.text(f"{ps.output * 100:.0f}%", (bx2 + bw / 2, top + height + 12), col,
                          self.f_small, center=True)
        self.text("gris = recorrido real   color = lo que recibe el juego",
                  (590, 395), MUTED, self.f_small, center=True)

    def draw_shifter_info(self, st):
        sh = self.cfg["shifter"]
        gx, gy = 800, 118
        if not sh.get("gears"):
            self.text("Palanca H no detectada.", (gx, gy), MUTED)
            self.text("Presioná C para detectarla. Si la usás en modo", (gx, gy + 30), MUTED, self.f_small)
            self.text("secuencial, asignale Marcha arriba/abajo (RB/LB).", (gx, gy + 50), MUTED,
                      self.f_small)
            return
        g = st.shifter_gear
        self.text("Palanca", (gx + 50, gy + 4), MUTED, self.f_small, center=True)
        self.text(f"{g}ª" if g else "N", (gx + 50, gy + 50), ACCENT, self.f_big, center=True)
        self.text("Juego", (gx + 170, gy + 4), MUTED, self.f_small, center=True)
        gg = st.game_gear
        self.text(f"{gg}ª" if gg else "-", (gx + 170, gy + 50), TEXT, self.f_big, center=True)
        self.text(f"{len(sh['gears'])} marchas", (gx + 250, gy + 44), MUTED, self.f_small)
        lines = ["Al cambiar de marcha se mandan toques de",
                 f"{sh.get('up_button')} / {sh.get('down_button')} hasta llegar a la marcha puesta.",
                 "Si el juego se desfasa: poné la marcha que",
                 "tiene el juego y apretá M para sincronizar."]
        for i, line in enumerate(lines):
            self.text(line, (gx, gy + 80 + i * 18), MUTED, self.f_small)

    def draw_curve_and_params(self, st):
        rect = (780, 80, 380, 330)
        c = self.controls[self.sel_control]
        cfg, params = self.current_cfg()
        self.panel(rect, f"Ajustes: {self.control_label(c)}  [{self.sel_control + 1}]  (TAB cambia)")
        if c == "shifter":
            self.draw_shifter_info(st)
        else:
            self.draw_curve(st, c, cfg)
        # Lista de parámetros
        y = 410 - 10 - len(params) * 22
        for i, (key, lab, *_rest, fmt) in enumerate(params):
            v = cfg.get(key)
            if key == "output":
                v = OUTPUT_NAMES.get(v, v)
            elif key == "mode":
                v = MODE_NAMES.get(v, v)
            elif key == "invert":
                v = "Sí" if v else "No"
            sel = i == self.sel_param
            if sel:
                pygame.draw.rect(self.screen, (55, 60, 76), (790, y - 3, 360, 22), border_radius=4)
            self.text(lab, (800, y), TEXT if sel else MUTED, self.f_small)
            if sel and self.editing is not None:
                val = f"[ {self.editing}_ ]  ENTER"
                color = YELLOW
            else:
                val = ("< " if sel else "") + fmt.format(v) + (" >" if sel else "")
                color = ACCENT if sel else TEXT
            self.text(val, (1140 - self.f_small.size(val)[0], y), color, self.f_small)
            y += 22

    def draw_curve(self, st, c, cfg):
        gx, gy, gs = 800, 115, 120
        pygame.draw.rect(self.screen, (40, 44, 56), (gx, gy, gs, gs))
        pygame.draw.line(self.screen, (60, 64, 78), (gx, gy + gs), (gx + gs, gy), 1)
        pts = []
        for i in range(41):
            x = i / 40
            y = steering_curve_point(x, cfg) if c == "steering" else pedal_curve_point(x, cfg)
            pts.append((gx + x * gs, gy + gs - y * gs))
        col = ACCENT if c == "steering" else PEDAL_COLORS.get(c, YELLOW)
        pygame.draw.lines(self.screen, col, False, pts, 2)
        # Punto actual
        if c == "steering" and st.steering_connected:
            x = min(1.0, abs(st.steering_deg) / max(cfg["game_rotation_deg"] / 2, 1))
            y = abs(st.steering_out)
        elif c != "steering" and st.pedals.get(c) and st.pedals[c].connected:
            x, y = st.pedals[c].position, st.pedals[c].output
        else:
            x = y = None
        if x is not None:
            pygame.draw.circle(self.screen, TEXT, (gx + x * gs, gy + gs - y * gs), 5)
        self.text("entrada", (gx, gy + gs + 2), MUTED, self.f_small)
        self.text("salida", (gx + gs + 6, gy), MUTED, self.f_small)
        tip = ("Curva >1: más suave" if c != "steering"
               else "Curva >1: más precisa")
        self.text(tip, (gx + gs + 6, gy + 22), MUTED, self.f_small)
        self.text("Curva <1: más agresiva", (gx + gs + 6, gy + 40), MUTED, self.f_small)
        self.text("ENTER: escribir valor", (gx + gs + 6, gy + 70), MUTED, self.f_small)

    def draw_history(self, st):
        rect = (20, 420, 1140, 200)
        self.panel(rect, f"Reacción (últimos {HISTORY_SECONDS:.0f} s)")
        gx, gy, gw, gh = 40, 450, 1100, 150
        pygame.draw.rect(self.screen, (40, 44, 56), (gx, gy, gw, gh))
        pygame.draw.line(self.screen, (60, 64, 78), (gx, gy + gh / 2), (gx + gw, gy + gh / 2), 1)
        now = time.monotonic()
        if len(self.history) < 2:
            return
        series = [("steer", ACCENT, True)] + [(k, PEDAL_COLORS.get(k, YELLOW), False)
                                               for k in self.cfg["pedals"]]
        for key, col, centered in series:
            pts = []
            for t, vals in self.history:
                v = vals.get(key)
                if v is None:
                    continue
                x = gx + gw - (now - t) / HISTORY_SECONDS * gw
                y = gy + gh / 2 - v * gh / 2 if centered else gy + gh - v * gh
                pts.append((x, y))
            if len(pts) > 1:
                pygame.draw.lines(self.screen, col, False, pts, 2)
        lx = gx + 8
        for name, col in [("volante", ACCENT)] + [(self.cfg["pedals"][k].get("label", k),
                                                    PEDAL_COLORS.get(k, YELLOW))
                                                   for k in self.cfg["pedals"]]:
            r = self.text(name, (lx, gy + 4), col, self.f_small)
            lx = r.right + 16

    def draw_footer(self, st):
        btns = ", ".join(f"{i}" for _, i in st.raw_buttons) or "ninguno"
        xb = ", ".join(sorted(st.xbox_buttons)) or "-"
        gear = ""
        if self.cfg["shifter"].get("gears"):
            g = st.shifter_gear
            gear = f"    Palanca: {f'{g}ª' if g else 'N'}  (juego {st.game_gear or '-'}ª)"
        self.text(f"Botones apretados: {btns}    ->  Xbox: {xb}    "
                  f"LT {st.left_trigger * 100:.0f}%  RT {st.right_trigger * 100:.0f}%" + gear,
                  (20, 630), TEXT, self.f_small)
        self.text(f"TAB/1-{len(self.controls)}: control   Arriba/Abajo: parámetro   "
                  "Izq/Der: ajustar (Shift x5)   ENTER: escribir valor   G: guardar",
                  (20, 652), MUTED, self.f_small)
        self.text("C: detectar periféricos   R: recentrar volante   M: sincronizar marcha   "
                  "P: reiniciar máximo   ESC: salir", (20, 672), MUTED, self.f_small)
        msg, until = self.toast
        if msg and time.monotonic() < until:
            self.text(msg, (20, 696), YELLOW, self.f_small)

    def draw_calibration(self):
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))
        rect = (190, 140, 800, 420)
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=14)
        self.text("Detección automática de periféricos", (W / 2, 175), ACCENT, self.f_big, center=True)
        y = 230
        for i, line in enumerate(self.calib.instruction()):
            self.text(line, (W / 2, y), MUTED if i == 0 else TEXT,
                      self.f if i == 0 else self.f_big if i == 1 else self.f, center=True)
            y += 42 if i == 1 else 32
        if self.calib.error:
            self.text(self.calib.error, (W / 2, y + 10), RED, self.f, center=True)
        y = 420
        for line in self.calib.log[-4:]:
            self.text("OK  " + line, (230, y), GREEN, self.f_small)
            y += 22
        self.text("ESC cancela", (W / 2, 535), MUTED, self.f_small, center=True)

    # ---------------------------------------------------------------- loop --
    def run(self, max_frames: int | None = None):
        hz = max(60, int(self.cfg["output"].get("update_hz", 250)))
        clock = pygame.time.Clock()
        draw_every = max(1, hz // 60)
        frame = 0
        running = True
        try:
            while running:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        running = False
                    elif ev.type == pygame.KEYDOWN:
                        running = self.on_key(ev)
                    elif ev.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                        self.devices.rescan()
                        self.notify("Cambió la lista de periféricos")
                if self.calib:
                    self.calib.poll_buttons()
                    if self.calib.done:
                        self.finish_calibration()
                    st = self.engine.compute()
                    self.output.send(0.0, 0.0, 0.0, set())  # nada al juego mientras calibra
                else:
                    st = self.engine.tick()
                now = time.monotonic()
                vals = {"steer": st.steering_out if st.steering_connected else None}
                for k, p in st.pedals.items():
                    vals[k] = p.output if p.connected else None
                self.history.append((now, vals))
                while self.history and now - self.history[0][0] > HISTORY_SECONDS:
                    self.history.popleft()
                if frame % draw_every == 0:
                    self.screen.fill(BG)
                    self.draw_header()
                    self.draw_wheel(st)
                    self.draw_pedals(st)
                    self.draw_curve_and_params(st)
                    self.draw_history(st)
                    self.draw_footer(st)
                    if self.calib:
                        self.draw_calibration()
                    pygame.display.flip()
                frame += 1
                if max_frames is not None and frame >= max_frames:
                    break
                clock.tick(hz)
        finally:
            self.output.close()
            pygame.quit()
