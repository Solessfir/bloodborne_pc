# SPDX-License-Identifier: GPL-2.0-or-later
"""Reference labels and hints captured from the complete launcher; audited by tools/audit_launcher_settings.py."""
FIELDS = {
    "play": [
        {
            "key": "goal",
            "title": "Your goal",
            "hint": "Smooth, Balanced, Quiet"
        },
        {
            "key": "play_with",
            "title": "You play with",
            "hint": "Controller, Keyboard and mouse"
        }
    ],
    "picture": [
        {
            "key": "goal",
            "title": "Your goal",
            "hint": ""
        },
        {
            "key": "button:undo",
            "title": "Undo",
            "hint": "Made for your PC"
        },
        {
            "key": "auto_graphics",
            "title": "Adjust them automatically when the hardware changes",
            "hint": "Show the settings one by one"
        },
        {
            "key": "fullscreen",
            "title": "Fullscreen",
            "hint": "Recommended: the game gets the display to itself (smoother, and 4K downsampling works)."
        },
        {
            "key": "exclusive_fullscreen",
            "title": "Exclusive fullscreen",
            "hint": "Fullscreen takes the display over instead of covering the desktop: frames can arrive more evenly, but switching to another window takes a moment. Only with Fullscreen on."
        },
        {
            "key": "game_monitor",
            "title": "Monitor",
            "hint": "Used for output resolution. Your compositor controls which monitor the game opens on."
        },
        {
            "key": "output_res",
            "title": "Resolution",
            "hint": "The size of the picture. Your goal picks it for this PC; change it here if you like."
        },
        {
            "key": "window_size",
            "title": "Window size",
            "hint": ""
        },
        {
            "key": "hdr",
            "title": "Allow HDR output",
            "hint": "When HDR is enabled in your desktop session and the display supports it."
        },
        {
            "key": "effect_chromatic_aberration",
            "title": "Chromatic aberration",
            "hint": ""
        },
        {
            "key": "effect_dof",
            "title": "Depth of field",
            "hint": ""
        },
        {
            "key": "effect_motion_blur",
            "title": "Motion blur",
            "hint": ""
        },
        {
            "key": "show_fps",
            "title": "Show the FPS counter",
            "hint": ""
        }
    ],
    "controls": [
        {
            "key": "play_with",
            "title": "You play with",
            "hint": "Keyboard and mouse turns the mouse camera on and uses the Dark Souls III layout (asked first if you changed keys yourself). Controller turns the mouse camera off, so the game leaves the pointer alone. Keys and controller buttons keep working either way."
        },
        {
            "key": "button_prompts",
            "title": "Button prompts",
            "hint": "The game's button icons: your keyboard and mouse keys while you play with them, the controller's (PlayStation, Xbox or Switch) while you use it."
        },
        {
            "key": "menu_key",
            "title": "In-game menu key",
            "hint": "Opens the settings menu during play. No key: the menu only opens with the controller, or not at all; the launcher has every setting either way. A key you move the menu off can be bound to the game."
        },
        {
            "key": "menu_pad",
            "title": "In-game menu on the controller",
            "hint": "Off if pressing both sticks or Select + Start opens it by accident."
        },
        {
            "key": "controller_test",
            "title": "Controller test",
            "hint": "Press the buttons: what lights up here reaches the game."
        },
        {
            "key": "button:reset_controller",
            "title": "Reset controller buttons",
            "hint": ""
        },
        {
            "key": "mouse:layout",
            "title": "Layout",
            "hint": "WASD, Space to dodge, left click / Shift + left click to attack, right click / Shift + right click (or Ctrl) for the off hand, E interact, R item, F vial, Q lock on, Tab or Esc menu, and the 1:1 mouse camera. Replaces the keyboard and mouse bindings; the controller keeps its own."
        },
        {
            "key": "mouse:enabled",
            "title": "Enable mouse look",
            "hint": ""
        },
        {
            "key": "mouse:stick",
            "title": "Mouse controls",
            "hint": ""
        },
        {
            "key": "mouse:camera",
            "title": "Camera",
            "hint": "Direct turns the game's camera by exact angles: no stick acceleration or turn-speed cap. While locked on, moving the mouse switches target."
        },
        {
            "key": "mouse:camera_sensitivity",
            "title": "Sensitivity (direct)",
            "hint": "How far the direct camera turns per mouse movement (1.00 = 900 counts per radian)."
        },
        {
            "key": "mouse:speed",
            "title": "Sensitivity (stick)",
            "hint": "How fast the camera turns for a given mouse movement in stick emulation."
        },
        {
            "key": "mouse:speed_offset",
            "title": "Minimum turn speed (stick)",
            "hint": "A constant added on top of sensitivity; raises the floor for slow movements without affecting fast ones as much."
        },
        {
            "key": "mouse:sensitivity_y",
            "title": "Vertical sensitivity",
            "hint": "Up and down as a multiple of left and right (1.00 = the same)."
        },
        {
            "key": "mouse:invert_x",
            "title": "Invert horizontal",
            "hint": ""
        },
        {
            "key": "mouse:invert_y",
            "title": "Invert vertical",
            "hint": ""
        }
    ],
    "online": [
        {
            "key": "online",
            "title": "Play online",
            "hint": "Off: the game stays offline, as before. Cheats, debug features and third-party patches run offline only."
        },
        {
            "key": "online_pool",
            "title": "Play with",
            "hint": "SuperMedo Server (recommended): supermedo.com's own servers, with a free account made below."
        },
        {
            "key": "online_npid",
            "title": "Online ID (NPID)",
            "hint": "Your account name on that server, not your email."
        },
        {
            "key": "online_password",
            "title": "Password",
            "hint": "Saved on this PC with the other launcher settings."
        },
        {
            "key": "supermedo_npid",
            "title": "Account",
            "hint": ""
        },
        {
            "key": "button:signout",
            "title": "Sign out",
            "hint": "SuperMedo account"
        },
        {
            "key": "button:signin_supermedo",
            "title": "Sign in with Discord",
            "hint": "Discord makes your SuperMedo account the first time, named after your Discord name; nothing to remember. Sign in again on any PC."
        },
        {
            "key": "button:signin_password",
            "title": "Online ID and password",
            "hint": "Sign in"
        },
        {
            "key": "button:create_account",
            "title": "Create account",
            "hint": "New SuperMedo account"
        },
        {
            "key": "party_key",
            "title": "Your party",
            "hint": "While you are in a party, your bells and summon signs find only your party's hunters, with no level limit. Leave the password in the game's network settings empty: the party brings you together."
        },
        {
            "key": "online_community",
            "title": "Game server",
            "hint": "game.supermedo.com by default. Only the name is needed; the game picks the ports."
        },
        {
            "key": "online_server",
            "title": "Server address",
            "hint": "host:port from the person who runs the server (Seamless co-op: its own address)."
        },
        {
            "key": "online_webapi",
            "title": "WebAPI address",
            "hint": "Of the shadNet server, not the game server. Leave empty: the server address with port 31315 is used."
        },
        {
            "key": "online_upnp",
            "title": "UPnP (open a port on the router automatically)",
            "hint": "Turn it off on Tailscale or another VPN."
        },
        {
            "key": "online_relay",
            "title": "Russia route (through a relay in Kazakhstan)",
            "hint": "Only if your network in Russia cannot reach the SuperMedo server: the connection goes through a relay to the same server and players. Leave it off otherwise."
        },
        {
            "key": "button:test_connection",
            "title": "Test connection",
            "hint": "Connection"
        }
    ],
    "saves": [
        {
            "key": "characters",
            "title": "Your characters",
            "hint": "Saves"
        },
        {
            "key": "button:import",
            "title": "Import saves from other versions",
            "hint": "From other versions"
        },
        {
            "key": "auto_backup",
            "title": "Back up automatically before every start",
            "hint": "Backups"
        },
        {
            "key": "exit_backup",
            "title": "Back up after every game exit",
            "hint": "Backups"
        },
        {
            "key": "button:backup",
            "title": "Back up now",
            "hint": "Backups"
        },
        {
            "key": "button:restore",
            "title": "Restore a backup",
            "hint": "Backups"
        },
        {
            "key": "button:add_backup",
            "title": "Add a backup file…",
            "hint": "Backups"
        },
        {
            "key": "user_dir",
            "title": "Saves folder",
            "hint": "Your characters, their backups and the trophies. Empty: {data_dir}/user."
        },
        {
            "key": "cache_dir",
            "title": "Cache folder",
            "hint": "Shaders, logs and temporary files of this installation. Empty: its user folder ({data_dir}/user), so every version and every PC keeps its own shaders, wherever the saves are."
        }
    ],
    "mods": [
        {
            "key": "mods_enabled",
            "title": "Load mods",
            "hint": "Loose-file mods, each in its own folder (with dvdroot_ps4, or chr\\, parts\\ … directly)."
        },
        {
            "key": "mods_dir",
            "title": "Mods folder",
            "hint": "Empty: {data_dir}/mods"
        },
        {
            "key": "patches_dir",
            "title": "Patches folder",
            "hint": "shadPS4/GoldHEN XML patch files for version 1.09. Empty: {data_dir}/patches"
        }
    ],
    "language": [
        {
            "key": "ui_language",
            "title": "Launcher language",
            "hint": "Applies when the launcher opens again."
        },
        {
            "key": "translucent_window",
            "title": "Slightly translucent window",
            "hint": "A hint of what lies behind the launcher: a blurred title bar (Windows 11) and the window at 98.5 %. Off: fully opaque, easiest to read."
        },
        {
            "key": "on_play",
            "title": "When the game starts",
            "hint": "Closed, it ends with the game; minimized, it waits on the task bar (or in the tray)."
        },
        {
            "key": "reopen_after_game",
            "title": "Open the launcher again when the game closes",
            "hint": "After a crash it always comes back, with the log."
        },
        {
            "key": "button:shortcut",
            "title": "Desktop shortcut",
            "hint": ""
        },
        {
            "key": "button:steam",
            "title": "Add to Steam",
            "hint": ""
        }
    ],
    "trophies": [
        {
            "key": "button:trophies",
            "title": "Bring achievements from another installation",
            "hint": "From an older port folder, the drive of your old PC or shadPS4: added to yours, none removed."
        }
    ],
    "help": [
        {
            "key": "button:game_files",
            "title": "Check the game files",
            "hint": ""
        },
        {
            "key": "button:shader_cache",
            "title": "Clear the shader cache",
            "hint": "For a black screen, or a broken picture after a driver update. The next start stutters for a few minutes."
        },
        {
            "key": "button:updates",
            "title": "Check for updates",
            "hint": ""
        },
        {
            "key": "button:versions",
            "title": "Other versions…",
            "hint": ""
        },
        {
            "key": "button:news",
            "title": "What's new",
            "hint": ""
        },
        {
            "key": "button:report",
            "title": "Save a report",
            "hint": ""
        },
        {
            "key": "button:copy_summary",
            "title": "Copy a summary",
            "hint": ""
        },
        {
            "key": "button:forum",
            "title": "Open the forum",
            "hint": ""
        },
        {
            "key": "button:show_log",
            "title": "Show the log",
            "hint": ""
        },
        {
            "key": "button:discord",
            "title": "Open the Discord",
            "hint": ""
        }
    ],
    "graphics": [
        {
            "key": "upscaler",
            "title": "Upscaler",
            "hint": "Temporal upscaling with the game's own motion vectors. FSR 4 needs its files (below) and a GPU with INT8 dot products; otherwise the game falls back to FSR 3.1 by itself."
        },
        {
            "key": "fsr411_backend",
            "title": "FSR 4.1 Settings",
            "hint": "FSR 4.1.1 FSR 4.1.2 Vulkan DX12 fsr4vk"
        },
        {
            "key": "preset",
            "title": "Quality preset",
            "hint": "Render scale per axis: Quality renders at 1/1.5 of the output size."
        },
        {
            "key": "output_res",
            "title": "Output resolution",
            "hint": "What the upscaler produces; the HUD is drawn at this size too."
        },
        {
            "key": "hud_position",
            "title": "HUD position (ultrawide)",
            "hint": "21:9 outputs: health, items and Blood Echoes at the screen edges, or in the centred 16:9 area as on a 16:9 screen."
        },
        {
            "key": "sharp_ui",
            "title": "Sharp UI",
            "hint": "Menus, HUD and text drawn at the output resolution instead of 1080p stretched up: much sharper at 1440p and 4K. From the next start, with live resolution changes off; not on ultrawide screens yet. An idea from Awaken's Lantern Engine."
        },
        {
            "key": "live_resolution",
            "title": "Live resolution changes",
            "hint": "Off: outputs other than 1080p are set by a patch at start (fastest; changing them in the game restarts it). On: change output and preset in the game without a restart, at a cost."
        },
        {
            "key": "sharpen",
            "title": "Sharpening (RCAS)",
            "hint": "Off with FSR 4: it sharpens by itself, and sharpening on top of it brings flaws along edges."
        },
        {
            "key": "sharpness",
            "title": "Sharpness",
            "hint": ""
        },
        {
            "key": "object_motion",
            "title": "Object motion vectors",
            "hint": "Less ghosting on characters, cloth and weapons; costs about 5–10% FPS."
        },
        {
            "key": "object_motion_cache",
            "title": "Motion-vector cache (experimental)",
            "hint": ""
        },
        {
            "key": "effect_ssao",
            "title": "Ambient occlusion (SSAO)",
            "hint": ""
        },
        {
            "key": "effect_game_aa",
            "title": "The game's own anti-aliasing",
            "hint": ""
        },
        {
            "key": "effect_dynamic_shadows",
            "title": "Shadows of dynamic lights",
            "hint": ""
        },
        {
            "key": "effect_ssr",
            "title": "Screen-space reflections (not in the original)",
            "hint": ""
        },
        {
            "key": "model_lod",
            "title": "Model detail (LOD)",
            "hint": "A game patch (game version 1.09)."
        },
        {
            "key": "fps_mode",
            "title": "Frame rate",
            "hint": "Community patches for game version 1.09. Unlocked makes the game use the real frame time. Other game versions always run at 30 FPS (the patches would corrupt them)."
        },
        {
            "key": "frame_cap",
            "title": "Frame cap (unlocked mode)",
            "hint": "Above about 120 FPS the game's movement timing breaks (running and rolling get slower, physics and animations can glitch): higher caps are at your own risk."
        },
        {
            "key": "frames_ahead",
            "title": "Frames ahead of the GPU",
            "hint": "1 keeps frame pacing even; more can raise FPS when the graphics card is the limit."
        },
        {
            "key": "present_mode",
            "title": "Presentation",
            "hint": ""
        },
        {
            "key": "low_latency",
            "title": "Low latency (Reflex / Anti-Lag 2)",
            "hint": "Less input lag: the game starts each frame just in time instead of queuing frames for the display. NVIDIA Reflex on GeForce, AMD Anti-Lag 2 on Radeon (current drivers); other GPUs ignore it. Boost keeps the GPU clocks up. Auto: On + Boost on NVIDIA, off on other GPUs."
        },
        {
            "key": "early_submit",
            "title": "Send frames to the GPU in parts",
            "hint": "The graphics card starts drawing a frame while the rest of it is still being prepared, so it is finished about 2 ms sooner. Uses a little more CPU. New: turn it off if you see flickering or missing objects."
        },
        {
            "key": "vrr",
            "title": "Variable refresh rate (VRR)",
            "hint": "For a G-Sync or FreeSync display: the display follows the frames of the game, without tearing and without the lag of V-Sync. Uses V-Sync (Presentation is ignored) and keeps the frame rate a little below the refresh rate (117 FPS at 120 Hz, at most 120). Turn on G-Sync/FreeSync in the NVIDIA/AMD control panel; fullscreen works best."
        },
        {
            "key": "async_pipelines",
            "title": "New shaders while playing",
            "hint": "In the background: a place seen for the first time does not stutter while its shaders are compiled; things drawn with them appear a moment later instead. Each is compiled once and kept."
        },
        {
            "key": "show_fps",
            "title": "FPS",
            "hint": ""
        },
        {
            "key": "show_frame_times",
            "title": "Frame time",
            "hint": ""
        },
        {
            "key": "show_latency",
            "title": "Render latency",
            "hint": ""
        },
        {
            "key": "show_vram",
            "title": "Video memory (VRAM)",
            "hint": ""
        },
        {
            "key": "show_gpu",
            "title": "GPU usage",
            "hint": ""
        },
        {
            "key": "show_cpu",
            "title": "CPU usage",
            "hint": ""
        },
        {
            "key": "show_ram",
            "title": "RAM usage",
            "hint": ""
        },
        {
            "key": "show_fps_graph",
            "title": "Frame time graph",
            "hint": ""
        },
        {
            "key": "counter_colors",
            "title": "Value colours",
            "hint": "Colour-coded shows at a glance how each value stands; plain keeps the counter quiet."
        },
        {
            "key": "frame_gen",
            "title": "Frame generation",
            "hint": "Frames made between two of the game's: 60 FPS on screen becomes 120. Needs a display with that refresh rate (120 Hz or more at 60 FPS); it pauses when the display cannot show the extra frames. Adds a little input latency. Menus and movies are not generated. DLSS needs a GeForce RTX 40 or newer, otherwise FSR 3.1 is used."
        },
        {
            "key": "frame_gen_multiplier",
            "title": "Multiplier",
            "hint": "FSR 3.1 makes one frame (2×); DLSS on a GeForce RTX 50 up to three (4×)."
        },
        {
            "key": "frame_gen_fit_display",
            "title": "Fit to display refresh",
            "hint": "On: no more frames than the display shows (an uncapped game gets fewer generated frames, and the GPU does less). Off: the multiplier as chosen."
        },
        {
            "key": "button:fsr4",
            "title": "Download FSR 4 assets",
            "hint": ""
        },
        {
            "key": "button:fsr4vk",
            "title": "Download fsr4vk",
            "hint": ""
        }
    ],
    "game": [
        {
            "key": "game_dir",
            "title": "Game folder",
            "hint": "Your own game files of CUSA03173 (eboot.bin, sce_module, sce_sys, dvdroot_ps4); version 1.09 for the community patches."
        },
        {
            "key": "dlc_dir",
            "title": "DLC folder",
            "hint": "Your add-ons, one folder each named like SPEXPANSIONDLC03 (The Old Hunters). Only needed with the base game alone; the Game of the Year edition (CUSA03173) has it."
        }
    ],
    "gameplay": [
        {
            "key": "language",
            "title": "Text language",
            "hint": ""
        },
        {
            "key": "voice_language",
            "title": "Voice language",
            "hint": "As in the game uses the original voice setting; other choices use available tracks."
        },
        {
            "key": "player_name",
            "title": "Player name",
            "hint": "Where the game shows the PSN name; empty: the default."
        },
        {
            "key": "skip_intro",
            "title": "Skip the intro logos and movie",
            "hint": ""
        },
        {
            "key": "mute_unfocused",
            "title": "Mute when the game is in the background",
            "hint": ""
        },
        {
            "key": "tweak_no_rally",
            "title": "No Rally (hits do not give health back)",
            "hint": ""
        },
        {
            "key": "tweak_camera_distance",
            "title": "Camera further from the character",
            "hint": ""
        },
        {
            "key": "tweak_no_camera_rotation",
            "title": "No camera auto-rotation while moving",
            "hint": ""
        },
        {
            "key": "tweak_easy_run",
            "title": "Run with less stick tilt (about 70%)",
            "hint": ""
        },
        {
            "key": "tweak_ragdoll",
            "title": "Dark Souls-style ragdoll physics (corpses fly further)",
            "hint": ""
        },
        {
            "key": "tweak_circle_confirm",
            "title": "Japanese/Asian buttons: Circle confirms and interacts, Cross dodges",
            "hint": ""
        },
        {
            "key": "quit_to_desktop",
            "title": "Quit to Desktop in the title menu and in the System menu",
            "hint": ""
        },
        {
            "key": "pc_menu",
            "title": "PC Settings in the System menu: graphics, frame rate, effects and camera in the game",
            "hint": ""
        },
        {
            "key": "rebirth",
            "title": "Rebirth at the Doll: back to your origin's attributes for 5 Insight, levels regained free",
            "hint": ""
        },
        {
            "key": "steady_cloth",
            "title": "Cloth as on PS4 at higher frame rates: capes and coats hang and move as at 30 FPS",
            "hint": ""
        }
    ],
    "cheats": [
        {
            "key": "cheat_no_death",
            "title": "Never die (health stops at 1 HP)",
            "hint": ""
        },
        {
            "key": "cheat_stealth",
            "title": "Enemies do not see you (unless attacked)",
            "hint": ""
        },
        {
            "key": "cheat_silent",
            "title": "Enemies do not hear you",
            "hint": ""
        },
        {
            "key": "cheat_rally_no_decay",
            "title": "Rally never fades",
            "hint": ""
        },
        {
            "key": "cheat_enemy_control",
            "title": "Control the targeted enemy (R3; L3 to go back; not with the free camera)",
            "hint": ""
        },
        {
            "key": "debug_camera",
            "title": "Free camera (hold Cross + L3; keyboard Space + Z)",
            "hint": ""
        },
        {
            "key": "debug_menu",
            "title": "Game debug menu (left touchpad / Tab; needs the debug fonts)",
            "hint": ""
        },
        {
            "key": "button:respec",
            "title": "Respec a character…",
            "hint": ""
        }
    ],
    "system": [
        {
            "key": "gpu_override",
            "title": "Wrong graphics card?",
            "hint": "Detected automatically"
        }
    ],
    "advanced": [
        {
            "key": "button:port_folder",
            "title": "Port folder",
            "hint": ""
        },
        {
            "key": "draw_pipe",
            "title": "Two-stage GPU pipeline",
            "hint": "20–30% faster; switch it off if the game is unstable."
        },
        {
            "key": "readbacks",
            "title": "GPU readbacks",
            "hint": "How exactly data the GPU writes is copied back for the game."
        },
        {
            "key": "low_vram",
            "title": "Low-VRAM profile",
            "hint": "A larger texture budget and, at 1080p with an upscaler, a smaller scene from the start (preset changes then need a restart)."
        },
        {
            "key": "vram_warning",
            "title": "Warn when video memory runs low",
            "hint": "Off: no \"Video memory is running low\" banner in the game. Memory is freed as before; the log still says when it ran short."
        },
        {
            "key": "frame_stats",
            "title": "Frame statistics in the log (every 5 s)",
            "hint": ""
        },
        {
            "key": "mangohud",
            "title": "MangoHud",
            "hint": "Show the MangoHud performance overlay when installed."
        },
        {
            "key": "gpu_profile",
            "title": "GPU time per pass in the log",
            "hint": ""
        },
        {
            "key": "vk_validation",
            "title": "Vulkan validation layers (needs the Vulkan SDK; much slower)",
            "hint": ""
        },
        {
            "key": "extra_env",
            "title": "Extra variables",
            "hint": "NAME=value pairs separated by spaces (README lists them)."
        },
        {
            "key": "button:benchmark",
            "title": "Benchmark for bug reports…",
            "hint": "A fixed route in Cathedral Ward for testers: one zip to send."
        }
    ],
    "log": []
}
