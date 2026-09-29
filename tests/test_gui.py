"""Funktionstest der Oberflaeche ohne Klicks: Fenster aufbauen, Laeufe programmatisch starten,
Ereignisschleife pumpen, Ergebnis pruefen. Braucht ein Display (Windows/macOS/Linux mit X).

Aufruf aus dem Repo-Stammverzeichnis:  python tests/test_gui.py
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

T = ROOT / "test_tmp_gui"


def pump(app, timeout=120):
    t0 = time.time()
    while app.running and time.time() - t0 < timeout:
        app.update()
        time.sleep(0.02)
    app.update()
    assert not app.running, "Lauf nicht beendet"


def main():
    import nef2jpg
    import nef2jpg_gui
    from make_fake_nef import build_nef

    shutil.rmtree(T, ignore_errors=True)
    T.mkdir()
    for i in range(6):
        data, _ = build_nef(">", 6 if i % 2 else 1)
        (T / f"DSC_{i:04d}.NEF").write_bytes(data)
    (T / "kaputt.NEF").write_bytes(b"MM\0\x2a" + b"\xff" * 5000)
    nef2jpg_gui.settings_path = lambda: T / "settings.json"  # Einstellungen nicht im Benutzerprofil ablegen
    print("rawpy im Testinterpreter:", nef2jpg.rawpy is not None)

    app = nef2jpg_gui.App(str(T))
    app.update()
    print("Titel:", app.title())
    print("Ordner-Info:", app.lbl_folder_info.cget("text"))
    assert "7 NEF-Dateien" in app.lbl_folder_info.cget("text")

    print("\n-- Lauf 1: eingebettet, 2 Prozesse")
    app.var_mode.set("embedded")
    app.refresh_options()
    app.var_jobs.set(2)
    app.start()
    pump(app)
    log = app.log.get("1.0", "end")
    print("Status:", app.var_status.get())
    print("Fortschritt:", app.var_progress.get())
    assert app.counts == {"entwickelt": 0, "eingebettet": 6, "fehler": 1}, app.counts
    assert "300x400" in log and "400x300" in log and "FEHLER  kaputt.NEF" in log, log
    assert str(app.btn_start["state"]) == "normal" and str(app.btn_cancel["state"]) == "disabled"
    assert str(app.btn_open["state"]) == "normal"
    assert "6 davon schon als JPG vorhanden" in app.lbl_folder_info.cget("text")

    print("\n-- Lauf 2: entwickeln, alles vorhanden -> nichts zu tun")
    app.var_mode.set("develop")
    app.refresh_options()
    app.start()
    pump(app)
    assert app.total == 0 and "Nichts zu tun" in app.log.get("1.0", "end"), app.log.get("1.0", "end")
    print("Status:", app.var_status.get())

    print("\n-- Lauf 3: entwickeln + ueberschreiben -> LibRaw lehnt ab -> eingebettet + Hinweis")
    app.var_overwrite.set(True)
    app.start()
    pump(app)
    log = app.log.get("1.0", "end")
    print("Status:", app.var_status.get())
    print("LibRaw-Probleme:", app.libraw_problems)
    assert app.counts["eingebettet"] == 6 and app.libraw_problems and "Hinweis" in log, (app.counts, app.libraw_problems)

    print("\n-- Lauf 4: Abbrechen direkt nach Start")
    app.start()
    app.cancel()
    pump(app)
    print("Status:", app.var_status.get())
    assert app.var_status.get().startswith("Abgebrochen") and str(app.btn_start["state"]) == "normal"

    settings = T / "settings.json"
    print("\nEinstellungen gespeichert:", settings.exists())
    assert settings.exists()
    app.destroy()
    print("\nGUI-TEST OK")


if __name__ == "__main__":
    main()
