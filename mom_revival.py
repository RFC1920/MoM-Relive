"""Memories of Mars Revival client configurator and launcher."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import momlib
import redirect_urls
import ui_helpers
from version import __version__

_INSTANCE_MUTEX = None
_INSTANCE_MUTEX_NAME = "Local\\MoMReliveClient-6F3E8A17-79BC-40C8-A0BC-BCF72BA9E4D1"


def acquire_single_instance() -> bool:
    """Keep exactly one current MoM Relive client UI per Windows session."""
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX = (kernel32, handle)
    return True


def release_single_instance() -> None:
    global _INSTANCE_MUTEX
    if _INSTANCE_MUTEX is not None:
        kernel32, handle = _INSTANCE_MUTEX
        kernel32.CloseHandle(handle)
        _INSTANCE_MUTEX = None


def notify_duplicate_instance() -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(
            None,
            "MoM Relive Client is already running. Use the existing window.",
            "MoM Relive Client",
            0x40,
        )


def bundled_launcher() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("MoMClientLauncher.exe")
    return Path(__file__).resolve().parent / "dist" / "MoMClientLauncher.exe"


class ClientApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title(f"MoM Relive - Client {__version__}")
        self.root.geometry("960x800")
        self.root.minsize(760, 600)
        self.closing = False
        self.settings = momlib.load_settings()
        legacy_host = self.settings.get("backend_host", "127.0.0.1")
        self.settings.setdefault("client_backend_host", legacy_host or "127.0.0.1")
        self.settings.setdefault("client_engine_ini", str(momlib.client_engine_ini()))
        self.vars = {
            "client_dir": tk.StringVar(value=str(self.settings.get("client_dir", ""))),
            "client_engine_ini": tk.StringVar(
                value=str(self.settings.get("client_engine_ini", ""))
            ),
            "client_backend_host": tk.StringVar(
                value=str(self.settings.get("client_backend_host", "127.0.0.1"))
            ),
            "backend_port": tk.StringVar(
                value=str(self.settings.get("backend_port", 8080))
            ),
            "access_key": tk.StringVar(value=str(self.settings.get("access_key", ""))),
            "limit_client_cpu": tk.BooleanVar(
                value=bool(self.settings.get("limit_client_cpu", True))
            ),
            "openssl_compat": tk.BooleanVar(
                value=bool(self.settings.get("openssl_compat", False))
            ),
        }
        self.patch_status_var = tk.StringVar(value="Checking patch...")
        self.update_status_var = tk.StringVar(value="Updates: checking...")
        self.update_check_running = False
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log(
            "Ready. Prepare installs community-mode access and redirects the client to the Relive backend."
        )
        self.root.after(150, self.show_patch_status)
        self.root.after(900, self.check_for_updates)

    def _build(self):
        ttk = self.ttk
        style = ttk.Style(self.root)
        style.configure(
            "ClientReady.TLabel",
            foreground="#12823b",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "ClientWarning.TLabel",
            foreground="#9a6700",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "ClientMuted.TLabel",
            foreground="#586069",
            font=("Segoe UI", 9),
        )

        host = ttk.Frame(self.root)
        host.pack(fill="both", expand=True)
        canvas = self.tk.Canvas(host, highlightthickness=0)
        scroll = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        outer = ttk.Frame(canvas, padding=14)
        window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        canvas.bind_all(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"),
        )

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(
            header, text="Memories of Mars Client", font=("Segoe UI", 16, "bold")
        ).pack(side="left")
        status = ttk.Frame(header)
        status.pack(side="right")
        self.patch_status_label = ttk.Label(
            status,
            textvariable=self.patch_status_var,
            style="ClientWarning.TLabel",
        )
        self.patch_status_label.pack(anchor="e")
        self.update_status_label = ttk.Label(
            status,
            textvariable=self.update_status_var,
            style="ClientMuted.TLabel",
        )
        self.update_status_label.pack(anchor="e", pady=(2, 0))
        ttk.Label(
            outer,
            text=(
                "Prepare this installation to connect to a Relive server. "
                "The dedicated server is managed in its separate application."
            ),
            wraplength=780,
            justify="left",
        ).pack(anchor="w", pady=(3, 10))

        game = ttk.LabelFrame(outer, text="1. Game installation", padding=10)
        game.pack(fill="x")
        self._field(
            game,
            0,
            "Memories of Mars folder",
            "client_dir",
            browse=True,
            help_text="Root folder installed by Steam; it contains Launch_Game.exe.",
        )
        self._field(
            game,
            1,
            "Engine.ini override",
            "client_engine_ini",
            width=40,
            browse=self.browse_engine_ini,
            browse_help="Select the exact Engine.ini used by the game.",
            help_text=(
                "Optional exact Engine.ini used by this Windows profile. "
                "Leave blank to use the normal Local AppData path."
            ),
        )
        ttk.Label(
            game,
            text=(
                "Normally detected automatically. Select another file only when the "
                "game uses a different Windows profile or redirected AppData folder."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        connection = ttk.LabelFrame(
            outer, text="2. Server connection", padding=10
        )
        connection.pack(fill="x", pady=(9, 0))
        self._field(
            connection,
            0,
            "Backend IP or hostname",
            "client_backend_host",
            help_text="Use 127.0.0.1 on the host, or its public IP/DNS from another PC.",
        )
        self._field(
            connection,
            1,
            "Backend port",
            "backend_port",
            width=10,
            help_text="Backend TCP port; it must match the server configuration.",
        )
        self._field(
            connection,
            2,
            "Shared key",
            "access_key",
            width=22,
            help_text="Key protecting the backend; it must match exactly.",
        )
        ttk.Label(
            connection,
            text="The server administrator must give you these three values.",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        compatibility = ttk.LabelFrame(
            outer, text="3. Modern PC compatibility", padding=10
        )
        compatibility.pack(fill="x", pady=(9, 0))
        cpu_check = ttk.Checkbutton(
            compatibility,
            text="Temporarily limit CPU during loading (recommended)",
            variable=self.vars["limit_client_cpu"],
        )
        cpu_check.pack(anchor="w")
        ui_helpers.ToolTip(
            cpu_check,
            "Prevents an Unreal Engine crash on high-thread-count CPUs, then restores all cores.",
        )
        ssl_check = ttk.Checkbutton(
            compatibility,
            text="Legacy OpenSSL compatibility (only if the game closes while loading)",
            variable=self.vars["openssl_compat"],
        )
        ssl_check.pack(anchor="w", pady=(4, 0))
        ui_helpers.ToolTip(
            ssl_check,
            "Enables the legacy cryptographic compatibility required by some modern processors.",
        )

        actions = ttk.LabelFrame(outer, text="Actions", padding=8)
        actions.pack(fill="x", pady=(9, 8))
        self._action_button(
            actions,
            "Prepare / repair",
            self.apply_client,
            "Applies the reversible compatibility patch and installs the Relive community launcher.",
        ).grid(row=0, column=0, sticky="w")
        self._action_button(
            actions,
            "Play (community mode)",
            self.launch_client,
            "Repairs when needed and starts the game in the retired-service community mode.",
        ).grid(row=0, column=1, sticky="w", padx=7)
        self._action_button(
            actions,
            "Test connection",
            self.test_connection,
            "Checks the shared key, port, and servers advertised by the backend.",
        ).grid(row=0, column=2, sticky="w")
        self._action_button(
            actions,
            "Repair Engine.ini only",
            self.repair_engine_ini,
            "With the game closed, repairs and verifies the selected Engine.ini without modifying the executable.",
        ).grid(row=1, column=0, sticky="w", pady=(7, 0))
        self._action_button(
            actions,
            "Close game processes",
            self.close_game_processes,
            "After confirmation, closes only MemoriesOfMars.exe process trees.",
        ).grid(row=1, column=1, sticky="w", padx=7, pady=(7, 0))
        self._action_button(
            actions,
            "Restore official files",
            self.restore_client,
            "Restores official executables and enables the EAC launcher again.",
        ).grid(row=1, column=2, sticky="w", pady=(7, 0))
        self._action_button(
            actions,
            "Check for updates",
            lambda: self.check_for_updates(manual=True),
            "Checks official GitHub releases and offers to open the download page when a newer version exists.",
        ).grid(row=2, column=0, sticky="w", pady=(7, 0))
        self._action_button(
            actions,
            "Legal & licences",
            self.open_legal,
            "Opens the unofficial-project notice; other licences are installed beside it.",
        ).grid(row=2, column=2, sticky="w", pady=(7, 0))

        activity = ttk.LabelFrame(outer, text="Activity", padding=6)
        activity.pack(fill="both", expand=True, pady=(0, 4))
        self.log_box = self.tk.Text(activity, height=7, state="disabled", wrap="word")
        log_scroll = ttk.Scrollbar(
            activity, orient="vertical", command=self.log_box.yview
        )
        self.log_box.configure(yscrollcommand=log_scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    def _action_button(self, parent, text, command, help_text):
        button = self.ttk.Button(parent, text=text, command=command)
        ui_helpers.ToolTip(button, help_text)
        return button

    def open_legal(self):
        from tkinter import messagebox

        open_notice = messagebox.askyesno(
            "About MoM Relive",
            "MoM Relive — independent, unofficial community project\n\n"
            "Copyright (C) 2026 David Bermejo and contributors.\n"
            "Free software under GNU GPLv3; redistribution is permitted under "
            "that licence. ABSOLUTELY NO WARRANTY.\n\n"
            "Not affiliated with the game's rightsholders or platform providers.\n\n"
            "Open the complete legal notice?",
            parent=self.root,
        )
        if not open_notice:
            return
        try:
            momlib.open_project_document("LEGAL.md")
        except (OSError, momlib.ConfigError) as exc:
            self.error("Legal & licences", exc)

    def _field(
        self,
        parent,
        row,
        label,
        key,
        width=48,
        browse=False,
        help_text="",
        browse_help="Select the game's root folder.",
    ):
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        entry = ttk.Entry(parent, textvariable=self.vars[key], width=width)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        parent.columnconfigure(1, weight=1)
        if help_text:
            ui_helpers.ToolTip(entry, help_text)
        if browse:
            command = self.browse if browse is True else browse
            button = ttk.Button(parent, text="Browse...", command=command)
            button.grid(row=row, column=2, padx=(7, 0))
            ui_helpers.ToolTip(button, browse_help)
        return entry

    def browse(self):
        from tkinter import filedialog

        value = filedialog.askdirectory(
            initialdir=self.vars["client_dir"].get() or None, parent=self.root
        )
        if value:
            self.vars["client_dir"].set(value)
            self.show_patch_status(log_result=False)

    def browse_engine_ini(self):
        from tkinter import filedialog

        current = self.vars["client_engine_ini"].get().strip()
        current_path = (
            Path(current).expanduser() if current else momlib.client_engine_ini()
        )
        value = filedialog.askopenfilename(
            initialdir=str(current_path.parent),
            initialfile=current_path.name,
            filetypes=(
                ("Unreal Engine configuration", "Engine.ini"),
                ("INI files", "*.ini"),
            ),
            parent=self.root,
        )
        if value:
            self.vars["client_engine_ini"].set(value)
            self.show_patch_status(log_result=False)

    @staticmethod
    def _ini_path(settings):
        value = str(settings.get("client_engine_ini", "")).strip()
        return Path(value).expanduser() if value else None

    def show_patch_status(self, log_result=True):
        try:
            result = momlib.verify_client_preparation(
                self.vars["client_dir"].get().strip(),
                self.vars["client_backend_host"].get().strip(),
                self.vars["backend_port"].get(),
                self.vars["access_key"].get(),
                self._ini_path(
                    {"client_engine_ini": self.vars["client_engine_ini"].get()}
                ),
            )
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.patch_status_var.set("Repair required")
            self.patch_status_label.configure(style="ClientWarning.TLabel")
            if log_result:
                self.log(f"WARNING: client setup is not ready: {exc}")
        else:
            self.patch_status_var.set("Ready · configuration verified")
            self.patch_status_label.configure(style="ClientReady.TLabel")
            if log_result:
                self.log(
                    "Status: community launcher and Engine.ini verified at "
                    f"{result['ini']}"
                )

    def save(self) -> dict:
        values = dict(self.settings)
        values.update({key: var.get() for key, var in self.vars.items()})
        values["backend_port"] = momlib.validate_port(values["backend_port"])
        values["access_key"] = momlib.validate_key(values["access_key"])
        values["client_backend_host"] = str(values["client_backend_host"]).strip()
        if not values["client_backend_host"]:
            raise momlib.ConfigError("Enter the backend IP address or hostname")
        momlib.save_settings(values)
        self.settings = values
        return values

    def _apply(self, settings: dict) -> dict:
        return momlib.apply_client(
            settings["client_dir"],
            settings["client_backend_host"],
            settings["backend_port"],
            settings["access_key"],
            ini_path=self._ini_path(settings),
            launcher_source=bundled_launcher(),
        )

    def repair_engine_ini(self):
        try:
            settings = self.save()
            result = momlib.repair_client_ini(
                settings["client_backend_host"],
                settings["backend_port"],
                settings["access_key"],
                self._ini_path(settings),
            )
            self.show_patch_status(log_result=False)
            self.log(f"Engine.ini repaired and verified: {result['ini']}")
        except (ValueError, OSError) as exc:
            self.error("Repair Engine.ini", exc)

    def close_game_processes(self):
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Close game processes",
            "Force-close every running MemoriesOfMars.exe process? "
            "Unsaved in-game activity may be lost.",
            parent=self.root,
        ):
            return
        try:
            if momlib.close_windows_client_processes():
                self.log("Closed all MemoriesOfMars.exe process trees.")
            else:
                self.log("No running MemoriesOfMars.exe process was found.")
        except OSError as exc:
            self.error("Close game processes", exc)

    def check_for_updates(self, manual=False):
        if self.update_check_running:
            if manual:
                self.log("An update check is already running.")
            return
        self.update_check_running = True
        self.update_status_var.set("Updates: checking...")
        self.update_status_label.configure(style="ClientMuted.TLabel")

        def worker():
            result = error = None
            try:
                result = momlib.check_latest_release(__version__)
            except (OSError, ValueError, urllib.error.HTTPError) as exc:
                error = exc
            try:
                if not self.closing:
                    self.root.after(
                        0, self._finish_update_check, result, error, manual
                    )
            except (RuntimeError, self.tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _finish_update_check(self, result, error, manual):
        from tkinter import messagebox

        self.update_check_running = False
        if error is not None:
            self.update_status_var.set("Updates: check unavailable")
            self.update_status_label.configure(style="ClientMuted.TLabel")
            self.log(f"Update check unavailable: {error}")
            if manual:
                messagebox.showwarning(
                    "Check for updates", str(error), parent=self.root
                )
            return
        if result["available"]:
            self.update_status_var.set(f"Update available · v{result['latest']}")
            self.update_status_label.configure(style="ClientWarning.TLabel")
            self.log(
                f"Update available: v{result['latest']} "
                f"(installed v{result['current']})."
            )
            if manual and messagebox.askyesno(
                "Update available",
                f"MoM Relive v{result['latest']} is available. "
                "Open the official GitHub release page?",
                parent=self.root,
            ):
                webbrowser.open(result["url"])
        else:
            self.update_status_var.set(f"Up to date · v{result['current']}")
            self.update_status_label.configure(style="ClientReady.TLabel")
            self.log(f"Update check: v{result['current']} is the latest release.")
            if manual:
                messagebox.showinfo(
                    "Check for updates",
                    f"You are running the latest version: v{result['current']}.",
                    parent=self.root,
                )

    def apply_client(self):
        try:
            result = self._apply(self.save())
            self.show_patch_status(log_result=False)
            self.log(f"Client prepared successfully: {result['url']}")
            self.log(f"Engine.ini verified: {result['ini']}")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Prepare client", exc)

    def launch_client(self):
        try:
            settings = self.save()
            self._apply(settings)
            launcher = Path(settings["client_dir"]) / momlib.CLIENT_LAUNCHER_REL
            subprocess.Popen([str(launcher)], cwd=str(launcher.parent))
            self.show_patch_status(log_result=False)
            self.log("Game started through the Relive community launcher.")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Start game", exc)

    def test_connection(self):
        try:
            settings = self.save()
            verified = momlib.verify_client_preparation(
                settings["client_dir"],
                settings["client_backend_host"],
                settings["backend_port"],
                settings["access_key"],
                self._ini_path(settings),
            )
            base = verified["url"]
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Test connection", exc)
            return
        self.show_patch_status(log_result=False)
        self.log(f"Local client configuration verified: {verified['ini']}")
        self.log("Testing the backend connection...")

        def worker():
            try:
                with urllib.request.urlopen(base + "GetAllSessions", timeout=4) as response:
                    data = json.load(response)
                sessions = data.get("Sessions")
                if not isinstance(sessions, list):
                    raise TypeError("the response is not from a compatible Relive backend")
                message = f"Connection successful: {len(sessions)} advertised server(s)."
            except (OSError, TypeError, ValueError, urllib.error.HTTPError) as exc:
                message = f"CONNECTION ERROR: {exc}"
            try:
                if not self.closing:
                    self.root.after(0, self.log, message)
            except (RuntimeError, self.tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def restore_client(self):
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Restore client",
            "The original executable and Steam EAC launcher will be restored. Continue?",
            parent=self.root,
        ):
            return
        try:
            settings = self.save()
            result = momlib.restore_client(
                settings["client_dir"], self._ini_path(settings)
            )
            if not result["binary_restored"] or not result["launcher_restored"]:
                raise momlib.ConfigError(
                    "An original backup is missing. Use Verify integrity in Steam to complete restoration."
                )
            self.show_patch_status(log_result=False)
            self.log("Client restored: Steam will start the official EAC launcher again.")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Restore client", exc)

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{stamp}  {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def error(self, title, error):
        from tkinter import messagebox

        self.log(f"ERROR: {error}")
        messagebox.showerror(title, str(error), parent=self.root)

    def on_close(self):
        self.closing = True
        self.root.unbind_all("<MouseWheel>")
        self.root.destroy()


def gui_main() -> int:
    import tkinter as tk

    if not acquire_single_instance():
        notify_duplicate_instance()
        return 0
    try:
        root = tk.Tk()
        ClientApp(root)
        root.mainloop()
        return 0
    finally:
        release_single_instance()


if __name__ == "__main__":
    raise SystemExit(gui_main())
