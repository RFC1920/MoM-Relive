"""Standalone Memories of Mars Relive dedicated-server manager."""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import backend
import momlib
import redirect_urls
import ui_helpers
from version import __version__

RUNTIME_FILE = momlib.app_data_dir() / "runtime.json"


class IncompatibleBackendError(OSError):
    pass


def _find_server_console():
    if os.name != "nt":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    matches = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if "MemoriesOfMarsServer.exe" in title.value:
                matches.append(hwnd)
                return False
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else None


def _show_server_console(visible):
    hwnd = _find_server_console()
    if not hwnd:
        return False
    import ctypes

    ctypes.windll.user32.ShowWindow(hwnd, 5 if visible else 0)
    if visible:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    return True


def _restore_system_dll_search():
    """Keep external game binaries from loading DLLs bundled by PyInstaller."""
    if os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
    kernel32.SetDllDirectoryW.restype = ctypes.c_int
    if not kernel32.SetDllDirectoryW(None):
        code = ctypes.get_last_error()
        raise OSError(code, "Windows could not restore the system DLL search path")


def _disable_server_quickedit(pid):
    """Evita que seleccionar texto congele el bucle principal del juego."""
    if os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    for _ in range(20):
        if kernel32.AttachConsole(int(pid)):
            try:
                handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
                mode = ctypes.c_uint()
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    value = (mode.value | 0x0080) & ~0x0040
                    kernel32.SetConsoleMode(handle, value)
            finally:
                kernel32.FreeConsole()
            return
        time.sleep(0.1)


def _launch_server_process(settings):
    exe = Path(settings["server_dir"]) / momlib.SERVER_EXE_REL
    _restore_system_dll_search()
    kwargs = {
        "cwd": str(exe.parent),
        "env": momlib.server_environment(settings),
    }
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs.update(
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            startupinfo=startup,
        )
    process = subprocess.Popen([str(exe), "-log"], **kwargs)
    if os.name == "nt":
        threading.Thread(
            target=_disable_server_quickedit, args=(process.pid,), daemon=True
        ).start()
    return process


def _backend_command(settings):
    args = [
        "--backend-child",
        "--host",
        settings["backend_bind"],
        "--port",
        str(settings["backend_port"]),
        "--access-key",
        settings["access_key"],
        "--data-dir",
        str(momlib.app_data_dir()),
    ]
    if settings.get("public_ip"):
        args.extend(["--advertise-host", settings["public_ip"]])
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-u", str(Path(__file__).resolve()), *args]


def _write_runtime(data):
    RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNTIME_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(RUNTIME_FILE)


def _read_runtime():
    try:
        data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _port_is_listening(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except OSError:
        return False


class ServerConfigDialog:
    """Server-only configuration; client settings stay in the client app."""

    def __init__(self, manager):
        self.manager = manager
        self.root = manager.root
        self.tk = manager.tk
        self.ttk = manager.ttk
        self.window = self.tk.Toplevel(self.root)
        self.window.title("Dedicated Server Configuration")
        self.window.geometry("760x660")
        self.window.minsize(700, 600)
        self.window.transient(self.root)
        settings = momlib.load_settings()
        legacy_host = settings.get("backend_host", "127.0.0.1")
        settings.setdefault("server_backend_host", legacy_host or "127.0.0.1")
        self.settings = settings
        self.worlds = momlib.discover_server_worlds(settings.get("server_dir"))
        keys = (
            "server_dir",
            "server_backend_host",
            "backend_bind",
            "backend_port",
            "access_key",
            "server_name",
            "server_password",
            "server_id",
            "public_ip",
            "max_players",
            "admin_id",
        )
        self.vars = {
            key: self.tk.StringVar(value=str(settings.get(key, ""))) for key in keys
        }
        self.vars["skip_cloning"] = self.tk.BooleanVar(
            value=bool(settings.get("skip_cloning", True))
        )
        self.vars["server_openssl_compat"] = self.tk.BooleanVar(
            value=bool(settings.get("server_openssl_compat", True))
        )
        self._build()
        if not self.vars["public_ip"].get().strip():
            self.window.after(350, lambda: self.detect_public_ip(automatic=True))

    def _build(self):
        ttk = self.ttk
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer, text="Server Configuration", font=("Segoe UI", 15, "bold")
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="These settings apply only to the machine hosting the server.",
        ).pack(anchor="w", pady=(2, 10))

        backend_box = ttk.LabelFrame(outer, text="Relive Backend", padding=10)
        backend_box.pack(fill="x")
        self._field(backend_box, 0, "Listen address", "backend_bind")
        self._field(backend_box, 1, "Backend seen by the server", "server_backend_host")
        self._field(backend_box, 2, "TCP port", "backend_port", width=10)
        self._field(backend_box, 3, "Shared key", "access_key", width=22)
        ttk.Label(
            backend_box,
            text=(
                "0.0.0.0 allows external connections. Clients need your IP/DNS, "
                "this port, and the same shared key."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        server_box = ttk.LabelFrame(outer, text="Dedicated World", padding=10)
        server_box.pack(fill="x", pady=(10, 0))
        self._field(server_box, 0, "Server folder", "server_dir", browse=True)
        self._field(server_box, 1, "Display name", "server_name")
        self._field(server_box, 2, "Password", "server_password")
        self._field(
            server_box,
            3,
            "Stable world ID",
            "server_id",
            choices=[world["server_id"] for world in self.worlds],
        )
        self._field(server_box, 4, "Public IP or DNS", "public_ip")
        ttk.Button(server_box, text="Detect public IP", command=self.detect_public_ip).grid(
            row=4, column=2, padx=(7, 0)
        )
        self._field(server_box, 5, "Maximum players", "max_players", width=10)
        self._field(server_box, 6, "Administrator ID", "admin_id")
        ttk.Checkbutton(
            server_box,
            text="Preserve character on reconnect (skip the cloning facility)",
            variable=self.vars["skip_cloning"],
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ssl_check = ttk.Checkbutton(
            server_box,
            text="Legacy OpenSSL compatibility (recommended on modern processors)",
            variable=self.vars["server_openssl_compat"],
        )
        ssl_check.grid(row=8, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ui_helpers.ToolTip(
            ssl_check,
            "Sets OPENSSL_ia32cap=:~0x20000000 when launching the dedicated server.",
        )
        best = self.worlds[0] if self.worlds else None
        current = self.vars["server_id"].get().strip()
        if best and best["server_id"] != current:
            ttk.Label(
                server_box,
                text=(
                    f"Save with more data detected: {best['server_id']} "
                    f"({best['players']} player(s), {best['player_files']} files)."
                ),
                foreground="#9a5b00",
            ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
            ttk.Button(
                server_box,
                text="Use this save",
                command=lambda: self.vars["server_id"].set(best["server_id"]),
            ).grid(row=9, column=2, padx=(7, 0), pady=(6, 0))
        ttk.Label(
            server_box,
            text=(
                "The ID selects Game\\Saved\\DB\\Server<ID>. Changing it opens or creates "
                "another world; it does not merely change its display name."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=(5, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Save", command=self.save_only).pack(side="left")
        ttk.Button(
            actions, text="Save and apply patch (managed)", command=self.apply
        ).pack(side="left", padx=8)
        ttk.Button(
            actions,
            text="Apply compatibility only",
            command=self.apply_compatibility,
        ).pack(side="left")
        native_actions = ttk.Frame(outer)
        native_actions.pack(fill="x", pady=(7, 0))
        ttk.Button(
            native_actions,
            text="Open native server config",
            command=self.open_native_config,
        ).pack(side="left")
        ttk.Button(actions, text="Open Windows Firewall ports", command=self.firewall).pack(
            side="right"
        )
        ttk.Label(
            outer,
            text=(
                "The managed action keeps the original manager workflow and writes the fields "
                "above. Compatibility only preserves the native server name, password, world "
                "and player settings. Neither action starts the world."
            ),
            wraplength=690,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

    def _field(
        self, parent, row, label, key, width=48, browse=False, choices=None
    ):
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        if choices:
            entry = ttk.Combobox(
                parent,
                textvariable=self.vars[key],
                values=choices,
                width=width,
            )
        else:
            entry = ttk.Entry(parent, textvariable=self.vars[key], width=width)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        parent.columnconfigure(1, weight=1)
        if browse:
            ttk.Button(parent, text="Browse...", command=self.browse).grid(
                row=row, column=2, padx=(7, 0)
            )

    def browse(self):
        from tkinter import filedialog

        value = filedialog.askdirectory(
            initialdir=self.vars["server_dir"].get() or None, parent=self.window
        )
        if value:
            self.vars["server_dir"].set(value)

    def values(self):
        result = dict(self.settings)
        result.update({key: var.get() for key, var in self.vars.items()})
        result["backend_port"] = momlib.validate_port(result["backend_port"])
        result["access_key"] = momlib.validate_key(result["access_key"])
        result["max_players"] = int(result["max_players"])
        if not 1 <= result["max_players"] <= 64:
            raise momlib.ConfigError("Maximum players must be between 1 and 64")
        result["public_ip"] = momlib.check_public_ip(result["public_ip"])
        if not str(result["server_dir"]).strip():
            raise momlib.ConfigError("Select the dedicated-server folder")
        if not str(result["server_backend_host"]).strip():
            raise momlib.ConfigError("Enter the backend address seen by the server")
        return result

    def _save(self):
        result = self.values()
        momlib.save_settings(result)
        self.settings = result
        self.manager.settings = result
        return result

    def save_only(self):
        try:
            self._save()
            self.manager.log("Server configuration saved.")
        except (ValueError, OSError) as exc:
            self.manager.error("Server configuration", exc)

    def apply(self):
        try:
            settings = self._save()
            result = momlib.apply_server(
                settings["server_dir"],
                settings["server_backend_host"],
                settings["backend_port"],
                settings["access_key"],
                server_name=settings["server_name"],
                server_password=settings["server_password"],
                server_id=settings["server_id"],
                public_ip=settings["public_ip"],
                max_players=settings["max_players"],
                admin_id=settings["admin_id"],
                skip_cloning=settings["skip_cloning"],
            )
            self.manager.log(f"Configuration applied: {result['url']}")
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.manager.error("Apply configuration", exc)

    def apply_compatibility(self):
        try:
            settings = self._save()
            result = momlib.apply_server_compatibility(
                settings["server_dir"],
                settings["server_backend_host"],
                settings["backend_port"],
                settings["access_key"],
                skip_cloning=settings["skip_cloning"],
            )
            self.manager.log(
                f"Compatibility applied; native server settings preserved: {result['url']}"
            )
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.manager.error("Apply compatibility", exc)

    def open_native_config(self):
        try:
            settings = self._save()
            path = Path(settings["server_dir"]) / momlib.SERVER_CFG_REL
            if not path.is_file():
                raise momlib.ConfigError(f"Could not find {path}")
            os.startfile(path)
        except (ValueError, OSError) as exc:
            self.manager.error("Native server configuration", exc)

    def detect_public_ip(self, automatic=False):
        if not automatic:
            self.manager.log("Detecting public IP...")

        def worker():
            try:
                value = momlib.detect_public_ip()
            except (ValueError, OSError) as exc:
                self.root.after(0, self.manager.log, f"Public IP: {exc}")
                return
            self.root.after(0, self.vars["public_ip"].set, value)
            self.root.after(0, self.manager.log, f"Public IP detected: {value}")

        threading.Thread(target=worker, daemon=True).start()

    def firewall(self):
        try:
            settings = self._save()
            rules = (
                ("MoM Relive game UDP 7777", "UDP", 7777),
                ("MoM Relive beacon UDP 15000", "UDP", 15000),
                (
                    f"MoM Revival backend TCP {settings['backend_port']}",
                    "TCP",
                    settings["backend_port"],
                ),
            )
            failures = []
            for name, protocol, port in rules:
                result = subprocess.run(
                    [
                        "netsh",
                        "advfirewall",
                        "firewall",
                        "add",
                        "rule",
                        f"name={name}",
                        "dir=in",
                        "action=allow",
                        f"protocol={protocol}",
                        f"localport={port}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode:
                    failures.append(name)
            if failures:
                raise OSError("Could not create: " + ", ".join(failures))
            self.manager.log("Ports allowed through Windows Firewall.")
        except (ValueError, OSError) as exc:
            self.manager.error("Firewall", exc)


class ServerManager:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title(f"MoM Server Manager {__version__}")
        self.root.geometry("1040x800")
        self.root.minsize(860, 650)
        self.settings = momlib.load_settings()
        self.backend_process = None
        self.server_process = None
        self.starting = False
        self.stopping = False
        self.auto_restarting = False
        self.closing = False
        self.last_auto_restart_at = 0.0
        self.refreshing = False
        self.refresh_after = None
        self.server_log_after = None
        self.last_status = None
        self.last_status_key = None
        self.server_log_path = None
        self.server_log_offset = 0
        self.character_names = {}
        self.console_visible = False
        self.status_var = tk.StringVar(value="Checking...")
        self.backend_var = tk.StringVar(value="Checking")
        self.server_var = tk.StringVar(value="Checking")
        self.players_var = tk.StringVar(value="0")
        self.follow_server_log = tk.BooleanVar(value=True)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log(f"Manager {__version__} started; checking managed processes.")
        self._poll_server_log()
        self.refresh()

    def _build(self):
        ttk = self.ttk
        style = ttk.Style(self.root)
        style.configure(
            "Online.TLabel", foreground="#12823b", font=("Segoe UI", 11, "bold")
        )
        style.configure(
            "Offline.TLabel", foreground="#b42318", font=("Segoe UI", 11, "bold")
        )
        style.configure(
            "Warning.TLabel", foreground="#9a6700", font=("Segoe UI", 11, "bold")
        )
        style.configure("CardValue.TLabel", font=("Segoe UI", 12, "bold"))
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        title = ttk.Frame(outer)
        title.pack(fill="x")
        ttk.Label(
            title, text="Server Administration", font=("Segoe UI", 15, "bold")
        ).pack(side="left")
        self.status_label = ttk.Label(
            title, textvariable=self.status_var, style="Warning.TLabel"
        )
        self.status_label.pack(side="right")
        self._action_button(
            title,
            "Legal & licences",
            self.open_legal,
            "Opens the unofficial-project notice; other licences are installed beside it.",
        ).pack(side="right", padx=(0, 10))

        status = ttk.Frame(outer)
        status.pack(fill="x", pady=(10, 6))
        for column, (label, variable) in enumerate(
            (
                ("Backend", self.backend_var),
                ("Dedicated Server", self.server_var),
                ("Active Players", self.players_var),
            )
        ):
            card = ttk.LabelFrame(status, text=label, padding=(12, 7))
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 4))
            status.columnconfigure(column, weight=1)
            value = ttk.Label(card, textvariable=variable, style="CardValue.TLabel")
            value.pack(anchor="w")
            if column == 0:
                self.backend_status_label = value
            elif column == 1:
                self.server_status_label = value
            else:
                self.players_status_label = value

        controls = ttk.LabelFrame(outer, text="Actions", padding=8)
        controls.pack(fill="x", pady=6)
        lifecycle = ttk.LabelFrame(controls, text="Server lifecycle", padding=6)
        lifecycle.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._action_button(
            lifecycle,
            "Start",
            self.start,
            "Applies configuration, starts the backend, and then loads the world.",
        ).pack(side="left", padx=(0, 5))
        self._action_button(
            lifecycle,
            "Stop",
            self.stop,
            "Creates a backup first, then stops the world and backend.",
        ).pack(side="left", padx=5)
        self._action_button(
            lifecycle,
            "Restart",
            self.restart,
            "Creates a backup, stops the processes, and starts the server again.",
        ).pack(side="left", padx=5)
        maintenance = ttk.LabelFrame(controls, text="Maintenance", padding=6)
        maintenance.grid(row=0, column=1, sticky="ew", padx=5)
        self._action_button(
            maintenance,
            "Create backup",
            self.backup,
            "Copies all JSON data under Game\\Saved\\DB without changing the active save.",
        ).pack(side="left", padx=4)
        self._action_button(
            maintenance,
            "Configuration",
            self.open_config,
            "Opens backend, world, public IP, administrator, and firewall settings.",
        ).pack(side="left", padx=4)
        self._action_button(
            maintenance,
            "Data folder",
            self.open_data,
            "Opens the folder containing settings, state, logs, and managed backups.",
        ).pack(side="left", padx=4)
        monitoring = ttk.LabelFrame(controls, text="Monitoring", padding=6)
        monitoring.grid(row=0, column=2, sticky="ew", padx=(5, 0))
        self.console_button = self._action_button(
            monitoring,
            "Show console",
            self.toggle_console,
            "Shows or hides the native console. QuickEdit is disabled to prevent freezes.",
        )
        self.console_button.pack(side="left", padx=4)
        self._action_button(
            monitoring,
            "Refresh",
            self.manual_refresh,
            "Immediately queries the backend, sessions, and active players.",
        ).pack(side="left", padx=4)
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(2, weight=1)

        panes = ttk.Panedwindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(6, 0))

        players = ttk.LabelFrame(panes, text="Connected Players", padding=8)
        panes.add(players, weight=2)
        columns = ("account", "name", "server", "joined")
        self.player_table = ttk.Treeview(
            players, columns=columns, show="headings", height=7
        )
        self.player_table.heading("account", text="Player identifier")
        self.player_table.heading("name", text="Name")
        self.player_table.heading("server", text="Server / session")
        self.player_table.heading("joined", text="Connected since")
        self.player_table.column("account", width=190)
        self.player_table.column("name", width=170)
        self.player_table.column("server", width=220)
        self.player_table.column("joined", width=170)
        scroll = ttk.Scrollbar(
            players, orient="vertical", command=self.player_table.yview
        )
        self.player_table.configure(yscrollcommand=scroll.set)
        self.player_table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        notebook_frame = ttk.Frame(panes)
        panes.add(notebook_frame, weight=3)
        notebook = ttk.Notebook(notebook_frame)
        notebook.pack(fill="both", expand=True)

        server_tab = ttk.Frame(notebook, padding=6)
        activity_tab = ttk.Frame(notebook, padding=6)
        notebook.add(server_tab, text="Server Log")
        notebook.add(activity_tab, text="Manager Activity")

        server_tools = ttk.Frame(server_tab)
        server_tools.pack(fill="x", pady=(0, 5))
        ttk.Checkbutton(
            server_tools,
            text="Follow latest",
            variable=self.follow_server_log,
        ).pack(side="left")
        self._action_button(
            server_tools,
            "Open file",
            self.open_server_log,
            "Opens Game.log with the default Windows application.",
        ).pack(side="right", padx=(5, 0))
        self._action_button(
            server_tools,
            "Clear view",
            self.clear_server_log_view,
            "Clears this view only; Game.log remains on disk.",
        ).pack(side="right")
        server_text_frame = ttk.Frame(server_tab)
        server_text_frame.pack(fill="both", expand=True)
        self.server_log_box = self.tk.Text(
            server_text_frame,
            height=10,
            state="disabled",
            wrap="none",
            font=("Consolas", 9),
            background="#101417",
            foreground="#d8e1e8",
            insertbackground="white",
        )
        server_scroll_y = ttk.Scrollbar(
            server_text_frame, orient="vertical", command=self.server_log_box.yview
        )
        server_scroll_x = ttk.Scrollbar(
            server_text_frame, orient="horizontal", command=self.server_log_box.xview
        )
        self.server_log_box.configure(
            yscrollcommand=server_scroll_y.set, xscrollcommand=server_scroll_x.set
        )
        self.server_log_box.grid(row=0, column=0, sticky="nsew")
        server_scroll_y.grid(row=0, column=1, sticky="ns")
        server_scroll_x.grid(row=1, column=0, sticky="ew")
        server_text_frame.rowconfigure(0, weight=1)
        server_text_frame.columnconfigure(0, weight=1)

        activity_tools = ttk.Frame(activity_tab)
        activity_tools.pack(fill="x", pady=(0, 5))
        self._action_button(
            activity_tools,
            "Clear",
            self.clear_activity,
            "Clears the displayed action and status history.",
        ).pack(side="right")
        activity_text = ttk.Frame(activity_tab)
        activity_text.pack(fill="both", expand=True)
        self.log_box = self.tk.Text(
            activity_text, height=8, state="disabled", wrap="word"
        )
        activity_scroll = ttk.Scrollbar(
            activity_text, orient="vertical", command=self.log_box.yview
        )
        self.log_box.configure(yscrollcommand=activity_scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        activity_scroll.pack(side="right", fill="y")

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

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{stamp}  {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_activity(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def clear_server_log_view(self):
        self.server_log_box.configure(state="normal")
        self.server_log_box.delete("1.0", "end")
        self.server_log_box.configure(state="disabled")

    def manual_refresh(self):
        self.log("Manual refresh requested.")
        self.refresh()

    def toggle_console(self):
        desired = not self.console_visible
        if not _show_server_console(desired):
            self.error(
                "Native console",
                "This instance was started without a recoverable console. Restart the "
                "server once from this manager to enable it.",
            )
            return
        self.console_visible = desired
        self.console_button.configure(
            text="Hide console" if desired else "Show console"
        )
        self.log(
            "Native console shown." if desired else "Native console hidden."
        )

    def _learn_character_names(self, text):
        patterns = (
            r"\((\d{1,20})\).*?Character for (.+?) \(",
            r"\((\d{1,20})\).*?Teleporting (.+?) to ",
        )
        for pattern in patterns:
            for player_id, name in re.findall(pattern, text):
                self.character_names[player_id] = name.strip()

    def _poll_server_log(self):
        try:
            path = (
                Path(self.settings["server_dir"])
                / "Game"
                / "Saved"
                / "Logs"
                / "Game.log"
            )
            if path != self.server_log_path:
                self.server_log_path = path
                self.server_log_offset = 0
            if path.is_file():
                size = path.stat().st_size
                if size < self.server_log_offset:
                    self.server_log_offset = 0
                    self._append_server_log("\n--- new Game.log ---\n")
                if size > self.server_log_offset:
                    with path.open("rb") as fh:
                        fh.seek(self.server_log_offset)
                        chunk = fh.read(min(size - self.server_log_offset, 512 * 1024))
                        self.server_log_offset = fh.tell()
                    text = chunk.decode("utf-8", errors="replace")
                    self._learn_character_names(text)
                    self._append_server_log(text)
        except (OSError, ValueError):
            pass
        if not self.closing:
            self.server_log_after = self.root.after(1000, self._poll_server_log)

    def _append_server_log(self, text):
        if not text:
            return
        self.server_log_box.configure(state="normal")
        self.server_log_box.insert("end", text)
        # Limita la memoria de la UI; el fichero completo permanece en disco.
        if int(self.server_log_box.index("end-1c").split(".")[0]) > 6000:
            self.server_log_box.delete("1.0", "1000.0")
        if self.follow_server_log.get():
            self.server_log_box.see("end")
        self.server_log_box.configure(state="disabled")

    def _admin_url(self):
        port = momlib.validate_port(self.settings["backend_port"])
        key = momlib.validate_key(self.settings["access_key"])
        return f"http://127.0.0.1:{port}/r/{key}/s/AdminStatus"

    def _fetch_status(self):
        with urllib.request.urlopen(self._admin_url(), timeout=1.5) as response:
            data = json.load(response)
        if (
            data.get("result") != "ok"
            or data.get("api_version") != 1
            or not isinstance(data.get("sessions"), list)
            or not isinstance(data.get("players"), list)
        ):
            raise IncompatibleBackendError(
                f"An old or incompatible backend is using port "
                f"{self.settings['backend_port']}"
            )
        return data

    def refresh(self):
        if self.refresh_after is not None:
            try:
                self.root.after_cancel(self.refresh_after)
            except self.tk.TclError:
                pass
            self.refresh_after = None
        if self.refreshing:
            return
        self.refreshing = True

        def worker():
            try:
                data = self._fetch_status()
            except IncompatibleBackendError as exc:
                data = {"_incompatible": str(exc)}
            except (OSError, ValueError, urllib.error.HTTPError):
                data = None
            try:
                if not self.closing:
                    self.root.after(0, self._show_status, data)
            except (RuntimeError, self.tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _show_status(self, data):
        self.refreshing = False
        self.last_status = data
        for item in self.player_table.get_children():
            self.player_table.delete(item)
        if data and data.get("_incompatible"):
            self.status_var.set("Incompatible backend")
            self.status_label.configure(style="Offline.TLabel")
            self.backend_var.set("Incompatible version")
            self.server_var.set("Unavailable")
            self.players_var.set("—")
            self.backend_status_label.configure(style="Offline.TLabel")
            self.server_status_label.configure(style="Offline.TLabel")
            status_key = ("incompatible",)
        elif not data:
            self.status_var.set("Stopped")
            self.status_label.configure(style="Offline.TLabel")
            self.backend_var.set("Stopped")
            self.server_var.set("Stopped")
            self.players_var.set("0")
            self.backend_status_label.configure(style="Offline.TLabel")
            self.server_status_label.configure(style="Offline.TLabel")
            self.players_status_label.configure(style="CardValue.TLabel")
            status_key = ("stopped",)
        else:
            sessions = data.get("sessions", [])
            players = data.get("players", [])
            if sessions:
                self.status_var.set("Online")
                self.status_label.configure(style="Online.TLabel")
                self.server_var.set("Active")
                self.server_status_label.configure(style="Online.TLabel")
            else:
                self.status_var.set("Loading world...")
                self.status_label.configure(style="Warning.TLabel")
                self.server_var.set("Loading")
                self.server_status_label.configure(style="Warning.TLabel")
            self.backend_var.set("Active")
            self.backend_status_label.configure(style="Online.TLabel")
            self.players_var.set(str(len(players)))
            self.players_status_label.configure(
                style="Online.TLabel" if players else "CardValue.TLabel"
            )
            status_key = (
                "online" if sessions else "loading",
                tuple(sorted(str(p.get("player_id", "")) for p in players)),
            )
            for player in players:
                joined = player.get("joined_at") or 0
                rendered = (
                    datetime.fromtimestamp(joined, tz=timezone.utc)
                    .astimezone()
                    .strftime("%d/%m/%Y %H:%M:%S")
                    if joined
                    else "—"
                )
                session = f"{player.get('server', '')} / {player.get('session_id', '')}"
                player_id = str(player.get("player_id", ""))
                display_name = self.character_names.get(player_id) or player.get(
                    "name", ""
                )
                self.player_table.insert(
                    "",
                    "end",
                    values=(
                        player_id,
                        display_name,
                        session,
                        rendered,
                    ),
                )
        if status_key != self.last_status_key:
            if status_key[0] == "online":
                self.log(
                    f"Server online; {len(data.get('players', []))} active player(s)."
                )
            elif status_key[0] == "loading":
                self.log("Backend active; waiting for the world to advertise itself.")
            elif status_key[0] == "stopped":
                self.log("Backend and server stopped.")
            elif status_key[0] == "incompatible":
                self.log("ERROR: the port responds with an incompatible backend.")
            self.last_status_key = status_key
        self._watch_managed_server()
        self.refresh_after = self.root.after(3000, self.refresh)

    def _watch_managed_server(self):
        """Restart the world if it exits, including its scheduled daily restart."""
        if self.starting or self.stopping or self.auto_restarting:
            return
        runtime = _read_runtime()
        saved_pid = runtime.get("server_pid")
        if not saved_pid or self._saved_process_matches(saved_pid, "server"):
            return
        # Evita un bucle si el ejecutable falla inmediatamente al arrancar.
        if time.time() - self.last_auto_restart_at < 60:
            self.status_var.set("Server stopped unexpectedly")
            return
        backend_pid = runtime.get("backend_pid") or self._backend_pid_on_port()
        if not backend_pid or not self._saved_process_matches(backend_pid, "backend"):
            return
        self.auto_restarting = True
        self.last_auto_restart_at = time.time()
        self.status_var.set("Restarting world...")
        self.status_label.configure(style="Warning.TLabel")
        self.log(
            "The world stopped (for example, for its daily restart); "
            "it will start again automatically."
        )
        threading.Thread(
            target=self._auto_restart_world, args=(runtime,), daemon=True
        ).start()

    def _auto_restart_world(self, runtime):
        try:
            settings = momlib.load_settings()
            # El proceso terminado ya no puede destruir su anuncio. Lo retiramos
            # antes de registrar el nuevo para no mostrar una sesion fantasma.
            try:
                status = self._fetch_status()
                for session in status.get("sessions", []):
                    sid = session.get("session_id")
                    if sid:
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{settings['backend_port']}"
                            f"/r/{settings['access_key']}/s/DestroySession/{sid}",
                            method="DELETE",
                        )
                        with urllib.request.urlopen(request, timeout=2):
                            pass
            except (OSError, ValueError, urllib.error.HTTPError):
                pass
            exe = Path(settings["server_dir"]) / momlib.SERVER_EXE_REL
            self.server_process = _launch_server_process(settings)
            self.console_visible = False
            runtime.update(
                {
                    "server_pid": self.server_process.pid,
                    "server_exe": str(exe.resolve()),
                    "started_at": time.time(),
                }
            )
            _write_runtime(runtime)
            self.root.after(
                0,
                self.log,
                "World restarted automatically; waiting for its advertisement.",
            )
        except (ValueError, OSError) as exc:
            self.root.after(0, self.error, "Automatic restart", exc)
        finally:
            self.auto_restarting = False

    def _validated_settings(self):
        settings = momlib.load_settings()
        momlib.validate_key(settings["access_key"])
        momlib.validate_port(settings["backend_port"])
        if not settings.get("server_dir"):
            raise momlib.ConfigError("Configure the dedicated-server folder first")
        self.settings = settings
        return settings

    def start(self):
        if self.starting:
            return
        try:
            settings = self._validated_settings()
            runtime = _read_runtime()
            if self._saved_process_matches(runtime.get("server_pid"), "server"):
                raise momlib.ConfigError(
                    "The server process is already running. If it is not advertised, "
                    "click Restart instead of starting another copy."
                )
            try:
                status = self._fetch_status()
            except IncompatibleBackendError as exc:
                raise momlib.ConfigError(
                    f"{exc}. Click Stop to close it safely, then start again."
                ) from exc
            except (ValueError, urllib.error.HTTPError) as exc:
                raise momlib.ConfigError(
                    f"Port {settings['backend_port']} responds, but it is not running "
                    "a compatible Relive backend. Stop the process using it."
                ) from exc
            except OSError:
                status = None
            if not status and _port_is_listening(settings["backend_port"]):
                raise momlib.ConfigError(
                    f"Port {settings['backend_port']} is already occupied by another process. "
                    "Stop it or choose another port before starting."
                )
            if status and status.get("sessions"):
                raise momlib.ConfigError("The server is already advertised and active")
            momlib.apply_server(
                settings["server_dir"],
                settings["server_backend_host"],
                settings["backend_port"],
                settings["access_key"],
                server_name=settings["server_name"],
                server_password=settings["server_password"],
                server_id=settings["server_id"],
                public_ip=settings["public_ip"],
                max_players=settings["max_players"],
                admin_id=settings["admin_id"],
                skip_cloning=settings["skip_cloning"],
            )
            if not status:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self.backend_process = subprocess.Popen(
                    _backend_command(settings), creationflags=flags
                )
            self.starting = True
            self.status_var.set("Starting...")
            self.status_label.configure(style="Warning.TLabel")
            self.log("Configuration applied; waiting for the backend.")
            threading.Thread(
                target=self._start_world_after_backend, args=(settings,), daemon=True
            ).start()
        except (ValueError, OSError, redirect_urls.PatchError) as exc:
            self.error("Could not start", exc)

    def _start_world_after_backend(self, settings):
        for _ in range(50):
            try:
                status = self._fetch_status()
                if status.get("result") == "ok":
                    break
            except (OSError, ValueError, urllib.error.HTTPError):
                time.sleep(0.2)
        else:
            self.starting = False
            self.root.after(0, self.error, "Startup", "The backend is not responding")
            return
        exe = Path(settings["server_dir"]) / momlib.SERVER_EXE_REL
        try:
            self.server_process = _launch_server_process(settings)
            self.console_visible = False
            self.root.after(
                0, lambda: self.console_button.configure(text="Show console")
            )
            _write_runtime(
                {
                    "backend_pid": self.backend_process.pid
                    if self.backend_process
                    else None,
                    "server_pid": self.server_process.pid,
                    "server_exe": str(exe.resolve()),
                    "started_at": time.time(),
                }
            )
            self.root.after(
                0,
                self.log,
                "Server started; the world may take a few seconds to advertise itself.",
            )
        except OSError as exc:
            self.root.after(0, self.error, "World startup", exc)
        finally:
            self.starting = False
            self.root.after(0, self.refresh)

    def _saved_process_matches(self, pid, kind):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return False
        script = (
            "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "
            + str(pid)
            + "'; if($p){$p | Select-Object ExecutablePath,CommandLine | ConvertTo-Json -Compress}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            info = json.loads(result.stdout)
        except (TypeError, ValueError):
            return False
        executable = str(info.get("ExecutablePath") or "")
        command = str(info.get("CommandLine") or "")
        if kind == "server":
            expected = str(
                (Path(self.settings["server_dir"]) / momlib.SERVER_EXE_REL).resolve()
            )
            return executable.casefold() == expected.casefold()
        return (
            "--backend-child" in command or "backend.py" in command.casefold()
        ) and (
            Path(executable).name.casefold()
            in {"momservermanager.exe", "python.exe", "pythonw.exe"}
        )

    def _backend_pid_on_port(self):
        port = momlib.validate_port(self.settings["backend_port"])
        script = (
            "$c=Get-NetTCPConnection -State Listen -LocalPort "
            + str(port)
            + " -ErrorAction SilentlyContinue | Select-Object -First 1; "
            "if($c){$c.OwningProcess}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            pid = int(result.stdout.strip())
        except ValueError:
            return None
        # Acepta tanto el hijo empaquetado como el backend.py legado, pero no
        # termina una aplicacion ajena que casualmente use el mismo puerto.
        info_script = (
            "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "
            + str(pid)
            + "'; if($p){$p.CommandLine}"
        )
        info = subprocess.run(
            ["powershell", "-NoProfile", "-Command", info_script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        command = info.stdout.casefold()
        if "--backend-child" in command or "backend.py" in command:
            return pid
        return None

    def _terminate(self, process, saved_pid=None, kind="server"):
        if process and process.poll() is None:
            process.terminate()
            return True
        if saved_pid and self._saved_process_matches(saved_pid, kind):
            try:
                os.kill(int(saved_pid), signal.SIGTERM)
                return True
            except (OSError, ValueError):
                pass
        return False

    def stop(self, restart_after=False):
        self.stopping = True
        try:
            settings = self._validated_settings()
            try:
                backup = momlib.backup_server_saves(settings["server_dir"])
                self.log(f"Pre-shutdown backup: {backup}")
            except (ValueError, OSError) as exc:
                self.log(f"Could not create the pre-shutdown backup: {exc}")
            runtime = _read_runtime()
            stopped_server = self._terminate(
                self.server_process, runtime.get("server_pid"), "server"
            )
            time.sleep(0.5)
            backend_pid = runtime.get("backend_pid") or self._backend_pid_on_port()
            stopped_backend = self._terminate(
                self.backend_process, backend_pid, "backend"
            )
            _write_runtime({})
            self.server_process = self.backend_process = None
            self.console_visible = False
            self.console_button.configure(text="Show console")
            self.log(
                f"Stopped: server={'yes' if stopped_server else 'not found'}, "
                f"backend={'yes' if stopped_backend else 'not found'}."
            )
            self.refresh()
            if restart_after:
                self.root.after(1200, self.start)
        except (ValueError, OSError) as exc:
            self.error("Could not stop", exc)
        finally:
            self.stopping = False

    def restart(self):
        self.log("Restarting server...")
        self.stop(restart_after=True)

    def backup(self):
        try:
            settings = self._validated_settings()
            target = momlib.backup_server_saves(settings["server_dir"])
            self.log(f"Backup created: {target}")
        except (ValueError, OSError) as exc:
            self.error("Backup", exc)

    def open_config(self):
        ServerConfigDialog(self)

    def open_data(self):
        path = momlib.app_data_dir()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)
        except OSError as exc:
            self.error("Data folder", exc)

    def open_server_log(self):
        path = (
            Path(self.settings["server_dir"])
            / "Game"
            / "Saved"
            / "Logs"
            / "Game.log"
        )
        try:
            if not path.is_file():
                raise momlib.ConfigError(
                    "Game.log does not exist yet; start the server at least once."
                )
            os.startfile(path)
        except (ValueError, OSError) as exc:
            self.error("Server log", exc)

    def error(self, title, error):
        from tkinter import messagebox

        self.log(f"ERROR: {error}")
        messagebox.showerror(title, str(error), parent=self.root)

    def on_close(self):
        runtime = _read_runtime()
        active = any(
            process and process.poll() is None
            for process in (self.server_process, self.backend_process)
        ) or self._saved_process_matches(runtime.get("server_pid"), "server")
        if active:
            from tkinter import messagebox

            answer = messagebox.askyesnocancel(
                "Close manager",
                "Stop the server too?\n\nYes: stop and close.\nNo: leave it running.",
                parent=self.root,
            )
            if answer is None:
                return
            if answer:
                self.stop()
        self.closing = True
        for after_id in (self.refresh_after, self.server_log_after):
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except self.tk.TclError:
                    pass
        self.root.destroy()


def _acquire_single_instance():
    if os.name != "nt":
        return True
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Local\\MoMRevivalServerManager"
    )
    # Keep the handle alive for the lifetime of the process.
    globals()["_MUTEX_HANDLE"] = handle
    return ctypes.windll.kernel32.GetLastError() != 183


def gui_main():
    import tkinter as tk
    from tkinter import messagebox

    if not _acquire_single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "MoM Server Manager",
            "The server manager is already open.",
            parent=root,
        )
        root.destroy()
        return 0

    root = tk.Tk()
    ServerManager(root)
    root.mainloop()
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--backend-child":
        if sys.stdout is None:
            log_path = momlib.app_data_dir() / "backend-console.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            sys.stdout = open(  # noqa: SIM115
                log_path, "a", encoding="utf-8", buffering=1
            )
        if sys.stderr is None:
            sys.stderr = sys.stdout
        return backend.main(argv[1:]) or 0
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
