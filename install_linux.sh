#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
bin_home="${XDG_BIN_HOME:-$HOME/.local/bin}"
install_root="$data_home/MoMRelive"
installed_binary="$install_root/MoMNativeServer"
installed_client="$install_root/MoMReliveClient"
installed_configure="$install_root/MoMReliveConfigure"
command_link="$bin_home/mom-relive-server"
client_link="$bin_home/mom-relive-client"
configure_link="$bin_home/mom-relive-configure"
desktop_file="$data_home/applications/mom-relive-server.desktop"
client_desktop="$data_home/applications/mom-relive-client.desktop"
configure_desktop="$data_home/applications/mom-relive-configure.desktop"
service_file="$config_home/systemd/user/mom-relive-server.service"
legal_file="$install_root/LEGAL.md"
project_license="$install_root/LICENSE"
copyright_file="$install_root/COPYRIGHT"
third_party_file="$install_root/THIRD-PARTY-NOTICES.md"
license_dir="$install_root/licenses"

if [[ "${1:-}" == "--uninstall" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now mom-relive-server.service >/dev/null 2>&1 || true
  fi
  rm -f -- "$command_link" "$client_link" "$configure_link" "$desktop_file" "$client_desktop" "$configure_desktop" "$service_file" "$installed_binary" "$installed_client" "$installed_configure" "$legal_file" "$project_license" "$copyright_file" "$third_party_file" "$license_dir/PYTHON-LICENSE.txt" "$license_dir/PYINSTALLER-LICENSE.txt"
  rmdir -- "$license_dir" 2>/dev/null || true
  rmdir -- "$install_root" 2>/dev/null || true
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  echo "MoM Relive Linux tools removed. Game backups and user data were preserved."
  exit 0
fi

if [[ ! -x "$source_dir/MoMNativeServer" || ! -x "$source_dir/MoMReliveClient" || ! -x "$source_dir/MoMReliveConfigure" ]]; then
  echo "All three Linux tools must be next to install_linux.sh." >&2
  exit 2
fi

mkdir -p -- "$install_root" "$bin_home" "$(dirname -- "$desktop_file")" "$(dirname -- "$service_file")"

for required_notice in LEGAL.md LICENSE COPYRIGHT THIRD-PARTY-NOTICES.md licenses/PYTHON-LICENSE.txt licenses/PYINSTALLER-LICENSE.txt; do
  if [[ ! -f "$source_dir/$required_notice" ]]; then
    echo "Required legal notice is missing: $required_notice" >&2
    exit 3
  fi
done
mkdir -p -- "$license_dir"

install_atomic() {
  local source_path="$1"
  local target_path="$2"
  local pending_path="${target_path}.new"
  install -m 755 "$source_path" "$pending_path"
  mv -f -- "$pending_path" "$target_path"
}

# Renaming a complete temporary file also permits upgrades while an older
# installed executable is still mapped by a running process.
install_atomic "$source_dir/MoMNativeServer" "$installed_binary"
install_atomic "$source_dir/MoMReliveClient" "$installed_client"
install_atomic "$source_dir/MoMReliveConfigure" "$installed_configure"
install -m 644 "$source_dir/LEGAL.md" "$legal_file"
install -m 644 "$source_dir/LICENSE" "$project_license"
install -m 644 "$source_dir/COPYRIGHT" "$copyright_file"
install -m 644 "$source_dir/THIRD-PARTY-NOTICES.md" "$third_party_file"
install -m 644 "$source_dir/licenses/PYTHON-LICENSE.txt" "$license_dir/PYTHON-LICENSE.txt"
install -m 644 "$source_dir/licenses/PYINSTALLER-LICENSE.txt" "$license_dir/PYINSTALLER-LICENSE.txt"
ln -sfn -- "$installed_binary" "$command_link"
ln -sfn -- "$installed_client" "$client_link"
ln -sfn -- "$installed_configure" "$configure_link"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=MoM Relive Server'
  printf '%s\n' 'Comment=Run the native Memories of Mars community server'
  printf 'Exec="%s"\n' "$installed_binary"
  printf '%s\n' 'Icon=network-server'
  printf '%s\n' 'Terminal=true'
  printf '%s\n' 'Categories=Game;Network;'
} > "$desktop_file"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=MoM Relive Client (Proton)'
  printf '%s\n' 'Comment=Prepare and run Memories of Mars through Proton'
  printf 'Exec="%s"\n' "$installed_client"
  printf '%s\n' 'Icon=steam_icon_644290'
  printf '%s\n' 'Terminal=true'
  printf '%s\n' 'Categories=Game;Network;'
} > "$client_desktop"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=Configure MoM Relive (Linux)'
  printf '%s\n' 'Comment=Guided setup for a public MoM Relive server'
  printf 'Exec="%s"\n' "$installed_configure"
  printf '%s\n' 'Icon=preferences-system-network'
  printf '%s\n' 'Terminal=true'
  printf '%s\n' 'Categories=Game;Network;Settings;'
} > "$configure_desktop"

{
  printf '%s\n' '[Unit]'
  printf '%s\n' 'Description=MoM Relive native dedicated server'
  printf '%s\n' 'After=network-online.target'
  printf '%s\n' 'Wants=network-online.target'
  printf '%s\n' '' '[Service]'
  printf '%s\n' 'Type=simple'
  printf 'ExecStart="%s"\n' "$installed_binary"
  printf '%s\n' 'KillSignal=SIGINT'
  # The launcher deliberately maps a clean Ctrl+C/SIGINT shutdown to the
  # conventional shell status 130. Treat that status as successful so an
  # explicit systemctl stop is not reported as a failed service.
  printf '%s\n' 'SuccessExitStatus=130'
  printf '%s\n' 'TimeoutStopSec=60'
  printf '%s\n' 'Restart=on-failure'
  printf '%s\n' 'RestartSec=10'
  printf '%s\n' '' '[Install]'
  printf '%s\n' 'WantedBy=default.target'
} > "$service_file"

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$(dirname -- "$desktop_file")" >/dev/null 2>&1 || true
fi

echo "MoM Relive Linux tools installed."
echo "Command: $command_link"
echo "Client: $client_link"
echo "Configure: $configure_link"
echo "Desktop: $desktop_file"
echo "Service: $service_file"
echo "Configuration and saves remain under: $data_home/MoMRevival"
echo
echo "Next step: run 'mom-relive-configure' for guided public-server setup."
echo "Advanced options: mom-relive-configure --help"
echo "Optional background service: systemctl --user enable --now mom-relive-server"
