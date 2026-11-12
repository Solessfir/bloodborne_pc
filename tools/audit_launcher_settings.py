#!/usr/bin/env python3
"""Read the rendered reference UI's settings metadata without opening a game or user profile."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))


def audit():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import bbport_launcher_win as reference

    with tempfile.TemporaryDirectory() as folder:
        data = Path(folder)
        reference.DATA_DIR = reference.CONFIG_DIR = data
        reference.CONFIG_FILE = data / 'settings.json'
        reference.CONFIG_FILE.write_text(json.dumps({'setup_done': True, 'auto_graphics': False,
            'check_updates': False, 'ui_mode': 'expert', 'seen_version': reference.VERSION}))
        os.environ['BB_CONFIG'] = str(data / 'bbport.ini')
        root = tk.Tk()
        root.withdraw()
        try:
            ui = reference.Launcher(root, tk, ttk, filedialog, messagebox)
            for page in list(ui.pages):
                ui.show(page)
                root.update()
            pages = {str(widget): page for page, widget in ui.pages.items()}
            entries = []
            for item in ui.search_settings:
                widget, page = item['widget'], None
                while widget is not None and page is None:
                    page = pages.get(str(widget))
                    widget = widget.master
                if page:
                    entry = {key: item.get(key) for key in ('key', 'title', 'hint')} | {'page': page}
                    entry['hint'] = (entry.get('hint') or '').replace(str(data), '{data_dir}')
                    entries.append(entry)
            return {'pages': list(ui.pages),
                    'settings': {key: variable.store for key, variable in ui.vars.items()},
                    'entries': entries}
        finally:
            root.destroy()


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, ensure_ascii=False))
