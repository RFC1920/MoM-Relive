"""Configure the Linux server and Proton client with one shared contract."""

from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import linux_client
import momlib
import native_server


def _prompt(label, default=""):
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or str(default or "")


def _prompt_validated(label, default, validator):
    while True:
        try:
            return validator(_prompt(label, default))
        except (ValueError, OSError) as exc:
            print(f"  Invalid value: {exc}")


def _validate_server_dir(value):
    path = Path(value).expanduser().resolve()
    momlib.server_layout(path)
    return str(path)


def _validate_public_host(value):
    value = momlib.check_public_ip(value)
    if not value:
        raise momlib.ConfigError("Enter the public IPv4 address or DNS name")
    return value


def _yes_no(label, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        choice = input(f"{label} [{hint}]: ").strip().lower()
        if not choice:
            return default
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
        print("  Please answer y or n.")


def _service_available():
    unit = Path.home() / ".config/systemd/user/mom-relive-server.service"
    return unit.is_file() and shutil.which("systemctl") is not None


def _start_service():
    completed = subprocess.run(
        ["systemctl", "--user", "enable", "--now", "mom-relive-server.service"],
        check=False,
    )
    if completed.returncode:
        raise OSError(
            "systemd could not start the service. Run: "
            "systemctl --user enable --now mom-relive-server"
        )


def server_wizard():
    """Interactive first-run preparation for a public native Linux server."""
    settings = momlib.load_settings()
    _client, discovered_server = momlib.discover_installs()
    default_server = settings.get("server_dir") or discovered_server or ""
    default_port = settings.get(
        "server_backend_port", settings.get("backend_port", 8080)
    )
    saved_key = settings.get("server_access_key", settings.get("access_key", ""))
    try:
        default_key = momlib.validate_key(saved_key)
    except (ValueError, OSError):
        default_key = secrets.token_hex(4)

    print("MoM Relive public server setup")
    print("================================")
    print("This prepares MoM Relive; the official Steam dedicated server must")
    print("already be installed. Existing worlds and native settings are preserved.\n")

    server_dir = _prompt_validated(
        "Official dedicated-server folder", default_server, _validate_server_dir
    )
    port = _prompt_validated("Public backend TCP port", default_port, momlib.validate_port)
    key = _prompt_validated("Shared key", default_key, momlib.validate_key)

    default_public = str(settings.get("public_ip") or "")
    if not default_public:
        print("Detecting public IPv4 address...")
        try:
            default_public = momlib.detect_public_ip()
        except (ValueError, OSError) as exc:
            print(f"  Automatic detection unavailable: {exc}")
    public_host = _prompt_validated(
        "Public IPv4 address or DNS name", default_public, _validate_public_host
    )

    print("\nConfiguration summary")
    print(f"  Server folder: {server_dir}")
    print("  Internal backend: 127.0.0.1")
    print("  Listen address: 0.0.0.0")
    print(f"  Public backend: {public_host}:{port}")
    print(f"  Shared key: {key}")
    try:
        confirmed = _yes_no("Apply this configuration?", default=True)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not confirmed:
        print("Setup cancelled; no changes were applied.")
        return 0

    result = native_server.main(
        [
            "--prepare-only",
            "--server-dir",
            server_dir,
            "--backend-host",
            "127.0.0.1",
            "--bind",
            "0.0.0.0",
            "--port",
            str(port),
            "--key",
            key,
            "--public-ip",
            public_host,
        ]
    )
    if result:
        return result

    started = False
    if _service_available():
        try:
            start_now = _yes_no("Enable and start the server service now?", default=True)
            if start_now:
                _start_service()
                started = True
        except (ValueError, OSError) as exc:
            print(f"  Service was not started: {exc}")

    print("\nServer preparation complete.")
    config_path = Path(server_dir) / momlib.SERVER_CFG_REL
    print(f"Edit {config_path} to set the server name and world rules.")
    print(f"Forward TCP {port}, UDP 7777 and UDP 15000 to this computer.")
    print("Give players these client values:")
    print(f"  Backend: {public_host}")
    print(f"  Port: {port}")
    print(f"  Shared key: {key}")
    if started:
        print("The systemd user service is enabled and running.")
        print('For boot without login, run once: sudo loginctl enable-linger "$USER"')
    else:
        print("Start manually with: mom-relive-server")
    return 0


def _add_value(argv, option, value):
    if value is not None:
        argv.extend([option, str(value)])


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Apply one Relive host, port and shared key to the native Linux "
            "server and the Windows client running through Proton."
        )
    )
    parser.add_argument("--host", help="backend address seen by both components")
    parser.add_argument("--server-host", help="override the server backend address")
    parser.add_argument("--client-host", help="override the client backend address")
    parser.add_argument("--bind", help="backend listen address")
    parser.add_argument("--port", type=int)
    parser.add_argument("--key", help="shared key written to both components")
    parser.add_argument("--server-dir")
    parser.add_argument("--client-dir")
    parser.add_argument("--compat-dir")
    parser.add_argument("--proton")
    parser.add_argument(
        "--wizard",
        action="store_true",
        help="run the interactive public-server setup wizard",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--server-only", action="store_true")
    scope.add_argument("--client-only", action="store_true")
    parser.add_argument("--restore", action="store_true")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv == ["--wizard"]:
        try:
            return server_wizard()
        except (EOFError, KeyboardInterrupt):
            print("\nSetup cancelled; no changes were applied.")
            return 130
    options = build_parser().parse_args(argv)
    if options.wizard:
        build_parser().error("--wizard cannot be combined with other options")
    server_args = ["--restore" if options.restore else "--prepare-only"]
    client_args = ["--restore" if options.restore else "--prepare-only"]

    server_host = options.server_host or options.host
    client_host = options.client_host or options.host
    _add_value(server_args, "--server-dir", options.server_dir)
    _add_value(server_args, "--backend-host", server_host)
    _add_value(server_args, "--bind", options.bind)
    _add_value(server_args, "--port", options.port)
    _add_value(server_args, "--key", options.key)

    _add_value(client_args, "--client-dir", options.client_dir)
    _add_value(client_args, "--compat-dir", options.compat_dir)
    _add_value(client_args, "--proton", options.proton)
    _add_value(client_args, "--host", client_host)
    _add_value(client_args, "--port", options.port)
    _add_value(client_args, "--key", options.key)

    if not options.client_only:
        result = native_server.main(server_args)
        if result:
            return result
    if not options.server_only:
        result = linux_client.main(client_args)
        if result:
            return result

    settings = momlib.load_settings()
    if options.restore:
        print("Selected Linux components restored.")
    else:
        if options.client_only:
            print("Linux client destination configured; server settings were preserved.")
            print(f"Host: {settings['client_backend_host']}")
            print(f"Port: {settings['client_backend_port']}")
            print(f"Shared key: {settings['client_access_key']}")
        elif options.server_only:
            print("Linux server contract configured; client settings were preserved.")
            print(f"Host: {settings['server_backend_host']}")
            print(f"Port: {settings['server_backend_port']}")
            print(f"Shared key: {settings['server_access_key']}")
        else:
            print("Linux client/server contract configured.")
            print(f"Host: {settings['client_backend_host']}")
            print(f"Port: {settings['client_backend_port']}")
            print(f"Shared key: {settings['client_access_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
