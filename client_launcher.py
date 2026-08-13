"""Permanent client launcher used by Steam and the configurator."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CLIENT_EXE_REL = Path("MarsClient/Game/Binaries/Win64/MemoriesOfMars.exe")
STEAM_APP_ID = "644290"


def _data_dir() -> Path:
    root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(root) / "MoMRevival"


def _settings() -> dict:
    path = _data_dir() / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _log(message: str) -> None:
    try:
        path = _data_dir() / "client-launcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


def _error(message: str) -> int:
    _log(f"ERROR: {message}")
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None, message, "Memories of Mars Revival", 0x10
        )
    return 1


def _game_root() -> Path:
    # Instalado como <juego>/Launch_Game.exe. Durante desarrollo tambien admite
    # MOM_GAME_DIR para poder probar el lanzador sin copiarlo sobre Steam.
    override = os.environ.get("MOM_GAME_DIR")
    return Path(override).resolve() if override else Path(sys.executable).resolve().parent


def _restore_system_dll_search() -> None:
    """Prevent an external game process from loading DLLs from PyInstaller."""
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
    kernel32.SetDllDirectoryW.restype = ctypes.c_int
    if not kernel32.SetDllDirectoryW(None):
        code = ctypes.get_last_error()
        raise OSError(code, "Windows could not restore the system DLL search path")


def _set_affinity(process: subprocess.Popen, mask: int) -> None:
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.SetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    kernel32.SetProcessAffinityMask.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x0200 | 0x0400, False, process.pid)
    if not handle:
        raise OSError("Windows no permitio abrir el proceso para ajustar su CPU")
    try:
        if not kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(mask)):
            raise OSError("Windows no permitio ajustar la afinidad de CPU")
    finally:
        kernel32.CloseHandle(handle)


def main() -> int:
    root = _game_root()
    exe = root / CLIENT_EXE_REL
    if not exe.is_file():
        return _error(f"The game client was not found:\n{exe}")

    settings = _settings()
    env = os.environ.copy()
    # A direct launch must provide the same app context Steam supplies when it
    # starts Launch_Game.exe. Steam client updates can otherwise leave the old
    # Steamworks SDK with AppId 0 and the abandoned game crashes during init.
    env["SteamAppId"] = STEAM_APP_ID
    env["SteamGameId"] = STEAM_APP_ID
    if settings.get("openssl_compat", False):
        env["OPENSSL_ia32cap"] = ":~0x20000000"

    try:
        # PyInstaller points child processes at its one-file extraction folder
        # unless the normal Windows DLL search path is restored first. Without
        # this, the game keeps _MEI...\VCRUNTIME140.dll loaded and the launcher
        # cannot remove its temporary directory when it exits.
        _restore_system_dll_search()
        game = subprocess.Popen(
            [str(exe), "-NoEAC", "-console"], cwd=str(exe.parent), env=env
        )
    except OSError as exc:
        return _error(f"The game could not be started:\n{exc}")

    logical = os.cpu_count() or 1
    limit_cpu = settings.get("limit_client_cpu", True) and logical > 8
    if limit_cpu:
        try:
            load_cores = max(1, min(int(settings.get("client_load_cores", 4)), logical))
            _set_affinity(game, (1 << load_cores) - 1)
            _log(f"Cliente {game.pid}: afinidad limitada a {load_cores} hilos")
            try:
                game.wait(timeout=max(15, int(settings.get("client_load_seconds", 75))))
                _log(f"Cliente {game.pid}: finalizo durante la carga ({game.returncode})")
                return int(game.returncode or 0)
            except subprocess.TimeoutExpired:
                pointer_bits = ctypes.sizeof(ctypes.c_size_t) * 8
                _set_affinity(game, (1 << min(logical, pointer_bits)) - 1)
                _log(f"Cliente {game.pid}: afinidad completa restaurada")
        except (OSError, ValueError) as exc:
            _log(f"Aviso de afinidad: {exc}")
    else:
        _log(f"Cliente {game.pid}: iniciado sin EAC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
