
Write flipbooks to disk easily

This is a fully Python tool that allows you to write flipbooks in Houdini

![Alt text](https://i.imgur.com/fViOjuG.png "DinoWriter")

## Features
---
 - Open source with comprehensive explanations
 - A lot of customization available for the UI and settings
 - Keeping track of previous settings
 - Folders are automatically versioned
 - Enlarge the viewport window to improve quality
 - Support multiple viewports
 - Displaying existing flipbooks (can grab their name)
 - Grabs resolution from camera or divides it in half
 - Convert the sequence to video using FFmpeg
 - Opening the writing folder after flipbook is done 
 - A bunch of tips and tricks that I used in my workflow
 - Custom metadata (DEV)
## Tips
---
There are a bunch of little tips that I use in my daily workflow to make it easier and more readable.

1. Off background image used when working with film footage and dealing with shot timing. So later, you can easily merge your flipbooks with shot source footage.  
2. Turning on the black background provides a little improvement when merging with the source.  
3. Using version namespace in the file name allows you to see your flipbook version easily in Nuke without going inside the read node. Just select your read node and press the alt+up/down arrow to switch versions.

### Settings
---
Defaults live in `settings.json` inside the tool folder. Your changes are saved separately to
`$HOUDINI_USER_PREF_DIR/DinoWrite/settings.json` (or the path in `$DINOWRITE_SETTINGS`) and contain only the values
that differ from defaults, so updating the tool doesn't wipe them.

### Attentions
---
- By default, the script deletes your sequence if it doesn't cover the full length of the frame range (you can disable it in the `settings.json` file)  
- By default, after converting sequence to video, script delete sequence files (which can also be disabled in `settings.json`)  
- By default, sequences are written in native pixel aspect, but Houdini flipbooks cannot handle that with the original resolution. It can be fixed in Nuke via the reformat node. But ffmpeg conversion handles pixel aspect and gives you the correct image (which can also be modified in `settings.json`)

- Video colors (`advanced.color_transform` in settings):
  - `ocio` (default): the same OCIO display/view as the Scene Viewer, applied with `hoiiotool` that ships with Houdini (`$HFS/bin/hoiiotool`). Display/view can be fixed with `ocio_display` / `ocio_view`, EXR color space with `ocio_input_space` (default `scene_linear` role). Falls back to `srgb` if hoiiotool is missing or fails
  - `srgb`, `gamma22`, `bt709`: fixed transfer for linear EXR
  - `none`: pass pixels as is. Use it if your EXRs are already display-encoded (video looks washed out)
- ffmpeg is taken from `advanced.ffmpeg_path`, then `$PDG_FFMPEG`, then the one that ships with Houdini (`$HFS/bin/hffmpeg`), then system PATH
- After a successful conversion only frames of the converted sequence are deleted (`conversion_delete_input_sequence`), other files in the folder are kept

## Installation 
---
1. Download source files 
2. Copy them to your 

| os | location |
|---|---|
| win | %USERNAME%/Documents/houdini%.% |
| linux | $HOME/houdini%.% |
| mac | /Users/%USERNAME%/Library/Preferences/houdini%.% |

3. Create ShelfTool with following code:

```
import DinoWrite
DinoWrite.show(kwargs)
```
Pay attention that `DinoWrite` is name of the folder that you copied to the python lib folder.
Old shelf code `from DinoWrite import ui; ui.DinoWriter(kwargs)` still works.

Works with Houdini 21+ (PySide6 / Qt6) and older Qt5 builds (PySide2).

## Development
---
Local development uses [uv](https://docs.astral.sh/uv/). Houdini doesn't need it: it imports the folder directly.

```
uv sync            # create .venv with dev tools
uv run pytest      # run tests (hou, pxr and PySide2 are stubbed)
uv run ruff check  # lint
```

Use `DinoWrite.show(kwargs, reload=True)` in a shelf tool to pick up code changes without restarting Houdini.

Project layout:

| path | what |
|---|---|
| `__init__.py` | `show()` entry point, dev `reload_modules()` |
| `main.py` | main window |
| `config.py` | settings: defaults + user overrides |
| `flipbook.py` | recording + conversion pipeline |
| `core/` | Houdini logic without Qt: viewport, ffmpeg, OCIO (hoiiotool), helpers, logging |
| `gui/` | Qt: PySide6/PySide2 compat (`qt.py`), widgets, styles, icons |
| `settings.json` | default settings |

### Credits
- [Alexander Marchenko](https://www.linkedin.com/in/cg-alexander-marchenko/)
- Alexandra Ushakova
