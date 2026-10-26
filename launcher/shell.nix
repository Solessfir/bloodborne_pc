# Launcher environment: `nix-shell launcher/shell.nix --run 'python3 launcher/bbport_launcher.py'`
{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  packages = with pkgs; [
    (python3.withPackages (ps: [ ps.tkinter ps.pillow ]))
  ];
}
