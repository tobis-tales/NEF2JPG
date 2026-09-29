#!/usr/bin/env python3
"""
NEF2JPG - grafische Oberfläche für nef2jpg.py.

Start:
    python nef2jpg_gui.py [Ordner]
    NEF2JPG.exe [Ordner]                     Ordner optional, z.B. per Drag & Drop auf die EXE
    NEF2JPG.exe --cli <Ordner> [Optionen]    Kommandozeilenmodus ohne Fenster (Optionen wie nef2jpg.py)
"""
from __future__ import annotations

import json
import multiprocessing
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import nef2jpg

APP_NAME = "NEF2JPG"
MAX_JOBS = max(1, os.cpu_count() or 1)
MODE_TEXT = {"develop": "Rohdaten entwickeln", "embedded": "eingebettetes Kamera-JPG"}


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME / "settings.json"


def resource_path(name: str) -> Path:
    """Datei neben dem Skript bzw. im entpackten PyInstaller-Bundle."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d} h"
    return f"{seconds // 60}:{seconds % 60:02d} min"


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class App(tk.Tk):
    def __init__(self, folder: str | None = None) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {nef2jpg.__version__}  -  NEF nach JPG")
        self.geometry("780x620")
        self.minsize(680, 540)
        try:
            self.iconbitmap(str(resource_path("app.ico")))
        except Exception:
            pass  # kein Icon unter macOS/Linux oder Datei fehlt

        self.settings = self.load_settings()
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.pool: ProcessPoolExecutor | None = None
        self.cancel_event = threading.Event()
        self.running = False
        self.total = 0
        self.done = 0
        self.started_at = 0.0
        self.counts = {"entwickelt": 0, "eingebettet": 0, "fehler": 0}
        self.libraw_problems: dict[str, int] = {}
        self.errors: list[str] = []
        self.out_dir: Path | None = None

        self.var_folder = tk.StringVar(value=folder or str(self.settings.get("folder", "")))
        mode = self.settings.get("mode", "develop")
        self.var_mode = tk.StringVar(value=mode if mode in MODE_TEXT else "develop")
        self.var_quality = tk.IntVar(value=max(1, min(100, _int(self.settings.get("quality"), 92))))
        self.var_overwrite = tk.BooleanVar(value=bool(self.settings.get("overwrite", False)))
        self.var_jobs = tk.IntVar(value=max(1, min(MAX_JOBS, _int(self.settings.get("jobs"), min(MAX_JOBS, 8)))))
        self.var_status = tk.StringVar(value="Ordner mit NEF-Dateien auswählen und Start drücken.")
        self.var_progress = tk.StringVar(value="")

        self.build_ui()
        self.var_folder.trace_add("write", lambda *_: self.refresh_folder_info())
        self.refresh_folder_info()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ Aufbau
    def build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Ordner:").grid(row=0, column=0, sticky="w", **pad)
        self.ent_folder = ttk.Entry(frm, textvariable=self.var_folder)
        self.ent_folder.grid(row=0, column=1, sticky="ew", **pad)
        self.btn_browse = ttk.Button(frm, text="Durchsuchen …", command=self.choose_folder)
        self.btn_browse.grid(row=0, column=2, **pad)
        self.lbl_folder_info = ttk.Label(frm, text="", foreground="gray40")
        self.lbl_folder_info.grid(row=1, column=1, columnspan=2, sticky="w", padx=10)

        opt = ttk.LabelFrame(frm, text="Optionen", padding=8)
        opt.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        opt.columnconfigure(3, weight=1)
        self.rb_develop = ttk.Radiobutton(
            opt, text="Rohdaten entwickeln (LibRaw, neutraler Look, Qualität wählbar)",
            variable=self.var_mode, value="develop", command=self.refresh_options)
        self.rb_embedded = ttk.Radiobutton(
            opt, text="Eingebettetes Kamera-JPG übernehmen (sehr schnell, Kamera-Look, auch HE/HE*)",
            variable=self.var_mode, value="embedded", command=self.refresh_options)
        self.rb_develop.grid(row=0, column=0, columnspan=4, sticky="w")
        self.rb_embedded.grid(row=1, column=0, columnspan=4, sticky="w")
        ttk.Label(opt, text="JPG-Qualität:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.spn_quality = ttk.Spinbox(opt, from_=50, to=100, width=5, textvariable=self.var_quality)
        self.spn_quality.grid(row=2, column=1, sticky="w", pady=(8, 0), padx=(4, 20))
        ttk.Label(opt, text="Parallele Prozesse:").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.spn_jobs = ttk.Spinbox(opt, from_=1, to=MAX_JOBS, width=5, textvariable=self.var_jobs)
        self.spn_jobs.grid(row=2, column=3, sticky="w", pady=(8, 0), padx=4)
        self.chk_overwrite = ttk.Checkbutton(
            opt, text="Vorhandene JPGs überschreiben", variable=self.var_overwrite,
            command=self.refresh_folder_info)
        self.chk_overwrite.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
        self.btn_start = ttk.Button(btns, text="Start", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(btns, text="Abbrechen", command=self.cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=6)
        self.btn_open = ttk.Button(btns, text="JPG-Ordner öffnen", command=self.open_output, state="disabled")
        self.btn_open.pack(side="right")

        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frm, textvariable=self.var_progress).grid(row=5, column=0, columnspan=3, sticky="w", padx=10)

        mono = "Consolas" if sys.platform == "win32" else "Menlo"
        self.log = scrolledtext.ScrolledText(frm, height=14, state="disabled", wrap="none", font=(mono, 10))
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)
        self.log.tag_configure("fehler", foreground="#b00020")
        self.log.tag_configure("hinweis", foreground="#8a5a00")
        frm.rowconfigure(6, weight=1)

        ttk.Label(frm, textvariable=self.var_status, relief="sunken", anchor="w", padding=(6, 3)).grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=(4, 0))
        self.refresh_options()

    # ------------------------------------------------------------ Einstellungen
    @staticmethod
    def load_settings() -> dict:
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def save_settings(self) -> None:
        data = {"folder": self.var_folder.get(), "mode": self.var_mode.get(), "quality": self.var_quality.get(),
                "overwrite": self.var_overwrite.get(), "jobs": self.var_jobs.get()}
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------ Helfer
    def current_folder(self) -> Path | None:
        text = self.var_folder.get().strip().strip('"')
        if not text:
            return None
        path = Path(text)
        return path if path.is_dir() else None

    def refresh_folder_info(self) -> None:
        folder = self.current_folder()
        if folder is None:
            self.lbl_folder_info.config(text="")
            return
        try:
            nefs = nef2jpg.find_nefs(folder)
        except OSError:
            self.lbl_folder_info.config(text="Ordner nicht lesbar")
            return
        out_dir = folder / "JPG"
        existing = sum(1 for nef in nefs if (out_dir / (nef.stem + ".jpg")).exists())
        text = f"{len(nefs)} NEF-Dateien gefunden"
        if existing:
            text += f", {existing} davon schon als JPG vorhanden"
            text += "" if self.var_overwrite.get() else " (werden übersprungen)"
        self.lbl_folder_info.config(text=text)

    def refresh_options(self) -> None:
        develop = self.var_mode.get() == "develop"
        self.spn_quality.config(state="normal" if develop and not self.running else "disabled")

    def read_options(self) -> tuple[int, int] | None:
        try:
            quality, jobs = int(self.var_quality.get()), int(self.var_jobs.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning(APP_NAME, "Qualität und parallele Prozesse müssen ganze Zahlen sein.")
            return None
        quality, jobs = max(1, min(100, quality)), max(1, min(MAX_JOBS, jobs))
        self.var_quality.set(quality)
        self.var_jobs.set(jobs)
        return quality, jobs

    def log_line(self, text: str, tag: str = "") -> None:
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", (tag,) if tag else ())
        self.log.see("end")
        self.log.config(state="disabled")

    def clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        for widget in (self.ent_folder, self.btn_browse, self.rb_develop, self.rb_embedded,
                       self.spn_jobs, self.chk_overwrite, self.btn_start):
            widget.config(state=state)
        self.btn_cancel.config(state="normal" if running else "disabled")
        if running:
            self.btn_open.config(state="disabled")
        self.refresh_options()

    # ---------------------------------------------------------------- Aktionen
    def choose_folder(self) -> None:
        start = self.var_folder.get().strip().strip('"')
        chosen = filedialog.askdirectory(title="Ordner mit NEF-Dateien auswählen",
                                         initialdir=start if start and Path(start).is_dir() else None,
                                         mustexist=True)
        if chosen:
            self.var_folder.set(chosen)

    def start(self) -> None:
        if self.running:
            return
        folder = self.current_folder()
        if folder is None:
            messagebox.showwarning(APP_NAME, "Bitte einen vorhandenen Ordner auswählen.")
            return
        options = self.read_options()
        if options is None:
            return
        quality, jobs_n = options
        embedded = self.var_mode.get() == "embedded"
        jobs, skipped, nefs = nef2jpg.collect_jobs(folder, quality, embedded, self.var_overwrite.get())
        if not nefs:
            messagebox.showinfo(APP_NAME, f"Keine .NEF-Dateien in\n{folder}")
            return
        self.out_dir = folder / "JPG"
        try:
            self.out_dir.mkdir(exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Der Unterordner JPG kann nicht angelegt werden:\n{exc}")
            return
        self.save_settings()

        self.total, self.done = len(jobs), 0
        self.counts = {"entwickelt": 0, "eingebettet": 0, "fehler": 0}
        self.libraw_problems, self.errors = {}, []
        self.cancel_event.clear()
        self.progress.config(maximum=max(1, self.total), value=0)
        self.clear_log()
        self.log_line(f"{len(nefs)} NEF-Dateien in {folder}")
        self.log_line(f"Ziel: {self.out_dir}   Modus: {MODE_TEXT[self.var_mode.get()]}   "
                      f"{jobs_n} parallele Prozesse   {skipped} übersprungen")
        self.log_line("")
        self.started_at = time.perf_counter()
        if not jobs:
            self.log_line("Nichts zu tun, alle JPGs sind schon vorhanden. "
                          "Zum Neuberechnen 'Vorhandene JPGs überschreiben' anhaken.", "hinweis")
            self.finish()
            return
        self.set_running(True)
        self.worker = threading.Thread(target=self.run_jobs, args=(jobs, jobs_n), daemon=True)
        self.worker.start()
        self.after(100, self.poll)

    def run_jobs(self, jobs: list, jobs_n: int) -> None:
        """Hintergrund-Thread: verteilt die Auftraege auf Prozesse und meldet Ergebnisse ueber die Queue."""
        try:
            with ProcessPoolExecutor(max_workers=jobs_n) as pool:
                self.pool = pool
                if self.cancel_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                futures = [pool.submit(nef2jpg.convert_one, job) for job in jobs]
                for fut in as_completed(futures):
                    if not fut.cancelled():
                        self.queue.put(("result", fut.result()))
        except Exception as exc:
            self.queue.put(("error", nef2jpg.error_text(exc)))
        finally:
            self.pool = None
            self.queue.put(("done", None))

    def cancel(self) -> None:
        if not self.running:
            return
        self.cancel_event.set()
        self.btn_cancel.config(state="disabled")
        self.var_status.set("Abbruch, laufende Bilder werden noch fertiggestellt …")
        pool = self.pool
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "result":
                    self.handle_result(payload)
                elif kind == "error":
                    self.errors.append(payload)
                    self.log_line(f"FEHLER  {payload}", "fehler")
                elif kind == "done":
                    self.finish()
                    return
        except queue.Empty:
            pass
        self.update_progress_text()
        self.after(100, self.poll)

    def handle_result(self, result: tuple[str, str, str, str]) -> None:
        name, kind, detail, libraw_problem = result
        self.done += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if libraw_problem and kind == "eingebettet":
            self.libraw_problems[libraw_problem] = self.libraw_problems.get(libraw_problem, 0) + 1
        if kind == "fehler":
            self.errors.append(f"{name}: {detail}")
            self.log_line(f"FEHLER  {name}: {detail}", "fehler")
        elif kind == "eingebettet":
            self.log_line(f"ok      {name}   (eingebettetes Kamera-JPG, {detail})")
        else:
            self.log_line(f"ok      {name}")
        self.progress["value"] = self.done

    def update_progress_text(self) -> None:
        if not self.running:
            return
        elapsed = time.perf_counter() - self.started_at
        text = f"{self.done} / {self.total}"
        if self.done:
            per_image = elapsed / self.done
            text += f"   {per_image:.1f} s pro Bild   Rest ca. {format_duration(per_image * (self.total - self.done))}"
        self.var_progress.set(text)
        if not self.cancel_event.is_set():
            self.var_status.set(f"Konvertiere … {self.done} von {self.total}")

    def finish(self) -> None:
        elapsed = time.perf_counter() - self.started_at if self.started_at else 0.0
        self.set_running(False)
        summary = (f"{self.counts['entwickelt']} entwickelt, {self.counts['eingebettet']} eingebettetes Kamera-JPG, "
                   f"{self.counts['fehler']} Fehler, {format_duration(elapsed)}")
        if self.cancel_event.is_set():
            summary = "Abgebrochen: " + summary
        self.log_line("")
        self.log_line(summary, "fehler" if self.counts["fehler"] else "")
        for problem, n in self.libraw_problems.items():
            self.log_line(f"Hinweis: {n} {'Datei' if n == 1 else 'Dateien'} konnte LibRaw nicht entwickeln ({problem}).", "hinweis")
            self.log_line("Das ist typisch für NEFs im HE/HE*-Format. "
                          "Dafür wurde das eingebettete Kamera-JPG übernommen.", "hinweis")
        self.var_status.set(summary)
        self.var_progress.set(f"{self.done} / {self.total}")
        self.btn_open.config(state="normal" if self.out_dir and self.out_dir.is_dir() else "disabled")
        self.refresh_folder_info()

    def open_output(self) -> None:
        if not self.out_dir:
            return
        path = str(self.out_dir)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Ordner kann nicht geöffnet werden:\n{exc}")

    def on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(APP_NAME, "Die Konvertierung läuft noch. Wirklich beenden?"):
                return
            self.cancel()
        self.destroy()


def main(argv: list[str]) -> int:
    if "--cli" in argv:
        sys.argv = [sys.argv[0], *(a for a in argv if a != "--cli")]
        return nef2jpg.main()
    folder = argv[0] if argv and Path(argv[0]).is_dir() else None
    App(folder).mainloop()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # Pflicht für eine PyInstaller-EXE mit Prozess-Pool
    for stream in ("stdout", "stderr"):  # ohne Konsole (--windowed) sind die Streams None
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, "w"))
    sys.exit(main(sys.argv[1:]))
