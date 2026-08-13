# Hosting a public MoM Relive server

This guide covers the extra configuration required when players connect from
outside the server's local network. The game client and dedicated server can
run on Windows or Linux, but the network requirements are the same.

MoM Relive does not contain the game or dedicated-server files. Every player
must own and install Memories of Mars, and the host must install the official
**Memories of Mars - Dedicated Server** Steam tool.

## 1. Prepare the host network

Give the server computer a fixed LAN address. The preferred method is a DHCP
reservation in the router. Without it, a later address change can silently
break all port-forwarding rules.

Choose a backend TCP port. The examples below use `8080`; a different unused
port such as `18080` is equally valid. Also choose a shared key containing 4-16
letters, digits, `_` or `-`. The same host, port and key must be given to every
client.

Find the public IPv4 address or configure a dynamic DNS name. If the address
changes later, update the advertised public address and restart the server.

## 2. Install the official dedicated server

Install **Memories of Mars - Dedicated Server** through Steam, or use SteamCMD.
For example, on Linux:

```bash
steamcmd \
  +force_install_dir "$HOME/servers/mom" \
  +login anonymous \
  +app_update 897590 validate \
  +quit
```

Keep the game installation separate from the MoM Relive toolkit. Steam can
then validate or update the official files normally.

## 3. Configure MoM Relive on Windows

1. Download `MoMRevivalSetup.exe` from the latest release and install the
   **Dedicated server** component.
2. Open **MoM Server Manager**, then open **Configuration**.
3. Select the official dedicated-server directory.
4. Set **Listen address** to `0.0.0.0` so the backend accepts remote clients.
5. Set **Backend seen by the server** to `127.0.0.1` when the backend and game
   server run on the same computer.
6. Enter the backend TCP port, shared key and public IP or DNS name.
7. Select the existing world ID when preserving an existing save. A different
   world ID creates or selects a different world.
8. Save the configuration, apply the server patch and start the server.
9. Use **Open ports in Firewall** to create the matching Windows Firewall
   rules, or create them manually.

The manager disables EAC because the retired official services are not used.
Other native values remain in `DedicatedServerConfig.cfg`.

## 4. Configure MoM Relive on Linux

Download `MoMRelive-<version>-linux-x86_64.tar.gz` from the
[latest release](https://github.com/drbermejor/MoM-Relive/releases/latest),
extract it, and install it as the normal user that will run the server:

```bash
./install_linux.sh
```

Do not run the launcher as root. Prepare the server and persist its connection
settings with the interactive assistant:

```bash
mom-relive-configure
```

The assistant asks for the official server folder, backend port, shared key
and public IP or DNS name. It validates the values, automatically uses the
correct internal and listening addresses, applies the reversible preparation,
and offers to enable and start the systemd user service.

For an automated or non-interactive installation, use the equivalent command:

```bash
mom-relive-server --prepare-only \
  --server-dir "$HOME/servers/mom" \
  --backend-host 127.0.0.1 \
  --bind 0.0.0.0 \
  --port 8080 \
  --key CHANGE_ME \
  --public-ip YOUR_PUBLIC_IP_OR_DNS
```

The two backend addresses have different purposes:

- `--backend-host 127.0.0.1` is the address used internally by the game server.
- `--bind 0.0.0.0` makes the backend listen for clients on every host network
  interface.

If the backend is hosted somewhere other than the game server, it automatically
preserves a public address reported by the server, or uses the public source IP
of that registration when the game sends a private address. It does not trust
proxy forwarding headers for this purpose. A manual `--advertise-host` on the
backend remains the highest-priority override. An active legacy session is
corrected on its next keepalive after the backend is upgraded.

Edit `DedicatedServerConfig.cfg` in the official server directory to set the
server name, world ID, optional password, player limit and native game rules.
Then enable the user service:

```bash
sudo loginctl enable-linger "$USER"
systemctl --user enable --now mom-relive-server
```

Linger allows the user service to start after a reboot without an interactive
login. Follow its live output with:

```bash
journalctl --user -u mom-relive-server -f
```

If UFW is active, allow the configured backend port and both game UDP ports:

```bash
sudo ufw allow 8080/tcp
sudo ufw allow 7777/udp
sudo ufw allow 15000/udp
```

Use the actual backend port if it is not `8080`.

## 5. Forward the router ports

Create these port-forwarding rules from the Internet/WAN interface to the fixed
LAN address of the server computer:

| External port | Protocol | Internal destination | Purpose |
|---|---|---|---|
| Configured backend port | TCP | Server LAN IP, same port | Login and server listing |
| `7777` | UDP | Server LAN IP, port `7777` | Game traffic |
| `15000` | UDP | Server LAN IP, port `15000` | Query/beacon traffic |

Forward only the ports required by MoM Relive. Do not expose SSH, remote
desktop, the graphical server manager or unrelated administration services.

Router interfaces differ, so MoM Relive cannot create these rules
automatically. The Windows firewall button configures Windows only; it does not
configure the router.

## 6. Check for double NAT or CGNAT

Compare the router's WAN IPv4 address with the public IPv4 address reported by
an external address-checking service. Direct forwarding may not work when the
WAN address is different or belongs to one of these private/shared ranges:

- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `100.64.0.0/10` (carrier-grade NAT)

With double NAT, forward the same ports on the upstream router as well. With
CGNAT, request a public IPv4 address from the ISP or use a hosting/VPN solution
that supports both the backend TCP port and the two required UDP ports.

## 7. Give players the client settings

Players need only these values:

```text
Backend: YOUR_PUBLIC_IP_OR_DNS
Backend port: YOUR_BACKEND_PORT
Shared key: YOUR_SHARED_KEY
Server password: only when configured in DedicatedServerConfig.cfg
```

On Windows, install the **Client** component, enter those values, click
**Prepare / repair client**, and then **Play (community mode)**.

On Linux/Proton, configure only the remote client destination so local server
settings are not replaced:

```bash
mom-relive-configure --client-only \
  --host YOUR_PUBLIC_IP_OR_DNS \
  --port YOUR_BACKEND_PORT \
  --key YOUR_SHARED_KEY
mom-relive-client
```

## 8. Validate from outside the network

First open the health endpoint from a device on another Internet connection:

```text
http://YOUR_PUBLIC_IP_OR_DNS:YOUR_BACKEND_PORT/health
```

A working backend returns:

```json
{"result": "ok", "service": "MoMBackend/2.0"}
```

Then use a real prepared game client from outside the host network. Confirm
that the server appears in the browser and that the player can enter the world.
A generic UDP port checker is not a substitute for this test because the game
server may ignore packets that are not valid game protocol messages.

Common failure points:

- Backend unreachable: check `0.0.0.0`, the TCP firewall rule, router
  forwarding and CGNAT.
- Backend works but the server is absent: check that the dedicated server and
  backend use the same key and that the world completed startup.
- Server appears but joining fails: check UDP `7777`, the advertised public
  address and double NAT.
- Connection works only inside the LAN: test the public address from a mobile
  hotspot and check whether the router supports NAT loopback.

The shared key is included in every authorized client's patched URL. It keeps
casual scans out of the API, but it is not an anti-cheat secret or a substitute
for normal host security.
