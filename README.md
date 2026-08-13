# MoM Relive — unofficial community compatibility toolkit

> **Independent and unofficial.** This project is not endorsed by or affiliated
> with the game publisher, developer, Steam, Epic Games, or Easy Anti-Cheat.

An unofficial community replacement for the retired online services used by
**Memories of Mars**. It lets owners of the game run a dedicated server, list it
in the in-game browser, connect to community servers, and keep world and character
progress on the server machine.

Current version: **0.8.7**. Tested on Windows 11 with the Steam client and
dedicated server, and on the native Steam dedicated server for Linux.

> This project does not contain or redistribute the game, game assets, Steam
> files, EAC files, or saved games. You must own and install Memories of Mars
> and its dedicated server separately.
>
> See the project [legal notice](LEGAL.md), [copyright notice](COPYRIGHT), and
> [third-party notices](THIRD-PARTY-NOTICES.md) before distributing or using
> binary packages.

## What works

- Replacement HTTP backend for login and server sessions.
- Separate client and dedicated-server applications.
- Reversible, repeatable patching; Steam updates are detected and the clean
  `.orig` baseline is refreshed safely.
- A reversible community-mode `Launch_Game.exe` replacement for the retired
  service environment.
- Direct Windows launches explicitly provide Steam's official app context, so
  a Steam client or game update cannot leave the legacy SDK at `AppId 0` and
  crash the game during startup.
- Server browser discovery over LAN or the Internet.
- Persistent inventory, equipment, action bar, health, oxygen, food, FLOPS,
  learned blueprints, work orders, character progress and world deployables.
- Automatic save backups before shutdown and on demand.
- Server manager with live status, connected players, character names parsed
  from `Game.log`, a scrollable live log, panel activity, and a safely hidden or
  visible native server console.
- Console-first native server launcher that preserves the game's own
  `DedicatedServerConfig.cfg` settings.
- Automatic public-IP detection and automatic recovery after the game's daily
  server restart.
- Interactive Linux public-server setup with validation, sensible defaults and
  optional systemd startup.
- Windows client preparation verifies the exact `Engine.ini` path and backend
  URL pair before reporting a ready state or testing connectivity.
- Windows users can select a nonstandard `Engine.ini`, repair only that file,
  or explicitly close a locked `MemoriesOfMars.exe` process from the client UI.
- A per-session single-instance guard prevents duplicate client panels, while
  automatic and manual update checks use only the official GitHub release API.
- A separately hosted backend automatically advertises the public source IP of
  each remote game server instead of leaking its private LAN address. An
  explicitly configured public IP or DNS name always takes precedence.

## Install

Download `MoMRevivalSetup.exe` from the latest GitHub release. The installer is
self-contained and does not require Python. Choose one of these components:

- **Client** on every player's PC.
- **Dedicated server** on the host machine.
- **Client and dedicated server** when both run on the same PC.

The applications request administrator rights because Steam commonly installs
the game below `Program Files (x86)`.

Release assets are split by operating system:

- `MoMRevivalSetup.exe` is the Windows toolkit: client configurator, server
  manager and native console mode.
- `MoMRelive-<version>-linux-x86_64.tar.gz` is the Linux toolkit: native server,
  Proton client patcher/launcher, XDG user installer, desktop launchers and an
  optional systemd user service.

The Linux archive is built against Debian 11/glibc 2.31 for compatibility with
Debian 11+, Ubuntu 20.04+ and current x86-64 distributions. Its packaged tools
have been smoke-tested in Debian 11 and Ubuntu 20.04 containers; the complete
Steam client/server flow has been tested on CachyOS. See
[README-LINUX.md](README-LINUX.md) for the precise validation matrix and known
Proton compatibility settings.

## Host a server

1. Install the Steam tool **Memories of Mars - Dedicated Server**.
2. Open **MoM Server Manager**, then open **Configuration**.
3. Select the dedicated-server folder and an existing world ID if you already
   have a save. Changing the world ID selects a different save directory.
4. Set the server name, optional password, player limit and shared access key.
5. Save and apply the server patch, then click **Start**.
6. Allow or forward these ports:

   | Port | Protocol | Purpose |
   |---|---|---|
   | 7777 | UDP | Game traffic |
   | 15000 | UDP | Server query/beacon |
   | 8080 | TCP | Revival backend (or your configured port) |

For Internet play, forward the ports in the router to the host PC. The manager
can create the matching Windows Firewall rules, but it cannot configure the
router.

See [Hosting a public MoM Relive server](PUBLIC-SERVER.md) for complete Windows
and Linux instructions, router forwarding, firewall configuration, CGNAT
checks and external validation.

The shared key keeps casual Internet scans out of the API. It is not an
anti-cheat secret: an authorized client can read the value from its own patched
executable.

The manager enables the legacy OpenSSL CPU workaround for the dedicated server
by default. This is equivalent to setting
`OPENSSL_ia32cap=:~0x20000000` in a batch file and prevents an immediate exit on
affected modern processors. It can be disabled under **Configuration**.

## Native server mode

The server component also installs **Native Server (console)**. Use it when you
prefer the game's normal console and `DedicatedServerConfig.cfg` workflow:

This is an additional mode; the existing Server Manager and all of its managed
start, stop, restart, backup and monitoring features remain available.

1. Open **Server Manager**, configure the Relive backend values and server
   folder, then click **Save**. You only need to do this again when those Relive
   connection values change.
2. Edit `DedicatedServerConfig.cfg` in the dedicated-server folder with your
   usual editor or existing tooling. Server name, password, world ID, player
   limit, administrators and other native values remain under your control.
3. Launch **Native Server (console)** from the Start menu.

The native launcher applies only the required URL, EAC and persistence
compatibility changes, starts the Relive backend, sets the OpenSSL workaround,
and runs `MemoriesOfMarsServer.exe -log` in a visible console. It stops the
backend it owns when the server exits. It does not overwrite native server
settings other than forcing `EnableEAC` to `false`, which is required for the
community service. Server name, password, world ID, player limit,
administrators and other native values are preserved.

For existing scripts, the same executable supports a patch-only or backend-only
flow:

```powershell
MoMNativeServer.exe --prepare-only
MoMNativeServer.exe --backend-only
MoMNativeServer.exe --server-dir "D:\Steam\steamapps\common\Memories of Mars - Dedicated Server"
```

Arguments placed after `--` are passed directly to the native server executable.

### Native Linux server

The Linux mode is an addition to the Windows applications above. It uses
Steam's native ELF server, its normal `DedicatedServerConfig.cfg`, and the same
Relive backend; no Wine, Windows manager, `/etc/hosts` entry, or HTTPS proxy is
required.

Requirements are the Steam tool **Memories of Mars - Dedicated Server** and
Python 3.11 or later. Clone or download this repository on the server, then run:

```bash
python3 native_server.py
```

Native, Flatpak and Snap Steam installations are detected automatically. A
nonstandard Steam library is read from `steamapps/libraryfolders.vdf`;
alternatively, provide it explicitly:

```bash
python3 native_server.py \
  --server-dir "$HOME/.local/share/Steam/steamapps/common/Memories of Mars - Dedicated Server"
```

Run the launcher as a normal user, not as root. It creates reversible `.orig`
backups, patches both the ASCII and UTF-32LE service URLs found in the Linux
binary, preserves its executable permission, writes Unreal settings below
`Game/Saved/Config/LinuxServer`, starts the backend, and launches the server as
the official script does: `MemoriesOfMarsServer Game -log`.

Native settings remain in `DedicatedServerConfig.cfg`. To patch without
starting processes, to run only the backend, or to restore the managed changes:

```bash
python3 native_server.py --prepare-only
python3 native_server.py --backend-only
python3 native_server.py --restore
```

Use `Ctrl+C` for a clean shutdown. Arguments after `--` go directly to the
server, for example `python3 native_server.py -- -Port=7778`. The Linux launcher
restarts the world after its scheduled daily exit by default; use
`--no-auto-restart` to opt out.

## Connect a client

1. Install the Steam game **Memories of Mars**.
2. Open **MoM Revival Client**.
3. Enter the host's public IP or DNS name, backend port and shared key.
4. Click **Prepare / repair**, then **Play (community mode)**. Steam's normal Play
   button will also use the Revival launcher after preparation.

Close the game before preparing or repairing it. The client verifies the
community launcher, every embedded binary redirect, and both `BaseURL` entries
in the exact Windows-profile `Engine.ini` before reporting a ready state.
Use **Engine.ini override** to select a nonstandard Windows profile and
**Repair Engine.ini only** when the binary patch is already correct. If Windows
has locked the executable, **Close game processes** asks for confirmation and
then terminates only `MemoriesOfMars.exe` process trees.

Only one client panel can run in the same Windows session. The client checks the
official GitHub latest-release endpoint after startup; **Check for updates** can
repeat the check manually. It never downloads or runs an update automatically.

**Restore official files** restores both the original game executable and the
official EAC launcher. It does not delete saves.

## Saves and backups

The replacement backend does not own the world save. The dedicated server
writes JSON data below:

```text
Game/Saved/DB/Server<WorldId>/Version_1.1/
|-- PlayerData/<player-identifier>/
|   |-- Inventory.json
|   |-- Equipment.json
|   |-- Actionbar.json
|   |-- Stats.json
|   |-- Flops.json
|   |-- Blueprints.json
|   |-- Workorders.json
|   `-- Progress.json
`-- ServerData/
    |-- Deployables.json
    `-- Alliances.json
```

The manager discovers existing worlds and prefers the one with the most player
data. Managed backups are stored outside the source tree in
`%APPDATA%\MoMRevival\saves`. Back up the whole `Game\Saved\DB` directory
before migrating a server.

The option that preserves characters on reconnect writes:

```ini
[/Script/ShooterGame.MarsGameMode]
bNeverSpawnInCloningFacility=True
```

New characters may need one initial connection with that option disabled to
receive the cloning-facility starter equipment. Re-enable it afterwards to
preserve the character on reconnect.

## Build from source

Requirements:

- Python 3.11 or later
- Windows 10 or 11, `pyinstaller`, and Inno Setup 6 to build the Windows
  installer

Run:

```powershell
python -m unittest discover -s tests -v
.\build_release.ps1
```

Build the self-contained x86-64 Linux server package with PyInstaller installed:

```bash
./build_release_linux.sh
```

For a broadly compatible release artifact, build against the project's Debian
11 baseline (Docker required):

```bash
./build_release_linux_container.sh
```

The reproducible outputs are written to `dist\`. Neither `dist\` nor PyInstaller
build files are committed.

Command-line patching is also available:

```powershell
python apply.py server --key ab12cd34 --public-ip 203.0.113.10
python backend.py --access-key ab12cd34 --data-dir "$env:APPDATA\MoMRevival"
python apply.py client --host 203.0.113.10 --key ab12cd34
python native_server.py --server-dir "C:\path\to\Memories of Mars - Dedicated Server"
```

The same `apply.py` and `native_server.py` commands work with a native Linux
dedicated-server installation.

## How it works

The original AWS API Gateway endpoints no longer resolve. MoM Relive redirects
the session service through Unreal configuration and rewrites the retired
account-service URL in the client executable without changing its file size.
The local backend reproduces the response shapes required by the original game.

Important compatibility details discovered during recovery:

- The legacy Unreal build can crash while loading on high-thread-count CPUs;
  the client launcher can temporarily restrict CPU affinity during startup.

## Known limitations

- Achievements and global online statistics are placeholders.
- Some harmless serialization warnings from retired optional services remain in
  the game log.
- This is a community compatibility project, not an official Limbic, 505 Games,
  Steam, or Epic Games product.

## License

The original code in this repository is released under the GNU General Public
License v3.0. Copyright is stated in [COPYRIGHT](COPYRIGHT). This licence does
not grant rights to Memories of Mars or any third-party software. See
[LEGAL.md](LEGAL.md) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for
the complete distribution notices.
