# CEWE MCF to PDF

Converts a CEWE photo book project (`.mcf`) into a PDF, with photos cropped as in the book and all text boxes.

- Cover and double-page spreads, or single pages
- Choose image quality: 300 dpi (print quality), 200 or 150 dpi (smaller file)
- Small GUI, plus a command line
- Stand-alone programs for Windows and Linux: no Python or CEWE software needed

**Limitation:** CEWE's built-in background designs and clip-arts ship with the CEWE software, not in the `.mcf` project, so backgrounds are rendered white.

The `.mcf` file must sit next to its image folder (`<name>_mcf-Dateien`), as CEWE saves it.

## Download

Get the latest version from the [Releases](../../releases/latest) page:

| System | File | How to start |
|---|---|---|
| Windows 10/11 (64-bit) | `MCF2PDF-windows-x64.exe` | Double-click it, or drag an `.mcf` file onto it. If SmartScreen warns, click *More info → Run anyway* (the program is not code-signed). |
| Linux (x86-64, glibc 2.36+, e.g. Debian 12, Ubuntu 22.04+, Fedora 37+) | `mcf2pdf-linux-x64` | `chmod +x mcf2pdf-linux-x64 && ./mcf2pdf-linux-x64` |

Then choose the `.mcf` file and click **Convert to PDF**.

## Run from source

```
pip install -r requirements.txt
python3 mcf2pdf_gui.py                                        # GUI
python3 mcf2pdf.py book.mcf [out.pdf] [--dpi 200] [--single]   # command line
```

## Build the stand-alone programs

- Windows: install Python from python.org, then run `build_windows.bat` → `dist\MCF2PDF.exe`
- Linux: `./build_linux.sh` → `dist/mcf2pdf`

## Files

- `mcf2pdf.py`: converter (library + command line)
- `mcf2pdf_gui.py`: GUI (tkinter)
- `fonts/`: Liberation Sans (same letter widths as Arial, SIL Open Font License), bundled into the programs

## License

MIT. See [LICENSE](LICENSE). The bundled fonts use the SIL Open Font License.
