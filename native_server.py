"""Console-first launcher that preserves Memories of Mars native server config."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import backend
import momlib
import redirect_urls


def _backend_args(settings):
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
    return args


def _backend_command(settings):
    args = _backend_args(settings)
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-u", str(Path(__file__).resolve()), *args]


def _admin_url(settings):
    return (
        f"http://127.0.0.1:{settings['backend_port']}"
        f"/r/{settings['access_key']}/s/AdminStatus"
    )


def _compatible_backend(settings):
    try:
        with urllib.request.urlopen(_admin_url(settings), timeout=1.0) as response:
            data = json.load(response)
        return data.get("result") == "ok" and data.get("api_version") == 1
    except (OSError, ValueError, urllib.error.HTTPError):
        return False


def _port_is_listening(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except OSError:
        return False


def _start_backend(settings):
    if _compatible_backend(settings):
        print("Using the compatible Relive backend that is already running.")
        return None
    if _port_is_listening(settings["backend_port"]):
        raise momlib.ConfigError(
            f"Port {settings['backend_port']} is occupied by another service or by "
            "a Relive backend configured with a different key."
        )
    kwargs = {}
    if os.name == "posix":
        # Keep the backend outside the terminal foreground process group. On
        # Ctrl+C the launcher must stop the world first so its final session
        # update and save requests can still reach the backend.
        kwargs["start_new_session"] = True
    process = subprocess.Popen(_backend_command(settings), **kwargs)
    for _ in range(50):
        if process.poll() is not None:
            raise OSError(f"The Relive backend exited with code {process.returncode}")
        if _compatible_backend(settings):
            return process
        time.sleep(0.2)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    raise OSError("The Relive backend did not become ready in time")


def _settings_from_options(options):
    settings = momlib.load_settings()
    server_port = (
        options.port
        if options.port is not None
        else settings.get("server_backend_port", settings["backend_port"])
    )
    server_key = (
        options.key
        if options.key is not None
        else settings.get("server_access_key", settings["access_key"])
    )
    overrides = {
        "server_dir": options.server_dir,
        "server_backend_host": options.backend_host,
        "backend_bind": options.bind,
        "public_ip": options.public_ip,
    }
    settings.update({key: value for key, value in overrides.items() if value is not None})
    if options.allow_cloning:
        settings["skip_cloning"] = False
    if options.disable_openssl_fix:
        settings["server_openssl_compat"] = False
    settings["backend_port"] = momlib.validate_port(server_port)
    settings["access_key"] = momlib.validate_key(server_key)
    settings["server_backend_port"] = settings["backend_port"]
    settings["server_access_key"] = settings["access_key"]
    settings["backend_bind"] = str(settings["backend_bind"]).strip()
    settings["server_backend_host"] = str(settings["server_backend_host"]).strip()
    if not settings["backend_bind"] or not settings["server_backend_host"]:
        raise momlib.ConfigError("Backend listen and server addresses cannot be empty")
    if settings.get("public_ip"):
        settings["public_ip"] = momlib.check_public_ip(str(settings["public_ip"]))
    return settings


def _prepare(settings):
    if not settings.get("server_dir"):
        raise momlib.ConfigError(
            "The dedicated server was not found. Configure it in Server Manager or "
            "pass --server-dir."
        )
    result = momlib.apply_server_compatibility(
        settings["server_dir"],
        settings["server_backend_host"],
        settings["backend_port"],
        settings["access_key"],
        skip_cloning=settings.get("skip_cloning", True),
    )
    print(f"Relive compatibility applied: {result['url']}")
    print(f"Native server settings preserved in: {result['config']}")
    return result


def _restore_system_dll_search():
    if os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
    kernel32.SetDllDirectoryW.restype = ctypes.c_int
    if not kernel32.SetDllDirectoryW(None):
        raise OSError(
            ctypes.get_last_error(),
            "Windows could not restore the system DLL search path",
        )


def _run_server(settings, extra_args, *, auto_restart=False):
    command, cwd, layout = momlib.server_launch_spec(
        settings["server_dir"], extra_args
    )
    _restore_system_dll_search()
    print(f"Starting native {layout.platform} dedicated server: {command[0]}")
    if settings.get("server_openssl_compat", True):
        print("Legacy OpenSSL compatibility is enabled.")
    kwargs = {
        "cwd": str(cwd),
        "env": momlib.server_environment(settings),
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    while True:
        process = subprocess.Popen(command, **kwargs)
        try:
            return_code = process.wait()
        except KeyboardInterrupt:
            print("\nStopping the dedicated server...")
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            return process.wait()
        if not auto_restart:
            return return_code
        print(
            f"The world exited with code {return_code}; restarting in 10 seconds."
        )
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            print("\nAutomatic restart cancelled.")
            return 130


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Apply Relive compatibility, start the backend, and run the dedicated "
            "server while preserving DedicatedServerConfig.cfg as native configuration."
        )
    )
    parser.add_argument("--server-dir")
    parser.add_argument("--backend-host", help="backend address seen by the server")
    parser.add_argument("--bind", help="backend listen address")
    parser.add_argument("--port", type=int)
    parser.add_argument("--key", help="shared Relive access key")
    parser.add_argument("--public-ip")
    parser.add_argument("--allow-cloning", action="store_true")
    parser.add_argument("--disable-openssl-fix", action="store_true")
    parser.add_argument(
        "--no-auto-restart",
        action="store_true",
        help="do not relaunch the Linux world after its scheduled daily exit",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--prepare-only",
        action="store_true",
        help="apply compatibility without starting any process",
    )
    mode.add_argument(
        "--backend-only",
        action="store_true",
        help="run only the Relive backend for an independently launched server",
    )
    mode.add_argument(
        "--restore",
        action="store_true",
        help="restore the native server binary and managed configuration changes",
    )
    parser.add_argument(
        "server_args",
        nargs=argparse.REMAINDER,
        help="arguments after -- are passed to the native dedicated server",
    )
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--backend-child":
        return backend.main(argv[1:]) or 0

    options = build_parser().parse_args(argv)
    backend_process = None
    try:
        settings = _settings_from_options(options)
        # The Linux release has no GUI manager to create config.json. Persist
        # the discovered directory, generated key and explicit CLI overrides
        # so subsequent launches keep the same client/server contract.
        momlib.save_settings(settings)
        if options.restore:
            if not settings.get("server_dir"):
                raise momlib.ConfigError(
                    "The dedicated server was not found; pass --server-dir."
                )
            result = momlib.restore_server(settings["server_dir"])
            print(
                "Native server compatibility restored."
                if result["binary_restored"]
                else "No native server binary backup was found."
            )
            return 0
        if options.backend_only:
            return backend.run_server(
                settings["backend_bind"],
                settings["backend_port"],
                settings["access_key"],
                momlib.app_data_dir(),
                settings.get("public_ip", ""),
            ) or 0
        prepared = _prepare(settings)
        if options.prepare_only:
            return 0
        backend_process = _start_backend(settings)
        server_args = list(options.server_args)
        if server_args[:1] == ["--"]:
            server_args.pop(0)
        auto_restart = (
            prepared.get("platform") == "linux" and not options.no_auto_restart
        )
        return _run_server(settings, server_args, auto_restart=auto_restart)
    except (ValueError, OSError, redirect_urls.PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if backend_process and backend_process.poll() is None:
            print("Stopping the Relive backend...")
            backend_process.terminate()
            try:
                backend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_process.kill()
                backend_process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
