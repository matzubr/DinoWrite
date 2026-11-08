# DinoWrite

Write flipbooks to disk easily. A pure Python tool for Houdini.

![Alt text](https://i.imgur.com/fViOjuG.png "DinoWrite")

## Features
---
 - Folders are automatically versioned (`v001`, `v002`, ...)
 - True resolution: a 4K flipbook on a 2K monitor is recorded in a torn off copy of the viewer sized to 4K (bigger than the screen) instead of stretching the viewport
 - Convert the sequence to video with ffmpeg that ships with Houdini, with progress and cancel (Esc)
 - Video colors match the viewer: OCIO display/view applied with `hoiiotool`
 - Status line shows how the flipbook will be recorded and encoded, flipbook name is checked while typing
 - Opens the result when done: the converted video or the folder
 - Settings dialog behind the gear button, your settings survive tool updates
 - Remembers last used values
 - Supports multiple viewports
 - Shows existing flipbooks (can grab their name)
 - Grabs resolution from camera or divides it in half
 - Works with Houdini 21+ (PySide6 / Qt6) and older Qt5 builds (PySide2)
 - Custom metadata (DEV)

## Installation
---
1. Download the source and put the `DinoWrite` folder into the Python path of your Houdini preferences
   (for Houdini 21 it's `python3.11libs`, create it if missing):

| os | location |
|---|---|
| win | `%USERPROFILE%/Documents/houdini21.0/python3.11libs/DinoWrite` |
| linux | `$HOME/houdini21.0/python3.11libs/DinoWrite` |
| mac | `$HOME/Library/Preferences/houdini/21.0/python3.11libs/DinoWrite` |

   Or keep it anywhere and add its **parent** folder to `PYTHONPATH` with a
   [Houdini package](https://www.sidefx.com/docs/houdini/ref/plugins.html), e.g. `packages/DinoWrite.json`:

```json
{
    "env": [{"PYTHONPATH": "/path/to/folder/that/contains/DinoWrite"}]
}
```

2. Create a shelf tool with this script:

```python
import DinoWrite
DinoWrite.show(kwargs)
```

The folder must be named `DinoWrite`, it's the package name.
Old shelf tools with `from DinoWrite import ui; ui.DinoWriter(kwargs)` keep working.

Run the tool from a Scene Viewer's shelf/hotkey to record that viewer when there are several.

## Settings
---
Click the gear button in the window title. Tabs:

| tab | what |
|---|---|
| General | flipbooks folder, file name template, temp folder, recording viewer, incomplete flipbook cleanup |
| Video | color transform, OCIO display/view/EXR color space, ffmpeg and oiiotool paths (shows which ones are found), sequence cleanup, what to open after writing |
| Presets | resolution and frame range presets for the dropdown menus |
| ffmpeg command | the ffmpeg command template |

Defaults live in `settings.json` inside the tool folder. Your changes are saved separately to
`$HOUDINI_USER_PREF_DIR/DinoWrite/settings.json` (or the path in `$DINOWRITE_SETTINGS`) and contain only the values
that differ from defaults, so updating the tool doesn't wipe them. "Reset to defaults" removes that file.

### Recording viewer
`advanced.true_resolution`:
- `auto` (default): records in the maximized viewport when the resolution fits, otherwise in a floating copy of the viewer sized to the resolution (toolbars hidden, same camera), which is closed afterwards. Background color / background image toggles apply only to the copy
- `always`: always records in the copy
- `off`: maximized viewport, Houdini scales the image to the resolution

Some OSes (macOS, some Linux window managers) don't allow windows bigger than the screen: then a warning is logged and the image is scaled as before. On HiDPI screens a 4K viewport fits into a smaller window.

### Video colors
`advanced.color_transform`:
- `ocio` (default): the same OCIO display/view as the Scene Viewer, applied by `hoiiotool` that ships with Houdini (`$HFS/bin/hoiiotool`). Display/view can be fixed with `ocio_display` / `ocio_view`, EXR color space with `ocio_input_space` (default: `scene_linear` role). Falls back to `srgb` if hoiiotool is missing or fails
- `srgb`, `gamma22`, `bt709`: fixed transfer for linear EXR
- `none`: pass pixels as is. Use it if your EXRs are already display-encoded (video looks washed out)

The video is encoded with BT.709 matrix and tagged as BT.709 / sRGB.

### Tools lookup
- ffmpeg: `advanced.ffmpeg_path` → `$PDG_FFMPEG` → `$HFS/bin/hffmpeg` (ships with Houdini) → system PATH
- oiiotool: `advanced.oiiotool_path` → `$HFS/bin/hoiiotool` → `hoiiotool` / `oiiotool` in system PATH

### Attentions
- After a successful conversion the image sequence is deleted (`conversion_delete_input_sequence`, on by default). Only frames of that sequence are removed, other files in the folder are kept. Cancelled or failed conversion always keeps the sequence
- `delete_incomplete_fb` (off by default) deletes a sequence that doesn't cover the frame range
- Sequences are written in native pixel aspect, Houdini flipbooks can't write it with the original resolution. Fix it in Nuke with a Reformat node; ffmpeg conversion applies the pixel aspect to the video
- `aspect_affects_resolution` and `metadata` in `settings.json` are not implemented yet (DEV)

## Tips
---
1. Off background image is useful when working with film footage and shot timing: later you can easily merge your flipbooks with the shot source footage.
2. Black background gives a little improvement when merging with the source.
3. Version in the file name lets you see the flipbook version in Nuke without going inside the Read node. Select the Read node and press Alt+Up/Down to switch versions.

## Development
---
Local development uses [uv](https://docs.astral.sh/uv/). Houdini doesn't need it, it imports the folder directly.

```
uv sync            # create .venv with dev tools (pytest, ruff, PySide6)
uv run pytest      # run tests
uv run ruff check  # lint
```

Tests replace `hou` with a stub and build the real window offscreen with PySide6 (Qt6, as in Houdini 21).
The repo folder must be named `DinoWrite` for tests to import the package.

In Houdini, `DinoWrite.show(kwargs, reload=True)` reloads all modules to pick up code changes without a restart.

Project layout:

| path | what |
|---|---|
| `__init__.py` | `show()` entry point, `reload_modules()` for development |
| `main.py` | main window |
| `ui.py` | backward compatible import for old shelf tools |
| `flipbook.py` | recording (incl. torn off viewer) and conversion pipeline |
| `config.py` | settings: defaults + user overrides |
| `settings.json` | default settings |
| `core/` | Houdini logic without Qt |
| `core/viewport.py` | Scene Viewer wrapper, torn off copy at true resolution |
| `core/ffmpeg.py` | ffmpeg lookup, command and color filters |
| `core/ocio.py` | OCIO display/view via hoiiotool |
| `core/process.py` | running tools with Houdini progress/cancel |
| `core/helpers.py`, `core/log.py` | versions, frame/name parsing, logging |
| `gui/` | Qt: `qt.py` (PySide6/PySide2), widgets, settings dialog, styles |
| `icons/`, `misc/` | icons and font |
| `tests/` | pytest suite |

## Credits
---
- [Alexander Marchenko](https://www.linkedin.com/in/cg-alexander-marchenko/)
- Alexandra Ushakova
