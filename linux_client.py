"""Prepare and launch the Windows Memories of Mars client through Proton."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import momlib
import redirect_urls

STEAM_APP_ID = "644290"


def _compat_root(value=None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.name == "pfx":
            path = path.parent
        if (path / "pfx").is_dir():
            return path
        raise momlib.ConfigError(f"Could not find a Proton pfx under {path}")
    for steam in momlib.steam_roots():
        path = steam / "steamapps/compatdata" / STEAM_APP_ID
        if (path / "pfx").is_dir():
            return path.resolve()
    raise momlib.ConfigError(
        "The Memories of Mars Proton prefix was not found. Start the game once "
        "from Steam or pass --compat-dir."
    )


def _proton_path(value=None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_file():
            return path
        raise momlib.ConfigError(f"The Proton launcher was not found: {path}")
    candidates = []
    for steam in momlib.steam_roots():
        common = steam / "steamapps/common"
        preferred = common / "Proton - Experimental/proton"
        if preferred.is_file():
            candidates.append(preferred)
        candidates.extend(
            path
            for path in common.glob("*Proton*/proton")
            if path.is_file() and path != preferred
        )
    if not candidates:
        raise momlib.ConfigError("Proton was not found; pass --proton.")
    return candidates[0].resolve()


def _client_ini(compat_root: Path) -> Path:
    users = compat_root / "pfx/drive_c/users"
    preferred = users / "steamuser/AppData/Local"
    local = preferred if preferred.is_dir() else None
    if local is None and users.is_dir():
        local = next(
            (path / "AppData/Local" for path in users.iterdir() if (path / "AppData/Local").is_dir()),
            None,
        )
    if local is None:
        local = preferred
    return local / "MemoriesOfMars/Saved/Config/WindowsNoEditor/Engine.ini"


def _steam_root(proton: Path) -> Path:
    for parent in proton.parents:
        if parent.name == "steamapps":
            return parent.parent
    raise momlib.ConfigError(f"Could not determine the Steam root from {proton}")


def _prefix_processes(compat_root: Path):
    marker = b"STEAM_COMPAT_DATA_PATH=" + os.fsencode(str(compat_root))
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environment = (entry / "environ").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if marker in environment:
            yield int(entry.name)


def _process_identity(pid):
    """Return (Windows executable name, Linux process state) for a prefix PID."""
    try:
        argv0 = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0", 1)[0]
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except (OSError, PermissionError, IndexError):
        return "", ""
    name = os.fsdecode(argv0).replace("\\", "/").rsplit("/", 1)[-1].lower()
    # The command name may contain spaces and parentheses, so split after its
    # final closing parenthesis. The next field is the one-letter state.
    state_fields = stat.rsplit(")", 1)[-1].strip().split()
    return name, state_fields[0] if state_fields else ""


def _stop_prefix_processes(process, compat_root, grace_seconds=2.0):
    """Stop the launcher and Wine processes after the game itself has exited."""
    targets = set(_prefix_processes(compat_root))
    targets.discard(os.getpid())
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    remaining = targets
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        remaining = {
            pid
            for pid in _prefix_processes(compat_root)
            if pid != os.getpid() and _process_identity(pid)[1] not in {"", "Z"}
        }
        if not remaining:
            return
        time.sleep(0.1)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _watch_game_process(process, compat_root, stop_event, interval=0.5):
    """Prevent a dead Windows game from leaving the Proton wrapper waiting."""
    game_seen = False
    while not stop_event.wait(interval):
        if process.poll() is not None:
            return
        live_game = False
        for pid in _prefix_processes(compat_root):
            name, state = _process_identity(pid)
            if name == "memoriesofmars.exe" and state and state != "Z":
                game_seen = True
                live_game = True
                break
        if game_seen and not live_game:
            print("The game process exited; cleaning up the Proton session.")
            _stop_prefix_processes(process, compat_root)
            return


def _restore_prefix_affinity(launcher_pid, compat_root, available_cpus):
    restored = 0
    for pid in {launcher_pid, *_prefix_processes(compat_root)}:
        try:
            os.sched_setaffinity(pid, available_cpus)
            restored += 1
        except (OSError, ProcessLookupError):
            pass
    if restored:
        print(f"Client CPU affinity restored for {restored} Proton process(es).")


def _limit_cpu_during_load(process, compat_root, settings):
    if not settings.get("linux_limit_client_cpu", False) or not hasattr(os, "sched_setaffinity"):
        return None
    available_cpus = sorted(os.sched_getaffinity(0))
    if len(available_cpus) <= 8:
        return None
    load_cores = max(
        1,
        min(int(settings.get("client_load_cores", 4)), len(available_cpus)),
    )
    load_seconds = max(15, int(settings.get("client_load_seconds", 75)))
    os.sched_setaffinity(process.pid, available_cpus[:load_cores])
    timer = threading.Timer(
        load_seconds,
        _restore_prefix_affinity,
        args=(process.pid, compat_root, available_cpus),
    )
    timer.daemon = True
    timer.start()
    print(
        f"Client startup limited to {load_cores} logical CPUs for "
        f"{load_seconds} seconds."
    )
    return timer


def _launch(
    client_dir: Path,
    compat_root: Path,
    proton: Path,
    settings,
    extra_args,
    diagnostics=False,
):
    exe = client_dir / momlib.CLIENT_EXE_REL
    env = os.environ.copy()
    env.update(
        {
            "STEAM_COMPAT_DATA_PATH": str(compat_root),
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(_steam_root(proton)),
            "SteamAppId": STEAM_APP_ID,
            "SteamGameId": STEAM_APP_ID,
        }
    )
    if settings.get("linux_disable_nvapi", True):
        # Proton 9+ enables DXVK-NVAPI for all titles. Memories of Mars is a
        # D3D11 game and does not need it; on AMD it can recurse while the old
        # UE4 render thread loads assets and terminate the game.
        env["PROTON_DISABLE_NVAPI"] = "1"
        print("Proton NVAPI compatibility layer disabled for this game.")
    else:
        env.pop("PROTON_DISABLE_NVAPI", None)
    if diagnostics:
        diagnostic_dir = momlib.app_data_dir() / "diagnostics"
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        env["PROTON_LOG"] = "1"
        env["PROTON_LOG_DIR"] = str(diagnostic_dir)
        env["PROTON_CRASH_REPORT_DIR"] = str(diagnostic_dir)
        print(f"Proton diagnostics enabled: {diagnostic_dir}")
    if settings.get("openssl_compat", False):
        env["OPENSSL_ia32cap"] = ":~0x20000000"
    command = [str(proton), "run", str(exe), "-NoEAC", "-console", *extra_args]
    print(f"Starting the Proton client: {exe}")
    process = subprocess.Popen(
        command,
        cwd=str(exe.parent),
        env=env,
        start_new_session=True,
    )
    affinity_timer = None
    watcher_stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_game_process,
        args=(process, compat_root, watcher_stop),
        daemon=True,
    )
    watcher.start()
    try:
        affinity_timer = _limit_cpu_during_load(process, compat_root, settings)
    except (OSError, ValueError) as exc:
        print(f"CPU affinity warning: {exc}", file=sys.stderr)
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping the Proton client...")
        _stop_prefix_processes(process, compat_root)
        return process.wait()
    finally:
        watcher_stop.set()
        if affinity_timer is not None:
            affinity_timer.cancel()
            _restore_prefix_affinity(
                process.pid, compat_root, sorted(os.sched_getaffinity(0))
            )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Patch and launch the Memories of Mars client through Proton."
    )
    parser.add_argument("--client-dir")
    parser.add_argument("--compat-dir", help="Steam compatdata/644290 directory")
    parser.add_argument("--proton", help="path to Proton's proton script")
    parser.add_argument("--host", help="Relive backend address seen by the client")
    parser.add_argument("--port", type=int)
    parser.add_argument("--key", help="shared Relive access key")
    cpu = parser.add_mutually_exclusive_group()
    cpu.add_argument(
        "--limit-cpu",
        dest="limit_cpu",
        action="store_true",
        help="temporarily use fewer CPUs during startup (disabled by default)",
    )
    cpu.add_argument(
        "--no-cpu-limit",
        dest="limit_cpu",
        action="store_false",
        help="disable the optional startup CPU workaround",
    )
    parser.set_defaults(limit_cpu=None)
    nvapi = parser.add_mutually_exclusive_group()
    nvapi.add_argument(
        "--disable-nvapi",
        dest="disable_nvapi",
        action="store_true",
        help="disable Proton's NVAPI layer (default; fixes an AMD render crash)",
    )
    nvapi.add_argument(
        "--enable-nvapi",
        dest="disable_nvapi",
        action="store_false",
        help="allow Proton's NVAPI layer, mainly for troubleshooting",
    )
    parser.set_defaults(disable_nvapi=None)
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="write a detailed Proton log and crash reports",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--restore", action="store_true")
    parser.add_argument("client_args", nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    options = build_parser().parse_args(argv)
    try:
        settings = momlib.load_settings()
        found_client, _server = momlib.discover_installs()
        client_dir = Path(options.client_dir or settings.get("client_dir") or found_client or "").expanduser().resolve()
        if not (client_dir / momlib.CLIENT_EXE_REL).is_file():
            raise momlib.ConfigError("The Steam game client was not found; pass --client-dir.")
        compat_root = _compat_root(options.compat_dir or settings.get("proton_compat_dir"))
        proton = _proton_path(options.proton or settings.get("proton_path"))
        host = str(options.host or settings.get("client_backend_host") or "127.0.0.1")
        port = momlib.validate_port(
            options.port
            if options.port is not None
            else settings.get("client_backend_port", settings.get("backend_port", 8080))
        )
        key = momlib.validate_key(
            options.key
            if options.key is not None
            else settings.get("client_access_key", settings.get("access_key", "mom1"))
        )
        ini = _client_ini(compat_root)
        settings.update(
            {
                "client_dir": str(client_dir),
                "client_backend_host": host,
                "client_backend_port": port,
                "client_access_key": key,
                "proton_compat_dir": str(compat_root),
                "proton_path": str(proton),
            }
        )
        if options.limit_cpu is not None:
            settings["linux_limit_client_cpu"] = options.limit_cpu
        if options.disable_nvapi is not None:
            settings["linux_disable_nvapi"] = options.disable_nvapi
        momlib.save_settings(settings)
        if options.restore:
            result = momlib.restore_client(client_dir, ini_path=ini)
            print(
                "Proton client compatibility restored."
                if result["binary_restored"]
                else "No client binary backup was found."
            )
            return 0
        result = momlib.apply_client(client_dir, host, port, key, ini_path=ini)
        print(f"Proton client prepared: {result['url']}")
        print(f"Unreal configuration: {ini}")
        if options.prepare_only:
            return 0
        client_args = list(options.client_args)
        if client_args[:1] == ["--"]:
            client_args.pop(0)
        return _launch(
            client_dir,
            compat_root,
            proton,
            settings,
            client_args,
            diagnostics=options.diagnostics,
        )
    except (ValueError, OSError, redirect_urls.PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
