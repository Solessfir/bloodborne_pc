#!/usr/bin/env bash
# Installs or removes the current copy's application-menu entry.
set -euo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
dest=${XDG_DATA_HOME:-$HOME/.local/share}/applications
entry=$dest/io.github.bbport.Launcher.desktop
case ${1:-install} in
install|add|--play)
    mkdir -p "$dest"
    python3 - "$here" "$entry" "${1:-install}" <<'PY'
from pathlib import Path
import sys

here, entry = map(Path, sys.argv[1:3])
launcher = here.parent / 'launch.sh'
if not launcher.is_file():
    launcher = here / 'bb-launcher.sh'
# Exec has both desktop string escaping and quoted argument escaping.
argument = str(launcher).replace('%', '%%')
for character in ('\\', '"', '`', '$'):
    argument = argument.replace(character, '\\' + character)
argument = argument.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')
icon = str(here / 'bloodborne.png').replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')
template = (here / 'io.github.bbport.Launcher.desktop.in').read_text()
command = f'bash "{argument}"' + (' --play' if sys.argv[3] == '--play' else '')
entry.write_text(template.replace('@COMMAND@', command).replace('@ICON@', icon))
PY
    echo "Installed $entry"
    ;;
remove|uninstall|-r)
    rm -f -- "$entry"
    echo "Removed $entry"
    ;;
*)
    echo "Usage: $0 [install|--play|remove|-r]" >&2
    exit 2
    ;;
esac
if [[ -d $dest ]] && command -v update-desktop-database >/dev/null; then
    update-desktop-database "$dest"
fi
