#!/usr/bin/env bash
# Starts the shared native launcher; --tk keeps the previous frontend available.
here=$(cd -- "$(dirname -- "$0")" && pwd)
if [[ ${1:-} == --qt ]]; then
    shift
    exec python3 "$here/bbport_launcher_qt.py" "$@"
fi
if [[ ${1:-} == --tk ]]; then
    shift
elif python3 -c 'import PySide6, tkinter, PIL.ImageQt' 2>/dev/null; then
    exec python3 "$here/bbport_launcher_qt.py" "$@"
fi
if python3 -c 'import tkinter, PIL.ImageTk' 2>/dev/null; then
    exec python3 "$here/bbport_launcher.py" "$@"
fi
if command -v nix-shell >/dev/null; then
    printf -v command 'python3 %q ' "$here/bbport_launcher.py"
    for argument in "$@"; do printf -v command '%s%q ' "$command" "$argument"; done
    exec nix-shell "$here/shell.nix" --run "$command"
fi
echo 'Install Python Tk and Pillow (CachyOS/Arch: sudo pacman -S --needed tk python-pillow).' >&2
exit 1
