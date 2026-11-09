"""Punto de entrada: ``python -m moza_bridge [opciones]``."""

from __future__ import annotations

import argparse
import os
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="moza_bridge",
        description="Lee el volante y pedales MOZA y los convierte en un mando "
                    "Xbox 360 virtual con sensibilidad configurable.")
    ap.add_argument("--perfil", default="general",
                    help="perfil a usar (nombre en ./perfiles o ruta a .json). Ej: nfs_heat")
    ap.add_argument("--listar", action="store_true",
                    help="muestra los periféricos detectados y sale (para diagnóstico)")
    ap.add_argument("--sin-salida", action="store_true",
                    help="sólo monitor: no crea el mando virtual")
    ap.add_argument("--demo", action="store_true",
                    help="simula un volante y pedales (para probar sin hardware)")
    args = ap.parse_args(argv)

    # Que SDL lea los periféricos aunque la ventana no tenga el foco
    # (necesario mientras jugás con el juego en primer plano).
    os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    import pygame

    from .config import load_profile
    from .devices import DeviceManager, describe_devices
    from .output import create_output

    cfg, path = load_profile(args.perfil)

    if args.listar:
        pygame.display.init()
        pygame.joystick.init()
        pygame.event.pump()
        mgr = DeviceManager(cfg, demo=args.demo)
        time.sleep(0.3)
        pygame.event.pump()
        print("=== Periféricos detectados ===")
        print(describe_devices(mgr))
        print("\nCopiá este texto y compartilo si algo no se detecta bien.")
        pygame.quit()
        return 0

    if args.demo:
        cfg = _demo_config(cfg)

    from .gui import App

    pygame.display.init()
    pygame.joystick.init()
    mgr = DeviceManager(cfg, demo=args.demo)
    out = create_output(cfg["output"].get("enabled", True) and not args.sin_salida)
    print(f"Perfil: {path}")
    print(out.status)
    App(cfg, path, mgr, out).run()
    return 0


def _demo_config(cfg: dict) -> dict:
    base = "030000006e3400000500000000000000"
    ped = "030000006e3400000300000000000000"
    cfg["steering"]["axis"] = {"device": base, "name": "MOZA R5 Base (DEMO)", "index": 0}
    cfg["steering"]["hardware_rotation_deg"] = 900
    for i, k in enumerate(("throttle", "brake", "clutch")):
        cfg["pedals"][k].update(axis={"device": ped, "name": "MOZA SR-P Pedals (DEMO)", "index": i},
                                rest=-1.0, full=1.0)
    cfg["profile_name"] += " (DEMO)"
    return cfg


if __name__ == "__main__":
    sys.exit(main())
