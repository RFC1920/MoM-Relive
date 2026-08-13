# Third-party notices

MoM Relive's release executables are produced with Python and PyInstaller.
The Windows graphical applications also include Tcl/Tk components used by
Python's Tk interface, and the Windows installer is generated with Inno Setup.
These components are not part of the MoM Relive GPL grant and remain subject
to their own licences.

Every binary release must include the exact notices collected from its build
environment:

- `licenses/PYTHON-LICENSE.txt`
- `licenses/PYINSTALLER-LICENSE.txt`
- `licenses/TCL-TK-LICENSE.txt` in the Windows installer
- `licenses/INNO-SETUP-LICENSE.txt` in the Windows installer

The build fails if a required notice cannot be found. This prevents a release
from silently omitting the terms for the runtime versions it actually embeds.

No licence listed here grants rights to Memories of Mars, its content, its
name or logos, or any other third-party game or service.
