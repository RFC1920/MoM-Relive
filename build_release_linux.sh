#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

python_bin="${PYTHON:-python3}"
version="$($python_bin -c 'from version import __version__; print(__version__)')"
architecture="$(uname -m)"
if [[ "$architecture" != "x86_64" ]]; then
  echo "Linux releases are currently supported only on x86_64 (found $architecture)." >&2
  exit 2
fi

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  $python_bin -m unittest discover -s tests -v
fi
$python_bin -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name MoMNativeServer \
  --distpath dist/linux \
  --workpath build/linux \
  --specpath build/linux-spec \
  native_server.py
$python_bin -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name MoMReliveClient \
  --distpath dist/linux \
  --workpath build/linux \
  --specpath build/linux-spec \
  linux_client.py
$python_bin -m PyInstaller \
  --clean \
  --noconfirm \
  --onefile \
  --name MoMReliveConfigure \
  --distpath dist/linux \
  --workpath build/linux \
  --specpath build/linux-spec \
  linux_configure.py

package_name="MoMRelive-${version}-linux-x86_64"
stage_root="$(mktemp -d "${TMPDIR:-/tmp}/mom-relive-release.XXXXXX")"
trap 'rm -rf -- "$stage_root"' EXIT
package_dir="$stage_root/$package_name"
mkdir -p "$package_dir"
license_dir="$package_dir/licenses"
mkdir -p "$license_dir"

python_license="$($python_bin - <<'PY'
import pathlib
import sys
import sysconfig

candidates = [
    pathlib.Path(sys.base_prefix) / "LICENSE.txt",
    pathlib.Path(sys.base_prefix) / "LICENSE",
    pathlib.Path("/usr/local/LICENSE"),
    pathlib.Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
    pathlib.Path("/usr/share/doc") / f"python{sys.version_info.major}.{sys.version_info.minor}" / "copyright",
]
for candidate in candidates:
    if candidate.is_file():
        print(candidate)
        break
PY
)"
pyinstaller_license="$($python_bin - <<'PY'
import importlib.metadata as metadata

distribution = metadata.distribution("pyinstaller")
for entry in distribution.files or ():
    if str(entry).replace("\\", "/").endswith("licenses/COPYING.txt"):
        print(distribution.locate_file(entry))
        break
PY
)"
if [[ ! -f "$python_license" || ! -f "$pyinstaller_license" ]]; then
  echo "A required third-party licence could not be located." >&2
  exit 3
fi
install -m 644 "$python_license" "$license_dir/PYTHON-LICENSE.txt"
install -m 644 "$pyinstaller_license" "$license_dir/PYINSTALLER-LICENSE.txt"
install -m 755 dist/linux/MoMNativeServer "$package_dir/MoMNativeServer"
install -m 755 dist/linux/MoMReliveClient "$package_dir/MoMReliveClient"
install -m 755 dist/linux/MoMReliveConfigure "$package_dir/MoMReliveConfigure"
install -m 755 install_linux.sh "$package_dir/install_linux.sh"
install -m 644 README-LINUX.md "$package_dir/README-LINUX.md"
install -m 644 PUBLIC-SERVER.md "$package_dir/PUBLIC-SERVER.md"
install -m 644 LEGAL.md "$package_dir/LEGAL.md"
install -m 644 LICENSE "$package_dir/LICENSE"
install -m 644 COPYRIGHT "$package_dir/COPYRIGHT"
install -m 644 THIRD-PARTY-NOTICES.md "$package_dir/THIRD-PARTY-NOTICES.md"

archive="dist/${package_name}.tar.gz"
tar -C "$stage_root" -czf "$archive" "$package_name"
sha256sum "$archive" > "$archive.sha256"

echo "Created $archive"
cat "$archive.sha256"
