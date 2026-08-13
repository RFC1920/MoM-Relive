# Roadmap

This roadmap records planned work. It is not a promise of a release date.

## Windows unattended server operation

- Enable automatic world restart in `Native Server (console)` on Windows, as
  already provided by the native Linux launcher.
- Keep the backend running while the world performs its scheduled daily
  restart.
- Distinguish an intentional `Ctrl+C` or service stop from an unexpected world
  exit, so an administrator can always stop the server without it relaunching.
- Add a bounded restart delay and crash-loop protection.
- Keep `--no-auto-restart` as an explicit opt-out on both platforms.
- Provide a supported Windows service or Task Scheduler installation mode so a
  dedicated server can start at boot without leaving Server Manager open.
- Add automatic save backups to the standalone native-console/service flow.

Until this work is complete, unattended automatic restart on Windows requires
Server Manager to remain open. `Native Server (console)` starts the backend and
world, but exits when the Windows world process exits.

## Linux administration parity

- Add a lightweight web interface or terminal UI for server administration.
- Show backend/world state, active sessions and connected players.
- Display and follow `Game.log`, including resolved character names.
- Add on-demand, pre-shutdown and scheduled save backups.
- Provide safe start, stop and restart controls without weakening the existing
  systemd integration.

## Network configuration clarity

- Distinguish explicitly between the backend's public address and each game
  server's advertised public address.
- Offer separate modes for detecting the address of each connecting game
  server and forcing one address for all advertisements.
- Add clearer diagnostics for backend TCP reachability, UDP game/query ports,
  NAT, port forwarding and CGNAT.

## Windows release pipeline and code signing

- Build Windows release artifacts in GitHub Actions from the tagged source.
- Integrate an Authenticode provider suitable for the open-source project.
- Sign `MoMRevival.exe`, `MoMClientLauncher.exe`, `MoMServerManager.exe` and
  `MoMNativeServer.exe` before packaging them.
- Sign and timestamp `MoMRevivalSetup.exe` after the installer is built.
- Verify every signature and timestamp before publishing a release.
- Publish checksums and build provenance with each release.

The current Windows release is not Authenticode-signed. This does not mean that
it contains malware, but Windows may identify it as coming from an unknown
publisher, and SmartScreen or antivirus products may warn about a new,
low-reputation executable. Users should download only from the official GitHub
release page and verify the published SHA-256 checksum. A mismatched checksum
must be treated as an invalid download, not ignored.
