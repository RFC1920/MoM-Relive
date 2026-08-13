"""Instalador por linea de comandos de Memories of Mars Revival.

Ejemplos:
  python apply.py client --host 203.0.113.10 --key ab12cd34
  python apply.py server --host 127.0.0.1 --public-ip 203.0.113.10 --key ab12cd34
  python apply.py client --restore

La interfaz grafica (mom_revival.py) ofrece las mismas operaciones.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import momlib
import redirect_urls


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "component",
        choices=("client", "server", "all"),
        help="component to patch; client and server are independent",
    )
    ap.add_argument(
        "--host",
        default="127.0.0.1",
        help="IP o nombre de la maquina que ejecuta el backend",
    )
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument(
        "--key", default="mom1", help="shared access key (4-16 characters)"
    )
    ap.add_argument("--client-dir", help="Steam 'Memories of Mars' folder")
    ap.add_argument(
        "--server-dir", help="'Memories of Mars - Dedicated Server' folder"
    )
    ap.add_argument(
        "--restore",
        action="store_true",
        help="retira solamente los cambios gestionados",
    )
    ap.add_argument("--admin", dest="admin_id")
    ap.add_argument("--public-ip")
    ap.add_argument("--max-players", type=int)
    ap.add_argument("--server-name")
    ap.add_argument("--server-password")
    ap.add_argument("--server-id")
    ap.add_argument(
        "--allow-cloning",
        action="store_true",
        help="no aplica el arreglo de persistencia de la camara",
    )
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    opts = ap.parse_args(argv)
    found_client, found_server = momlib.discover_installs()
    client_dir = Path(opts.client_dir) if opts.client_dir else found_client
    server_dir = Path(opts.server_dir) if opts.server_dir else found_server
    results = {}
    try:
        if opts.component in ("client", "all"):
            if not client_dir:
                raise momlib.ConfigError(
                    "The client was not found; specify --client-dir"
                )
            if opts.restore:
                results["client"] = momlib.restore_client(client_dir)
            else:
                results["client"] = momlib.apply_client(
                    client_dir, opts.host, opts.port, opts.key
                )

        if opts.component in ("server", "all"):
            if not server_dir:
                raise momlib.ConfigError(
                    "The dedicated server was not found; specify --server-dir"
                )
            if opts.restore:
                results["server"] = momlib.restore_server(server_dir)
            else:
                results["server"] = momlib.apply_server(
                    server_dir,
                    opts.host,
                    opts.port,
                    opts.key,
                    server_name=opts.server_name,
                    server_password=opts.server_password,
                    server_id=opts.server_id,
                    public_ip=opts.public_ip,
                    max_players=opts.max_players,
                    admin_id=opts.admin_id,
                    skip_cloning=not opts.allow_cloning,
                )
    except (momlib.ConfigError, redirect_urls.PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
