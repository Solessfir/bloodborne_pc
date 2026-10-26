#!/usr/bin/env bash
# Starts the shared Tk launcher; Nix supplies its dependencies when needed.
here=$(cd -- "$(dirname -- "$0")" && pwd)
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
