"""Memories of Mars Relive installation and configuration core.

No depende de paquetes externos. Todas las operaciones son idempotentes y se
pueden dirigir a carpetas de prueba para no tocar una instalacion real.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import redirect_urls

APP_NAME = "MoM Revival"
PROJECT_URL = "https://github.com/drbermejor/MoM-Relive"
LATEST_RELEASE_API = "https://api.github.com/repos/drbermejor/MoM-Relive/releases/latest"
CLIENT_EXE_REL = Path("MarsClient/Game/Binaries/Win64/MemoriesOfMars.exe")
CLIENT_LAUNCHER_REL = Path("Launch_Game.exe")
SERVER_CFG_REL = Path("DedicatedServerConfig.cfg")
SERVER_SAVE_REL = Path("Game/Saved/DB")
WINDOWS_SERVER_EXE_REL = Path("Game/Binaries/Win64/MemoriesOfMarsServer.exe")
WINDOWS_SERVER_ENGINE_REL = Path("Game/Saved/Config/WindowsServer/Engine.ini")
WINDOWS_SERVER_GAME_REL = Path("Game/Saved/Config/WindowsServer/Game.ini")
LINUX_SERVER_EXE_REL = Path("Game/Binaries/Linux/MemoriesOfMarsServer")
LINUX_SERVER_ENGINE_REL = Path("Game/Saved/Config/LinuxServer/Engine.ini")
LINUX_SERVER_GAME_REL = Path("Game/Saved/Config/LinuxServer/Game.ini")
# Aliases kept for the Windows manager and existing third-party scripts.
SERVER_EXE_REL = WINDOWS_SERVER_EXE_REL
SERVER_ENGINE_REL = WINDOWS_SERVER_ENGINE_REL
SERVER_GAME_REL = WINDOWS_SERVER_GAME_REL


def project_document(name: str) -> Path:
    """Locate an installed project notice without accepting arbitrary paths."""
    allowed = {"LEGAL.md", "LICENSE", "COPYRIGHT", "THIRD-PARTY-NOTICES.md"}
    if name not in allowed:
        raise ConfigError("Unsupported project document")
    root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return root / name


def open_project_document(name: str = "LEGAL.md") -> Path:
    path = project_document(name)
    if not path.is_file():
        raise ConfigError(f"Project notice was not installed: {path}")
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
    return path
LIMBIC_SECTION = "OnlineSubsystemLimbic"
CLONE_SECTIONS = (
    "/Script/ShooterGame.MarsGameMode",
    "/Script/ShooterGame.MarsGameState",
    "/Script/ShooterGame.MarsPlayerController",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServerLayout:
    platform: str
    exe_rel: Path
    engine_rel: Path
    game_rel: Path


WINDOWS_SERVER_LAYOUT = ServerLayout(
    "windows",
    WINDOWS_SERVER_EXE_REL,
    WINDOWS_SERVER_ENGINE_REL,
    WINDOWS_SERVER_GAME_REL,
)
LINUX_SERVER_LAYOUT = ServerLayout(
    "linux",
    LINUX_SERVER_EXE_REL,
    LINUX_SERVER_ENGINE_REL,
    LINUX_SERVER_GAME_REL,
)


def server_layout(server_dir) -> tuple[Path, ServerLayout]:
    """Resolve a Windows or native Linux dedicated-server installation."""
    root = Path(server_dir).expanduser().resolve()
    layouts = (
        (LINUX_SERVER_LAYOUT, WINDOWS_SERVER_LAYOUT)
        if os.name == "posix"
        else (WINDOWS_SERVER_LAYOUT, LINUX_SERVER_LAYOUT)
    )
    for layout in layouts:
        if (root / layout.exe_rel).is_file():
            return root, layout
    expected = " or ".join(str(root / layout.exe_rel) for layout in layouts)
    raise ConfigError(f"Could not find the dedicated server: {expected}")


def server_launch_spec(server_dir, extra_args=()) -> tuple[list[str], Path, ServerLayout]:
    """Return the native command and working directory for the server platform."""
    root, layout = server_layout(server_dir)
    exe = root / layout.exe_rel
    if layout.platform == "linux":
        # MemoriesOfMarsServer.sh supplies the project name before user args.
        command = [str(exe), "Game", "-log", *extra_args]
        cwd = root
    else:
        command = [str(exe), "-log", *extra_args]
        cwd = exe.parent
    return command, cwd, layout


def app_data_dir() -> Path:
    if os.name == "posix":
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
        return Path(root) / "MoMRevival"
    root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(root) / "MoMRevival"


def client_engine_ini() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "MemoriesOfMars/Saved/Config/WindowsNoEditor/Engine.ini"


def default_settings() -> dict:
    client, server = discover_installs()
    worlds = discover_server_worlds(server) if server else []
    server_id = worlds[0]["server_id"] if worlds else "mom_revival_01"
    return {
        "client_dir": str(client or ""),
        "server_dir": str(server or ""),
        "client_backend_host": "127.0.0.1",
        "server_backend_host": "127.0.0.1",
        "backend_bind": "0.0.0.0",
        "backend_port": 8080,
        "access_key": secrets.token_hex(4),
        "limit_client_cpu": True,
        "openssl_compat": False,
        "client_load_cores": 4,
        "client_load_seconds": 75,
        "server_name": "Memories of Mars Revival",
        "server_password": "",
        "server_id": server_id,
        "public_ip": "",
        "max_players": 8,
        "admin_id": "",
        "skip_cloning": True,
        "server_openssl_compat": True,
    }


def discover_server_worlds(server_dir) -> list[dict]:
    """Lista las partidas locales, priorizando la que contiene mas datos."""
    if not server_dir:
        return []
    db = Path(server_dir).expanduser() / "Game" / "Saved" / "DB"
    if not db.is_dir():
        return []
    worlds = []
    for folder in db.glob("Server*"):
        if not folder.is_dir() or len(folder.name) <= len("Server"):
            continue
        files = [path for path in folder.rglob("*") if path.is_file()]
        player_files = [path for path in files if "PlayerData" in path.parts]
        player_ids = {
            path.parts[path.parts.index("PlayerData") + 1]
            for path in player_files
            if "PlayerData" in path.parts
            and len(path.parts) > path.parts.index("PlayerData") + 1
        }
        worlds.append(
            {
                "server_id": folder.name[len("Server") :],
                "players": len(player_ids),
                "player_files": len(player_files),
                "files": len(files),
                "latest": max((path.stat().st_mtime for path in files), default=0),
                "path": str(folder),
            }
        )
    return sorted(
        worlds,
        key=lambda item: (
            item["players"],
            item["player_files"],
            item["files"],
            item["latest"],
        ),
        reverse=True,
    )


def load_settings(path: Path | None = None) -> dict:
    path = path or app_data_dir() / "config.json"
    defaults = default_settings()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                # Import only settings supported by this release. Obsolete or
                # unexpected values must not survive configuration migration.
                defaults.update(
                    {key: value for key, value in loaded.items() if key in defaults}
                )
        except (OSError, ValueError):
            pass
    return defaults


def save_settings(settings: dict, path: Path | None = None) -> Path:
    path = path or app_data_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return path


def steam_roots() -> list[Path]:
    roots: list[Path] = []
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
    ]
    if os.name == "posix":
        candidates = [
            Path.home() / ".local/share/Steam",
            Path.home() / ".steam/steam",
            Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
            Path.home() / "snap/steam/common/.local/share/Steam",
            *candidates,
        ]
    try:
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key_name in (
                r"Software\Valve\Steam",
                r"Software\WOW6432Node\Valve\Steam",
            ):
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        value, _ = winreg.QueryValueEx(key, "SteamPath")
                        candidates.append(Path(value))
                except OSError:
                    pass
    except ImportError:
        pass

    for steam in candidates:
        if steam not in roots and steam.exists():
            roots.append(steam)
        vdf = steam / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for value in re.findall(r'"path"\s+"([^"]+)"', text):
                    library = Path(value.replace("\\\\", "\\"))
                    if library not in roots:
                        roots.append(library)
            except OSError:
                pass
    return roots


def discover_installs() -> tuple[Path | None, Path | None]:
    client = server = None
    for root in steam_roots():
        common = root / "steamapps/common"
        c = common / "Memories of Mars"
        s = common / "Memories of Mars - Dedicated Server"
        if client is None and (c / CLIENT_EXE_REL).is_file():
            client = c
        if server is None:
            try:
                server_layout(s)
            except ConfigError:
                pass
            else:
                server = s
    return client, server


def validate_key(value: str) -> str:
    value = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,16}", value):
        raise ConfigError("The key must be 4-16 characters: letters, digits, _ or -")
    return value


def validate_port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ConfigError("The backend port must be a number") from None
    if not 1 <= port <= 65535:
        raise ConfigError("The port must be between 1 and 65535")
    return port


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value).strip())
    if not match:
        raise ConfigError(f"Invalid release version: {value}")
    return tuple(int(part) for part in match.groups())


def check_latest_release(current_version: str, timeout: float = 5.0) -> dict:
    """Query the official GitHub latest release without downloading anything."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MoM-Relive/{current_version}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    latest = str(payload.get("tag_name") or "").strip()
    url = str(payload.get("html_url") or "").strip()
    release_url = urlsplit(url)
    if (
        not latest
        or release_url.scheme != "https"
        or release_url.hostname != "github.com"
        or release_url.port is not None
        or not release_url.path.startswith("/drbermejor/MoM-Relive/releases/")
    ):
        raise ConfigError("GitHub returned an invalid latest release")
    return {
        "current": str(current_version),
        "latest": latest.removeprefix("v"),
        "available": version_tuple(latest) > version_tuple(current_version),
        "url": url,
    }


def backend_url(host: str, port: int, key: str, identity: str) -> str:
    """URL compacta; debe caber en el hueco fijo de 60 caracteres del .exe."""
    host = str(host).strip().rstrip("/")
    if "://" in host:
        parsed = urlsplit(host)
        if parsed.scheme.lower() != "http" or not parsed.hostname:
            raise ConfigError(
                "The backend must use http:// (the game cannot use this TLS setup)"
            )
        host = parsed.hostname
    if not host or not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
        raise ConfigError("Nombre o IP del backend no valido")
    # Las literales IPv6 necesitan corchetes dentro de una URL.
    rendered_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    key = validate_key(key)
    port = validate_port(port)
    identity = str(identity)
    url = f"http://{rendered_host}:{port}/r/{key}/{identity}/"
    # La URL original mas corta ocupa 60 caracteres y necesita un NUL final.
    if len(url) > 60:
        raise ConfigError(
            f"La URL parcheada ocupa {len(url)} caracteres (maximo 60). "
            "Use an IP address, a shorter key, or a shorter ID."
        )
    return url


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        original_mode = path.stat().st_mode & 0o7777
    except OSError:
        original_mode = None
    fd, name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
        if original_mode is not None:
            os.chmod(path, original_mode)
    except Exception:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    wanted = f"[{section}]".casefold()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip().casefold()
        if stripped == wanted:
            start = i
        elif start is not None and stripped.startswith("[") and stripped.endswith("]"):
            return start, i
    return (start, len(lines)) if start is not None else None


def set_ini_key(path: Path, section: str, key: str, values: list[str]) -> None:
    lines = _read_text(path).splitlines()
    bounds = _section_bounds(lines, section)
    if bounds is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", *[f"{key}={v}" for v in values]])
    else:
        start, end = bounds
        rx = re.compile(rf"^\s*{re.escape(key)}\s*=", re.IGNORECASE)
        body = [line for line in lines[start + 1 : end] if not rx.match(line)]
        lines[start + 1 : end] = [*[f"{key}={v}" for v in values], *body]
    _write_text_atomic(path, "\n".join(lines).rstrip() + "\n")


def remove_ini_key(path: Path, section: str, key: str) -> None:
    if not path.exists():
        return
    lines = _read_text(path).splitlines()
    bounds = _section_bounds(lines, section)
    if bounds is None:
        return
    start, end = bounds
    rx = re.compile(rf"^\s*{re.escape(key)}\s*=", re.IGNORECASE)
    lines[start + 1 : end] = [
        line for line in lines[start + 1 : end] if not rx.match(line)
    ]
    # Retira una seccion que haya quedado completamente vacia.
    bounds = _section_bounds(lines, section)
    if bounds:
        start, end = bounds
        if not any(
            line.strip() and not line.lstrip().startswith((";", "#"))
            for line in lines[start + 1 : end]
        ):
            del lines[start:end]
    _write_text_atomic(path, "\n".join(lines).strip() + ("\n" if lines else ""))


def set_limbic_url(path: Path, url: str) -> None:
    # Manual fixes and older builds may have left duplicate Limbic sections.
    # Unreal can then consume an obsolete value even when the final section
    # looks correct. Remove BaseURL from every matching section first.
    lines = _read_text(path).splitlines()
    filtered = []
    in_section = False
    section_name = LIMBIC_SECTION.casefold()
    key_rx = re.compile(r"^\s*BaseURL\s*=", re.IGNORECASE)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].strip().casefold() == section_name
        if in_section and key_rx.match(line):
            continue
        filtered.append(line)
    if filtered != lines:
        _write_text_atomic(path, "\n".join(filtered).rstrip() + "\n")
    quoted = f'"{url}"'
    set_ini_key(path, LIMBIC_SECTION, "BaseURL", [quoted, quoted])


def client_ini_urls(path: Path) -> list[str]:
    """Return every BaseURL from all Limbic sections in Engine.ini."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Engine.ini was not found: {path}")
    values = []
    in_section = False
    section_name = LIMBIC_SECTION.casefold()
    key_rx = re.compile(r"^\s*BaseURL\s*=\s*(.*?)\s*$", re.IGNORECASE)
    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].strip().casefold() == section_name
            continue
        if not in_section:
            continue
        match = key_rx.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values.append(value)
    return values


def verify_client_ini(path: Path, expected_url: str) -> dict:
    """Verify the exact Engine.ini contract consumed by the game browser."""
    path = Path(path).expanduser().resolve()
    urls = client_ini_urls(path)
    if len(urls) != 2:
        raise ConfigError(
            f"{path} contains {len(urls)} Limbic BaseURL entries; expected exactly 2. "
            "Click Prepare / repair."
        )
    if urls != [expected_url, expected_url]:
        found = urls[0] if urls else "missing"
        raise ConfigError(
            f"{path} points to {found}, not the configured backend. "
            "Click Prepare / repair."
        )
    return {"ini": str(path), "url": expected_url, "base_urls": len(urls)}


def repair_client_ini(host, port, key, ini_path=None) -> dict:
    """Repair only the selected Windows-profile Engine.ini and verify it."""
    ini = Path(ini_path).expanduser() if ini_path else client_engine_ini()
    url = backend_url(host, port, key, "p")
    set_limbic_url(ini, url)
    result = verify_client_ini(ini, url)
    return result


def set_clone_fix(path: Path, enabled: bool) -> None:
    if enabled:
        set_ini_key(path, CLONE_SECTIONS[0], "bNeverSpawnInCloningFacility", ["True"])
        set_ini_key(path, CLONE_SECTIONS[0], "bAlwaysSpawnInCloningFacility", ["False"])
        for section in CLONE_SECTIONS[1:]:
            set_ini_key(path, section, "bNeverSpawnInCloningFacility", ["True"])
    else:
        for section in CLONE_SECTIONS:
            remove_ini_key(path, section, "bNeverSpawnInCloningFacility")
        remove_ini_key(path, CLONE_SECTIONS[0], "bAlwaysSpawnInCloningFacility")


def update_server_cfg(path: Path, updates: dict) -> None:
    if not path.is_file():
        raise ConfigError(f"Could not find {path}")
    try:
        cfg = json.loads(_read_text(path))
    except ValueError as exc:
        raise ConfigError(
            f"DedicatedServerConfig.cfg no es JSON valido: {exc}"
        ) from exc
    if not isinstance(cfg, dict):
        raise ConfigError("DedicatedServerConfig.cfg no contiene un objeto JSON")
    cfg.update({k: v for k, v in updates.items() if v is not None})
    _write_text_atomic(path, json.dumps(cfg, indent="\t", ensure_ascii=False) + "\n")


def _require_root(root: str | Path, exe_rel: Path, label: str) -> Path:
    root = Path(root).expanduser().resolve()
    if not (root / exe_rel).is_file():
        raise ConfigError(f"Could not find {label} under {root}")
    return root


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def install_client_launcher(client_dir, launcher_source) -> dict:
    """Sustituye el lanzador EAC de Steam conservando una copia reversible."""
    root = _require_root(client_dir, CLIENT_EXE_REL, "the client")
    source = Path(launcher_source).resolve()
    if not source.is_file():
        raise ConfigError(f"Could not find the Relive launcher: {source}")
    target = root / CLIENT_LAUNCHER_REL
    if not target.is_file():
        raise ConfigError(f"Could not find the Steam launcher: {target}")
    original = target.with_suffix(target.suffix + ".orig")
    marker = target.with_suffix(target.suffix + ".momrevival")

    current_hash = _file_hash(target)
    previous_patch_hash = ""
    try:
        previous_patch_hash = marker.read_text(encoding="ascii").strip()
    except OSError:
        pass

    # Si Steam ha restaurado o actualizado Launch_Game.exe, esa nueva version
    # pasa a ser la base restaurable. Si sigue nuestro lanzador, no pisamos .orig.
    if current_hash != previous_patch_hash:
        shutil.copy2(target, original)

    fd, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=root)
    os.close(fd)
    try:
        shutil.copy2(source, name)
        os.replace(name, target)
    except Exception:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise
    patched_hash = _file_hash(target)
    _write_text_atomic(marker, patched_hash + "\n")
    return {"launcher": str(target), "backup": str(original)}


def restore_client_launcher(client_dir) -> bool:
    root = Path(client_dir).expanduser().resolve()
    target = root / CLIENT_LAUNCHER_REL
    original = target.with_suffix(target.suffix + ".orig")
    marker = target.with_suffix(target.suffix + ".momrevival")
    if not original.is_file():
        return False
    shutil.copy2(original, target)
    try:
        marker.unlink()
    except FileNotFoundError:
        pass
    return True


def client_launcher_is_installed(client_dir) -> bool:
    root = Path(client_dir).expanduser()
    target = root / CLIENT_LAUNCHER_REL
    marker = target.with_suffix(target.suffix + ".momrevival")
    if not target.is_file() or not marker.is_file():
        return False
    try:
        return _file_hash(target) == marker.read_text(encoding="ascii").strip()
    except OSError:
        return False


def apply_client(
    client_dir,
    host,
    port,
    key,
    ini_path: Path | None = None,
    launcher_source: Path | None = None,
) -> dict:
    root = _require_root(client_dir, CLIENT_EXE_REL, "the client")
    ini = ini_path or client_engine_ini()
    url = backend_url(host, port, key, "p")
    set_limbic_url(ini, url)
    verification = verify_client_ini(ini, url)
    client_exe = root / CLIENT_EXE_REL
    try:
        binary_urls = redirect_urls.verify(client_exe, url)
        replaced = 0
    except redirect_urls.PatchError:
        replaced = redirect_urls.patch(client_exe, url)
        binary_urls = redirect_urls.verify(client_exe, url)
    launcher = install_client_launcher(root, launcher_source) if launcher_source else None
    return {
        "url": url,
        "binary_urls": replaced,
        "ini": str(ini),
        "ini_verified": verification["base_urls"] == 2,
        "binary_verified": binary_urls,
        "launcher": launcher,
    }


def verify_client_preparation(
    client_dir,
    host,
    port,
    key,
    ini_path: Path | None = None,
) -> dict:
    """Check the launcher and Engine.ini destination without changing files."""
    root = _require_root(client_dir, CLIENT_EXE_REL, "the client")
    if not client_launcher_is_installed(root):
        raise ConfigError("The Relive community launcher is not installed")
    ini = ini_path or client_engine_ini()
    url = backend_url(host, port, key, "p")
    result = verify_client_ini(ini, url)
    result["binary_urls"] = redirect_urls.verify(root / CLIENT_EXE_REL, url)
    return result


def close_windows_client_processes() -> bool:
    """Close only MemoriesOfMars.exe process trees after explicit UI approval."""
    if os.name != "nt":
        raise ConfigError("Closing the Windows game process is only available on Windows")
    completed = subprocess.run(
        ["taskkill.exe", "/F", "/T", "/IM", "MemoriesOfMars.exe"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 128:
        return False
    detail = (completed.stderr or completed.stdout or "taskkill failed").strip()
    raise OSError(detail)


def apply_server(
    server_dir,
    host,
    port,
    key,
    *,
    server_name=None,
    server_password=None,
    server_id=None,
    public_ip=None,
    max_players=None,
    admin_id=None,
    skip_cloning=True,
) -> dict:
    result = apply_server_compatibility(
        server_dir, host, port, key, skip_cloning=skip_cloning
    )
    root = Path(server_dir).expanduser().resolve()
    updates = {}
    # Password, IP publica y administradores deben poder vaciarse desde la UI.
    fields = {
        "ServerName": server_name if server_name not in (None, "") else None,
        "ServerPassword": server_password,
        "ServerID": server_id if server_id not in (None, "") else None,
        "PublicIP": public_ip,
        "MaxPlayers": int(max_players) if max_players not in (None, "") else None,
        "Admins": admin_id,
    }
    updates.update({k: v for k, v in fields.items() if v is not None})
    if updates:
        update_server_cfg(root / SERVER_CFG_REL, updates)
    return result


def apply_server_compatibility(
    server_dir,
    host,
    port,
    key,
    *,
    skip_cloning=True,
) -> dict:
    """Apply only Relive compatibility while preserving native world settings."""
    root, layout = server_layout(server_dir)
    url = backend_url(host, port, key, "s")
    set_limbic_url(root / layout.engine_rel, url)
    set_clone_fix(root / layout.game_rel, bool(skip_cloning))
    # EAC cannot be used with the retired official services. All other values
    # remain owned by DedicatedServerConfig.cfg and its native editing flow.
    update_server_cfg(root / SERVER_CFG_REL, {"EnableEAC": False})
    replaced = redirect_urls.patch(root / layout.exe_rel, url)
    return {
        "url": url,
        "binary_urls": replaced,
        "config": str(root / SERVER_CFG_REL),
        "platform": layout.platform,
    }


def server_environment(settings: dict, environ=None) -> dict:
    """Return an environment suitable for the legacy dedicated server."""
    env = dict(os.environ if environ is None else environ)
    if settings.get("server_openssl_compat", True):
        env["OPENSSL_ia32cap"] = ":~0x20000000"
    else:
        # The checkbox must also override a value inherited from the shell.
        env.pop("OPENSSL_ia32cap", None)
    return env


def restore_client(client_dir, ini_path: Path | None = None) -> dict:
    root = _require_root(client_dir, CLIENT_EXE_REL, "the client")
    ini = ini_path or client_engine_ini()
    remove_ini_key(ini, LIMBIC_SECTION, "BaseURL")
    restored = redirect_urls.restore(root / CLIENT_EXE_REL)
    launcher_restored = restore_client_launcher(root)
    return {
        "binary_restored": restored,
        "launcher_restored": launcher_restored,
        "ini": str(ini),
    }


def restore_server(server_dir) -> dict:
    root, layout = server_layout(server_dir)
    remove_ini_key(root / layout.engine_rel, LIMBIC_SECTION, "BaseURL")
    set_clone_fix(root / layout.game_rel, False)
    update_server_cfg(root / SERVER_CFG_REL, {"EnableEAC": True})
    restored = redirect_urls.restore(root / layout.exe_rel)
    return {"binary_restored": restored}


def backup_server_saves(server_dir, destination: Path | None = None) -> Path:
    root, _layout = server_layout(server_dir)
    source = root / SERVER_SAVE_REL
    if not source.is_dir():
        raise ConfigError(f"Todavia no hay partidas en {source}")
    destination = destination or app_data_dir() / "saves"
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    target = destination / stamp
    target.parent.mkdir(parents=True, exist_ok=True)
    counter = 2
    while target.exists():
        target = destination / f"{stamp}_{counter}"
        counter += 1
    shutil.copytree(source, target)
    return target


def local_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def check_public_ip(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        # El juego tambien admite nombres DNS; limitamos a una forma segura.
        if re.fullmatch(r"[A-Za-z0-9.-]+", value):
            return value
        raise ConfigError("PublicIP no es una IP ni un nombre DNS valido") from None


def detect_public_ip(timeout: float = 5.0) -> str:
    """Consulta la IPv4 publica sin bloquear indefinidamente la interfaz."""
    request = urllib.request.Request(
        "https://api.ipify.org",
        headers={"User-Agent": "MoMRevival/0.3"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = response.read(128).decode("ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ConfigError(f"Could not detect the public IP: {exc}") from exc
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ConfigError(
            "El servicio de IP publica devolvio una respuesta invalida"
        ) from exc
    if address.version != 4:
        raise ConfigError("No public IPv4 address was detected")
    return str(address)
