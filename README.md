# NEF2JPG

Wandelt einen Ordner Nikon-Rohdateien (`.NEF`) in JPGs um. Die JPGs landen im
Unterordner `JPG` des gewählten Ordners und behalten den Dateinamen
(`DSC_0001.NEF` → `JPG\DSC_0001.jpg`). Aufnahmedaten wie Kamera, Objektiv,
Datum, Belichtung und GPS werden als EXIF übernommen.

## Download

Fertige Windows-Programme liegen unter **[Releases](https://github.com/tobis-tales/NEF2JPG/releases/latest)**:

| Datei | Zweck |
|---|---|
| `NEF2JPG.exe` | Programm mit Oberfläche: Ordner wählen, Optionen setzen, Start |
| `nef2jpg-cli.exe` | Kommandozeilenversion für Skripte und Stapelverarbeitung |

Beide laufen auf 64-Bit-Windows ohne weitere Installation. Beim ersten Start
meldet Windows SmartScreen eventuell „Der Computer wurde durch Windows
geschützt“, weil die EXE nicht signiert ist: „Weitere Informationen“ und dann
„Trotzdem ausführen“ klicken. Der Start dauert ein paar Sekunden, weil sich die
EXE beim Start entpackt.

## Benutzung

**Oberfläche:** `NEF2JPG.exe` starten, Ordner wählen oder einen Ordner auf die
EXE ziehen, Optionen setzen, Start. Der Fortschritt läuft mit, Fehler werden
rot markiert, „Abbrechen“ beendet den Lauf nach den gerade laufenden Bildern.
Die zuletzt benutzten Einstellungen werden gemerkt.

**Kommandozeile:**

```
nef2jpg-cli.exe "D:\Fotos\Urlaub"                Ordner konvertieren
nef2jpg-cli.exe "D:\Fotos\Urlaub" --embedded     eingebettetes Kamera-JPG nehmen
nef2jpg-cli.exe "D:\Fotos\Urlaub" --quality 95   JPG-Qualität 1-100, Standard 92
nef2jpg-cli.exe "D:\Fotos\Urlaub" --overwrite    vorhandene JPGs überschreiben
nef2jpg-cli.exe "D:\Fotos\Urlaub" --jobs 4       Anzahl paralleler Prozesse
```

Ohne Ordnerangabe öffnet die Kommandozeilenversion einen Auswahldialog.
Bereits vorhandene JPGs werden übersprungen, wenn `--overwrite` fehlt.

## Zwei Wege zum JPG

**Rohdaten entwickeln (Standard):** Die Rohdaten werden mit der freien
Bibliothek [LibRaw](https://www.libraw.org/) komplett entwickelt, mit
Kamera-Weißabgleich in sRGB. Neutraler Look, Qualität wählbar.
Richtwert: 1 bis 3 Sekunden pro 24-Megapixel-Bild und Prozessorkern.

**Eingebettetes Kamera-JPG:** Jede NEF enthält bereits ein fertiges JPG der
Kamera, mit Picture Control, Schärfung und allen Kameraeinstellungen. Dieses
JPG wird direkt herausgelöst, ohne Neuberechnung und ohne Qualitätsverlust,
Hochformat wird korrekt gedreht. Bei neueren Nikon-Kameras hat es die volle
Auflösung, bei älteren nur eine kleinere Vorschau. Die Pixelmaße stehen im
Protokoll hinter jeder Datei. Dieser Weg dauert nur Sekundenbruchteile pro Bild.

**Automatik bei HE/HE*:** NEFs im Format „High Efficiency“ (HE oder HE*), das
zum Beispiel Z8, Z9, Z6III, Zf, Z5II und Z50II schreiben, kann LibRaw nicht
lesen. Meldet LibRaw „Unsupported file format or not RAW file“, nimmt das
Programm von selbst das eingebettete Kamera-JPG und weist im Protokoll darauf
hin. Wer für diese Kameras eine echte Rohentwicklung braucht, stellt die Kamera
auf „Verlustfrei komprimiert“ oder nutzt Nikon NX Studio.

## Selbst bauen

Voraussetzung: Python 3.10 bis 3.14 von [python.org](https://www.python.org/downloads/windows/),
im Installer „Add python.exe to PATH“ anhaken.

- **Windows:** Repo herunterladen und entpacken (oder klonen), Doppelklick auf
  `build.bat`. Das Skript legt eine eigene Umgebung im Unterordner `.venv` an,
  installiert `rawpy`, `Pillow` und `PyInstaller` und baut beide EXEs.
- **GitHub Actions:** Jeder Push auf `main` baut und testet die EXEs auf einem
  Windows-Runner (Artefakt `NEF2JPG-windows`). Ein Tag `v*` erzeugt zusätzlich
  ein Release mit den EXEs.
- **Direkt mit Python** (auch macOS/Linux): `pip install -r requirements.txt`,
  dann `python nef2jpg_gui.py` oder `python nef2jpg.py <Ordner>`.

## Dateien

| Datei | Inhalt |
|---|---|
| `nef2jpg.py` | Kern: Konvertierung, Kommandozeile, NEF-Struktur lesen, EXIF übernehmen |
| `nef2jpg_gui.py` | Oberfläche (tkinter), nutzt den Kern |
| `smoke_test.py` | Prüfung der erzeugten JPGs im CI-Build |
| `make_icon.py` | erzeugt `app.ico` |
| `build.bat` | lokaler Windows-Build |
| `.github/workflows/build.yml` | Cloud-Build, Test und Release |

## Hinweise

- Manche Virenscanner stufen mit PyInstaller gebaute Programme fälschlich als
  verdächtig ein. In dem Fall die Datei im Virenscanner freigeben.
- Die Nikon-MakerNote wird nicht ins JPG übernommen, sie ist dafür zu groß.
  Alle Standard-EXIF-Felder bleiben erhalten.
- Beim Entwickeln werden bis zu 8 Prozesse parallel gestartet; jeder braucht
  bei 45-Megapixel-Dateien einige hundert MB Arbeitsspeicher. Bei knappem
  Speicher die Anzahl der Prozesse verringern.
