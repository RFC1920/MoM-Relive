# MoM Relive — native Linux server

This package prepares and launches both Steam components on x86-64 Linux:

- `mom-relive-server` runs the dedicated server as a native Linux process.
- `mom-relive-client` patches the Windows client and launches it through the
  installed Steam Proton runtime in community compatibility mode.
- `mom-relive-configure` applies the same host, port and shared key to both.

It contains no game files and does not require Python. Proton is needed only
for the game client.

## Compatibility and validation status

The release binaries are built in Debian 11 on x86-64, using glibc 2.31 as the
oldest supported runtime baseline. This is intended to cover Debian 11 or
newer, Ubuntu 20.04 or newer, and current x86-64 distributions such as Arch
Linux and CachyOS. A compatible glibc does not by itself guarantee that every
Steam, Proton, graphics-driver or desktop combination will work.

| Environment | What has been validated |
|---|---|
| CachyOS, AMD Radeon RX 9070 XT, Proton Experimental | Full end-to-end test with the real Steam Windows client and native Linux dedicated server: patching, login, server listing, joining, persistence and repeated mobile 3D-printer interaction. |
| Debian 11.11 container, glibc 2.31 | All three packaged executables start and expose their command-line interface. Steam, Proton and gameplay were not tested in the container. |
| Ubuntu 20.04 container, glibc 2.31 | All three packaged executables start and expose their command-line interface. Steam, Proton and gameplay were not tested in the container. |
| Debian/Ubuntu desktop with Steam | Expected to work from the shared glibc baseline, but a complete real-game session has not yet been validated. Reports are welcome. |
| Vanilla Arch Linux | Expected to behave like the tested Arch-derived CachyOS system, but has not been tested separately. |

Consequently, it is accurate to say that the tools have been smoke-tested on
Ubuntu 20.04 and Debian 11. It is not yet accurate to claim full Ubuntu or
Debian gameplay validation.

## Install

Extract the archive and install it for the current user. This does not require
`sudo`:

```bash
./install_linux.sh
```

It installs `mom-relive-server` in `~/.local/bin`, adds a desktop launcher and
provides an optional `systemd --user` service. It also installs
`mom-relive-client`, `mom-relive-configure` and their desktop launchers.
Uninstalling preserves settings, saves and game backups:

```bash
./install_linux.sh --uninstall
```

## Start

For a dedicated server, start the guided public-server setup:

```bash
mom-relive-configure
```

It locates or asks for the official server folder, detects the public IPv4
address, proposes a backend port and shared key, validates every value, applies
the compatibility preparation, and can enable and start the systemd user
service. It does not replace `DedicatedServerConfig.cfg` or change an existing
world selection.

For scripts and automated deployments, the original non-interactive options
remain available. For example, configure both components together with:

```bash
mom-relive-configure --host 127.0.0.1 --port 8080 --key YOUR_SHARED_KEY
```

Changing the shared key requires running this command again and restarting the
server. The matching client and server values are persisted in
`~/.local/share/MoMRevival/config.json`.

To connect this client temporarily to somebody else's server, change only its
destination. The local server host, port and key are left untouched:

```bash
mom-relive-configure --client-only \
  --host OTHER_SERVER_ADDRESS --port 8080 --key THEIR_SHARED_KEY
mom-relive-client
```

Run the same command with your own server address and key to switch back. On a
machine that hosts only a server, use `--server-only`; this also allows client
and server tools to be installed on different Linux machines.

Install the dedicated-server tool through Steam, edit its normal
`DedicatedServerConfig.cfg`, and run as a normal user:

```bash
mom-relive-server
```

The standard native, Flatpak and Snap Steam locations and additional libraries
in `steamapps/libraryfolders.vdf` are detected automatically. To select a path
or set the values shared with Windows clients explicitly:

```bash
mom-relive-server \
  --server-dir "$HOME/.local/share/Steam/steamapps/common/Memories of Mars - Dedicated Server" \
  --backend-host 127.0.0.1 \
  --bind 0.0.0.0 \
  --port 8080 \
  --key changeMe
```

The first run stores these values in
`~/.local/share/MoMRevival/config.json`. Use the same backend host, TCP port and
key when preparing each Windows client. For Internet hosting, also pass
`--public-ip YOUR_PUBLIC_IP` and forward UDP 7777, UDP 15000 and the configured
backend TCP port.

When the backend and game server are hosted at different locations, v0.8.4 and
later preserve a public address reported by the game server, or automatically
use the public source IP observed by the backend when the game reports a private
LAN address. A manual `--advertise-host` on a separately run backend (or
`--public-ip` when using the combined launcher) still takes precedence. This
supports multiple remote game servers without one global address accidentally
being applied to all of them. Existing sessions are corrected on their next
keepalive after the backend is upgraded.

For a complete public-hosting walkthrough, including SteamCMD, `0.0.0.0`
binding, firewall rules, router forwarding, CGNAT checks and external testing,
see [Hosting a public MoM Relive server](PUBLIC-SERVER.md).

The launcher automatically starts the world again after its configured daily
exit, matching Steam's `RunServer.sh`. Pass `--no-auto-restart` to disable this.
Use `Ctrl+C` to stop the world cleanly. Extra arguments after `--` are passed to
the game server, for example:

```bash
mom-relive-server -- -Port=7778
```

## Maintenance

```bash
mom-relive-server --prepare-only  # patch only
mom-relive-server --backend-only  # backend only
mom-relive-server --restore       # restore managed changes
mom-relive-server --help
```

For an unattended user service after initial configuration:

```bash
systemctl --user enable --now mom-relive-server
journalctl --user -u mom-relive-server -f
```

Patching is reversible and idempotent. The original ELF executable is kept as
`MemoriesOfMarsServer.orig`; its size and executable mode are preserved.
Native server settings remain in `DedicatedServerConfig.cfg`, except EAC is
disabled because it cannot be used with the community backend.

MoM Relive is an unofficial community compatibility project. See `LEGAL.md`
and `LICENSE` in this package.

## Proton client

Start the game once from Steam so its Proton prefix exists, then run:

```bash
mom-relive-client --host 127.0.0.1 --port 8080 --key YOUR_SHARED_KEY
```

The tool patches `MemoriesOfMars.exe`, writes the game's `Engine.ini` inside
Steam's `compatdata/644290` prefix and launches the real game executable with
the retired-service compatibility flag. It does not replace Steam's Windows
launcher. Use the MoM Relive
desktop entry or `mom-relive-client` for Linux sessions.

```bash
mom-relive-client --prepare-only
mom-relive-client --restore
```

CPU affinity is not changed by default on Linux. If a particular processor
hangs only while the game is starting, `--limit-cpu` temporarily limits the
Proton prefix and restores all available CPUs after 75 seconds. Use
`--diagnostics` to save a detailed Proton log under
`~/.local/share/MoMRevival/diagnostics` while reproducing a crash.

The launcher disables Proton's DXVK-NVAPI layer for Memories of Mars. The game
does not require NVAPI, and the layer can make its old UE4 render thread recurse
and terminate while loading the mobile 3D-printer interface on AMD GPUs. Use
`--enable-nvapi` only to override this compatibility setting for testing. If
the Windows game process exits abnormally, the launcher also cleans up its
remaining Proton/Wine processes instead of waiting indefinitely.

## Troubleshooting

Start with the default settings. In particular, do not add `taskset` or a CPU
limit unless startup itself fails on a particular machine. To capture a Proton
log and any available crash report:

```bash
mom-relive-client --diagnostics
```

The detailed Proton log is written below
`~/.local/share/MoMRevival/diagnostics`. The Unreal client log remains in the
game's `Saved/Logs` directory below Steam's `compatdata/644290` prefix. Server
and backend output from the user service is available with:

```bash
journalctl --user -u mom-relive-server -f
```

If a comparison specifically requires NVAPI, run once with `--enable-nvapi`.
On the tested AMD system this reproduced a render-thread termination when the
mobile 3D-printer UI loaded; it is therefore not the normal configuration.

`OPENSSL_ia32cap=:~0x20000000` is a separate server compatibility setting. It
masks a CPU capability from the old OpenSSL library bundled with the dedicated
server. It does not restrict CPU affinity and is unrelated to the Proton client
render crash.

## Notes for maintainers and forks

The retired service URLs are embedded directly in the executables; they are not
stored in a `.pak`, and an HTTP proxy alone is insufficient. The tested native
Linux server contains nine URLs: one ASCII string and eight UTF-32LE strings.
One of the UTF-32LE values is the authentication endpoint beginning with
`l32aayf7lh`. A patcher that handles only ASCII or UTF-16LE leaves the old
authentication and other AWS services active.

Binary replacements must remain within the original string slots, retain a NUL
terminator, preserve the executable size and mode, and always rebuild from the
pristine `.orig` copy. If Steam replaces an executable, that clean baseline
must be refreshed before applying the patch again.

The native server command is:

```bash
MemoriesOfMarsServer Game -log
```

The `Game` project argument is required on Linux. Compatibility preparation
must also write the LinuxServer Unreal configuration, redirect both session and
embedded service URLs, and disable EAC. Normal values in
`DedicatedServerConfig.cfg` should remain under the server owner's control.

Client and server use the same shared key when they communicate through one
Relive backend. The configuration deliberately stores client and server
destinations separately so a player can temporarily select somebody else's
host and key without rewriting the configuration of their own server.
