# ============================================================
# gui.py — Simple desktop window for non-technical users
# ============================================================
"""A minimal Tkinter front-end so a non-coder can run the scraper without the
terminal: pick the input CSV, set an optional row range and proxy, click Start,
watch progress, and have results.xlsx open automatically when it finishes.

Launch with:  python -m web_crawler.gui   (or the run_gui.bat shortcut)

It reuses the exact run pipeline from cli._run (which dedupes and exports the
xlsx at the end), so the GUI and command line behave identically.
"""

import asyncio
import json
import logging
import os
import queue
import threading

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from web_crawler import chrome
from web_crawler.cli import RunControl, _run
from web_crawler.config import DEFAULTS, load_settings

logger = logging.getLogger(__name__)

# Sentinel pushed onto the log queue when the worker thread finishes.
_DONE = "__SCRAPE_DONE__"

# Where the GUI remembers the last-entered values (proxy, rows, etc.) so the
# user doesn't have to retype them each launch. Sits next to the project files.
_PREFS_FILE = os.path.join(os.path.dirname(DEFAULTS.input_csv), ".gui_prefs.json")


class _QueueLogHandler(logging.Handler):
    """Logging handler that forwards formatted records to a thread-safe queue
    the GUI drains on the main thread (Tk widgets aren't thread-safe)."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            pass


class ScraperGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_output_csv: str | None = None
        self.prefs: dict = self._load_prefs()
        self.control: RunControl | None = None
        self.paused: bool = False

        root.title("TruePeopleSearch Scraper")
        root.geometry("760x560")
        root.minsize(680, 480)

        self._build_form()
        self._build_log()
        self._configure_logging()
        self.root.after(150, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Layout ──────────────────────────────────────────────
    def _build_form(self):
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="x")
        frm.columnconfigure(1, weight=1)

        p = self.prefs

        # Input CSV
        ttk.Label(frm, text="Input CSV:").grid(row=0, column=0, sticky="w", pady=4)
        self.input_var = tk.StringVar(value=p.get("input_csv") or DEFAULTS.input_csv)
        ttk.Entry(frm, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Browse…", command=self._browse).grid(row=0, column=2)

        # Row range
        rng = ttk.Frame(frm)
        rng.grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(rng, text="Rows  start:").pack(side="left")
        self.start_var = tk.StringVar(value=p.get("start", ""))
        ttk.Entry(rng, textvariable=self.start_var, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(rng, text="end:").pack(side="left")
        self.end_var = tk.StringVar(value=p.get("end", ""))
        ttk.Entry(rng, textvariable=self.end_var, width=8).pack(side="left", padx=4)
        ttk.Label(rng, text="(leave blank = all rows)").pack(side="left", padx=8)

        # Proxy (required for this deployment)
        ttk.Label(frm, text="Proxy (host:port):").grid(row=2, column=0, sticky="w", pady=4)
        self.proxy_var = tk.StringVar(
            value=p.get("proxy") or os.environ.get("WEB_CRAWLER_PROXY_SERVER", ""))
        ttk.Entry(frm, textvariable=self.proxy_var).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Label(frm, text="(IP-whitelist auth)").grid(row=2, column=3, sticky="w")

        # Chrome profile (must have the NopeCHA extension)
        ttk.Label(frm, text="Chrome profile:").grid(row=3, column=0, sticky="w", pady=4)
        self.profile_var = tk.StringVar(value=p.get("profile") or DEFAULTS.profile_dir)
        ttk.Entry(frm, textvariable=self.profile_var, width=18).grid(row=3, column=1, sticky="w", padx=6)

        # Options
        opts = ttk.Frame(frm)
        opts.grid(row=4, column=0, columnspan=3, sticky="w", pady=4)
        self.resume_var = tk.BooleanVar(value=p.get("resume", True))
        ttk.Checkbutton(opts, text="Resume (skip rows already done)",
                        variable=self.resume_var).pack(side="left")
        self.retry_failed_var = tk.BooleanVar(value=p.get("retry_failed", False))
        ttk.Checkbutton(opts, text="Retry previously failed rows",
                        variable=self.retry_failed_var).pack(side="left", padx=16)

        # Actions
        actions = ttk.Frame(frm)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.start_btn = ttk.Button(actions, text="Start scraping", command=self._on_start)
        self.start_btn.pack(side="left")
        self.pause_btn = ttk.Button(actions, text="Pause", command=self._on_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(actions, text="Stop", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left")
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(actions, textvariable=self.status_var).pack(side="left", padx=12)

    def _build_log(self):
        wrap = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Progress:").pack(anchor="w")
        self.log_widget = scrolledtext.ScrolledText(wrap, height=18, state="disabled",
                                                     wrap="word", font=("Consolas", 9))
        self.log_widget.pack(fill="both", expand=True)

    # ── Logging plumbing ────────────────────────────────────
    def _configure_logging(self):
        """Attach our queue handler (and a file handler) to the root logger so
        every web_crawler.* message shows up in the window."""
        handler = _QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                                datefmt="%H:%M:%S"))
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        # Avoid stacking duplicate handlers if the window is reopened.
        root_logger.handlers = [h for h in root_logger.handlers
                                if not isinstance(h, _QueueLogHandler)]
        root_logger.addHandler(handler)
        # Also keep the on-disk log for support, like the CLI does.
        try:
            file_handler = logging.FileHandler(DEFAULTS.log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            root_logger.addHandler(file_handler)
        except Exception:
            pass

    def _drain_log_queue(self):
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item == _DONE:
                    self._on_finished()
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.root.after(150, self._drain_log_queue)

    def _append(self, line: str):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", line + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    # ── Remembered preferences ──────────────────────────────
    def _load_prefs(self) -> dict:
        """Load the last-used field values, if any. Never raises."""
        try:
            with open(_PREFS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_prefs(self):
        """Remember the current field values for next launch. Never raises."""
        prefs = {
            "input_csv": self.input_var.get().strip(),
            "start": self.start_var.get().strip(),
            "end": self.end_var.get().strip(),
            "proxy": self.proxy_var.get().strip(),
            "profile": self.profile_var.get().strip(),
            "resume": bool(self.resume_var.get()),
            "retry_failed": bool(self.retry_failed_var.get()),
        }
        try:
            with open(_PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(prefs, f, indent=2)
        except Exception as e:
            logger.debug(f"[GUI] Could not save preferences: {e}")

    # ── Run control ─────────────────────────────────────────
    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select input CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)

    def _parse_int(self, value: str, label: str):
        value = value.strip()
        if not value:
            return None
        if not value.isdigit():
            raise ValueError(f"{label} must be a whole number (got '{value}').")
        return int(value)

    def _on_start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            start = self._parse_int(self.start_var.get(), "Start row")
            end = self._parse_int(self.end_var.get(), "End row")
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        input_csv = self.input_var.get().strip()
        if not input_csv or not os.path.exists(input_csv):
            messagebox.showerror("Missing file", "Please choose an input CSV that exists.")
            return

        proxy = self.proxy_var.get().strip()
        if not proxy:
            if not messagebox.askyesno(
                "No proxy set",
                "No proxy was entered, so the run will use your direct connection.\n\n"
                "Continue without a proxy?",
            ):
                return

        args = {
            "input": input_csv,
            "start": start,
            "end": end,
            "proxy": proxy or None,
            "profile": self.profile_var.get().strip() or None,
            "retry_failed": self.retry_failed_var.get(),
            "skip_vpn_check": True,        # proxy provides the IP; no VPN gate in the GUI
            "resume": self.resume_var.get(),
            "no_resume": not self.resume_var.get(),
        }
        settings = load_settings(args)
        self.last_output_csv = settings.output_csv
        self.last_user_data_dir = settings.user_data_dir
        self._save_prefs()  # remember these entries for next time

        self.control = RunControl()
        self.paused = False
        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="Pause")
        self.stop_btn.configure(state="normal")
        self.status_var.set("Running…  (watch the Chrome window for any CAPTCHA)")
        self._append("=" * 60)
        self._append("Starting. Chrome will (re)launch — solve any CAPTCHA in that window.")

        self.worker = threading.Thread(target=self._run_worker,
                                       args=(settings, self.control), daemon=True)
        self.worker.start()

    def _run_worker(self, settings, control):
        try:
            asyncio.run(_run(settings, control))
        except Exception as e:
            logger.error(f"[GUI] Run failed: {e}")
        finally:
            self.log_queue.put(_DONE)

    def _on_pause(self):
        if not self.control:
            return
        if self.paused:
            self.control.resume()
            self.paused = False
            self.pause_btn.configure(text="Pause")
            self.status_var.set("Running…")
            self._append("[Resumed]")
        else:
            self.control.pause()
            self.paused = True
            self.pause_btn.configure(text="Resume")
            self.status_var.set("Paused — will hold after the current address finishes.")
            self._append("[Paused — finishing the current address, then waiting]")

    def _on_stop(self):
        if not self.control:
            return
        self.control.stop()
        self.status_var.set("Stopping — closing Chrome and ending the run…")
        self._append("[Stopping — closing the Chrome window. Progress is saved.]")
        self.pause_btn.configure(state="disabled")
        self.stop_btn.configure(state="disabled")
        # Closing Chrome interrupts any in-flight wait so the run ends promptly.
        self._close_chrome_bg()

    def _close_chrome_bg(self):
        """Close the project's Chrome window on a background thread (the kill
        waits a few seconds for file locks, which would otherwise freeze the
        window). Scoped to the project profile so other Chrome stays open."""
        user_data_dir = getattr(self, "last_user_data_dir", None) or DEFAULTS.user_data_dir
        threading.Thread(
            target=chrome.kill_project_chrome, args=(user_data_dir,), daemon=True
        ).start()

    def _on_finished(self):
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="Pause")
        self.stop_btn.configure(state="disabled")
        self.paused = False
        self.control = None
        self.status_var.set("Done.")
        self._append("=" * 60)
        # Close the Chrome window now the run has ended.
        self._close_chrome_bg()
        xlsx = (self.last_output_csv or "").replace(".csv", ".xlsx")
        if xlsx and os.path.exists(xlsx):
            if messagebox.askyesno("Finished", "Scraping finished.\n\nOpen the results spreadsheet now?"):
                try:
                    os.startfile(xlsx)  # noqa: S606 (Windows-only, intended)
                except Exception as e:
                    messagebox.showinfo("Results saved", f"Results saved to:\n{xlsx}\n\n({e})")
        else:
            messagebox.showinfo("Finished", "Scraping finished. No spreadsheet was produced "
                                            "(no rows saved). Check the progress log.")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Still running",
                "A scrape is still running. Progress is saved continuously, but closing now "
                "stops it and closes Chrome.\n\nClose anyway?",
            ):
                return
            if self.control:
                self.control.stop()
            self._close_chrome_bg()  # terminate the browser along with the app
        self._save_prefs()  # remember entries even if the user never clicked Start
        self.root.destroy()


def main():
    root = tk.Tk()
    ScraperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
