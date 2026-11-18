#!/usr/bin/env python3
"""Small GUI for mcf2pdf: pick a CEWE photo book (.mcf), get a PDF."""
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import mcf2pdf

QUALITY = {"High (300 dpi)": 300, "Medium (200 dpi)": 200, "Small (150 dpi)": 150}


class App(tk.Tk):
    def __init__(self, initial=None):
        super().__init__()
        self.title("MCF to PDF")
        self.minsize(560, 340)
        self.q = queue.Queue()
        self.worker = None
        self.cancel_flag = threading.Event()

        self.mcf = tk.StringVar()
        self.out = tk.StringVar()
        self.quality = tk.StringVar(value=next(iter(QUALITY)))
        self.single = tk.BooleanVar(value=False)
        self.open_after = tk.BooleanVar(value=True)
        self.backgrounds = tk.BooleanVar(value=True)
        self.page_numbers = tk.BooleanVar(value=True)

        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Photo book (.mcf):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.mcf).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Browse…", command=self.pick_mcf).grid(row=0, column=2)

        ttk.Label(f, text="Save PDF as:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=self.out).grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(f, text="Browse…", command=self.pick_out).grid(row=1, column=2, pady=(6, 0))

        opts = ttk.Frame(f)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=10)
        ttk.Label(opts, text="Image quality:").pack(side="left")
        ttk.Combobox(opts, textvariable=self.quality, values=list(QUALITY), state="readonly",
                     width=16).pack(side="left", padx=(6, 16))
        ttk.Checkbutton(opts, text="Single pages (split spreads)", variable=self.single).pack(side="left")
        ttk.Checkbutton(opts, text="Open PDF when done", variable=self.open_after).pack(side="left", padx=(16, 0))
        opts2 = ttk.Frame(f)
        opts2.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Checkbutton(opts2, text="Page numbers", variable=self.page_numbers).pack(side="left")
        ttk.Checkbutton(opts2, text="Background colours (approximation of CEWE designs)",
                        variable=self.backgrounds).pack(side="left", padx=(16, 0))

        self.bar = ttk.Progressbar(f, mode="determinate")
        self.bar.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.status = ttk.Label(f, text="Choose an .mcf file to start.")
        self.status.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 6))

        self.log = tk.Text(f, height=6, state="disabled", wrap="word")
        self.log.grid(row=6, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(6, weight=1)

        btns = ttk.Frame(f)
        btns.grid(row=7, column=0, columnspan=3, sticky="e", pady=(10, 0))
        self.go = ttk.Button(btns, text="Convert to PDF", command=self.start)
        self.go.pack(side="left")
        self.stop = ttk.Button(btns, text="Cancel", command=self.cancel_flag.set, state="disabled")
        self.stop.pack(side="left", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if initial:
            self.set_mcf(initial)
        self.after(100, self.poll)

    # --- file pickers -------------------------------------------------------
    def set_mcf(self, path):
        path = os.path.abspath(path)
        self.mcf.set(path)
        self.out.set(os.path.splitext(path)[0] + ".pdf")
        self.status.config(text="Ready.")

    def pick_mcf(self):
        p = filedialog.askopenfilename(title="Choose photo book",
                                       filetypes=[("CEWE photo book", "*.mcf"), ("All files", "*.*")])
        if p:
            self.set_mcf(os.path.normpath(p))

    def pick_out(self):
        start = self.out.get() or self.mcf.get()
        p = filedialog.asksaveasfilename(title="Save PDF as", defaultextension=".pdf",
                                         initialdir=os.path.dirname(start) or None,
                                         initialfile=os.path.basename(start) if start else "",
                                         filetypes=[("PDF", "*.pdf")])
        if p:
            self.out.set(os.path.normpath(p))

    # --- conversion ---------------------------------------------------------
    def write_log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def start(self):
        mcf, out = self.mcf.get().strip(), self.out.get().strip()
        if not mcf or not os.path.isfile(mcf):
            messagebox.showerror("MCF to PDF", "Please choose an existing .mcf file.")
            return
        if not out:
            out = os.path.splitext(mcf)[0] + ".pdf"
            self.out.set(out)
        if os.path.exists(out) and not messagebox.askyesno("MCF to PDF", f"{os.path.basename(out)} already exists.\nReplace it?"):
            return
        self.cancel_flag.clear()
        self.go.config(state="disabled")
        self.stop.config(state="normal")
        self.bar.config(value=0, maximum=1)
        self.write_log(f"Converting {os.path.basename(mcf)} …")
        args = (mcf, out, QUALITY[self.quality.get()], self.single.get(),
                self.backgrounds.get(), self.page_numbers.get())
        self.worker = threading.Thread(target=self.run, args=args, daemon=True)
        self.worker.start()

    def run(self, mcf, out, dpi, single, backgrounds, page_numbers):
        try:
            res = mcf2pdf.convert(mcf, out, dpi, single,
                                  progress=lambda d, t, l: self.q.put(("progress", d, t, l)),
                                  warn=lambda m: self.q.put(("warn", m)),
                                  cancel=self.cancel_flag.is_set,
                                  backgrounds=backgrounds, page_numbers=page_numbers)
            self.q.put(("done", res))
        except mcf2pdf.Cancelled:
            self.q.put(("cancelled",))
        except Exception as e:
            self.q.put(("error", f"{e}\n\n{traceback.format_exc()}"))

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, d, t, label = msg
                    self.bar.config(maximum=t, value=d)
                    self.status.config(text=f"{label}  ({d} of {t})")
                elif kind == "warn":
                    self.write_log("Warning: " + msg[1])
                else:
                    self.go.config(state="normal")
                    self.stop.config(state="disabled")
                    if kind == "done":
                        size = os.path.getsize(msg[1]) / 1e6
                        self.status.config(text=f"Done: {msg[1]} ({size:.0f} MB)")
                        self.write_log(f"Saved {msg[1]}")
                        if self.open_after.get():
                            open_file(msg[1])
                    elif kind == "cancelled":
                        self.status.config(text="Cancelled.")
                        self.write_log("Cancelled.")
                    else:
                        self.status.config(text="Failed.")
                        self.write_log(msg[1])
                        messagebox.showerror("MCF to PDF", msg[1].split("\n\n")[0])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("MCF to PDF", "A conversion is running. Stop it and quit?"):
                return
            self.cancel_flag.set()
        self.destroy()


def open_file(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess; subprocess.Popen(["open", path])
        else:
            import subprocess; subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


if __name__ == "__main__":
    # allows dragging an .mcf onto the .exe
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
