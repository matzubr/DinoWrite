from pathlib import Path
from importlib import reload
from re import search
from .utils import utils

import hou
import json
import webbrowser as wb

reload(utils)

def start(data,kwargs):

    settingsfile = load_json(Path(__file__).parent / "settings.json")
    paths = settingsfile["paths"]
    advanced = settingsfile["advanced"]
    ffmpeg_cmd = settingsfile["ffmpeg_cmd"]

    # Parsing settings
    fb_name =      paths.get("fb_name")
    fb_video_ext = paths.get("fb_video_ext")
    fb_folder = hou.text.expandString(paths.get("fb_folder"))

    frame_padding = search(r"\$F\d+",fb_name)
    if not frame_padding:
        utils.log.error("No frame padding like '$F4' in 'fb_name' found")
        return 0
    else:
        frame_padding = frame_padding[0]
        frame_padding_int = frame_padding.replace("$F","").zfill(2)

    # Parsing data
    file_name = data.get("name")
    file_format = data.get("fileformat")
    file_resolution = tuple((int(data.get("resx")), int(data.get("resy"))))

    frame_start = utils.evalFrame(data.get("framestart"))
    frame_end = utils.evalFrame(data.get("frameend"))
    if frame_start is None or frame_end is None:
        utils.hmsg(f"Can't evaluate frame range:\n{data.get('framestart')} - {data.get('frameend')}", level="error")
        return 0
    frame_end = max(frame_start,frame_end)

    # Default path to write flipbook
    write_folder = Path(fb_folder.format(name=file_name)).resolve()
    
    if not write_folder.exists():
        write_folder.mkdir(parents=True, exist_ok=True)

    # Get newer folder version of flipbook (only 'vNNN' folders, compared as numbers)
    ver_str = utils.nextVersion(write_folder)

    # Set output filename
    filename = fb_name.format(
        name=file_name, version=ver_str, fileformat=file_format)
    output_filepath = write_folder / ver_str / filename

    # Get Viewport
    viewport = utils.HouViewport(kwargs)

    # Stash flipbook settings
    flipbook_options = viewport.flipbook_settings()

    # Correcting resolution for mpeg4 codec
    if data.get("convertvideo"):
        presx = file_resolution[0] if file_resolution[0] % 2 == 0 else file_resolution[0]-1
        presy = file_resolution[1] if file_resolution[1] % 2 == 0 else file_resolution[1]-1
        file_resolution = tuple((presx, presy))

    # #Flipbook Settings
    flipbook_options.output(output_filepath.as_posix())
    flipbook_options.outputToMPlay(True)
    flipbook_options.useResolution(True)
    flipbook_options.resolution(file_resolution)
    # flipbook_options.cropOutMaskOverlay(True)
    flipbook_options.frameRange(tuple((frame_start, frame_end)))
    flipbook_options.frameIncrement(1)
    flipbook_options.appendFramesToCurrent(False)
    # flipbook_options.beautyPassOnly(True)
    # flipbook_options.renderAllViewports(False)
    flipbook_options.antialias(hou.flipbookAntialias.HighQuality)

    # Remember viewport state before changing it
    prev_color_scheme = viewport.colorScheme() if data.get("blackbg") else None

    try:
        # Maximize window to get better quality
        viewport.maximize_viewport()

        # Change background color
        if data.get("blackbg"):
            viewport.colorScheme("dark")

        # Disable background image preview
        if data.get("bgimage"):
            viewport.displayBackgroundImage(False)

        # Start Flipbook
        viewport.startFlipbook(flipbook_options)
    finally:
        # Always return viewport to its original state, even if flipbook failed
        viewport.maximize_viewport(False)

        if prev_color_scheme is not None:
            viewport.colorScheme(prev_color_scheme)

        if data.get("bgimage"):
            viewport.displayBackgroundImage()

    # #Open dir
    if data.get("openfolder"):
        wb.open(write_folder.as_uri())

    sequence_folder = output_filepath.parent
    files_keeped = sequence_folder.exists()
    if not files_keeped:
        utils.log.warning(f"No frames were written to:\n{sequence_folder.as_posix()}")

    if files_keeped and advanced['delete_incomplete_fb']:
        fb_length = int(frame_end - frame_start) + 1
        files = [x for x in sequence_folder.iterdir() if x.is_file()]
        tolerance = min(10, fb_length // 10) #extra padding up to 10 frames, smaller for short ranges

        if len(files) < fb_length - tolerance:
            [x.unlink() for x in files]
            if not any(sequence_folder.iterdir()):
                sequence_folder.rmdir()
            files_keeped=False
            utils.log.warning(f"Incomplete flipbook deleted ({len(files)} of {fb_length} frames):\n{sequence_folder.as_posix()}")

    if data.get("convertvideo") and files_keeped:
        fps = utils.ffmpegFps(hou.fps())
        aspect = float(data.get("aspect") or 1)
        resolution = f"{file_resolution[0]}x{file_resolution[1]}"
        start_frame = int(frame_start)

        ffmpeg = utils.FFmpeg(config_path=None,
                            cmd=ffmpeg_cmd,
                            binary=advanced.get("ffmpeg_path", ""))

        input_files = output_filepath.as_posix().replace(frame_padding, f"%{frame_padding_int}d")
        output_video = (output_filepath.parent /
                        filename).as_posix().replace(f"{frame_padding}.{file_format}", fb_video_ext)

        ffmpeg.convert_to_video(fps=fps,
                                resolution=resolution,
                                aspect=file_resolution[0]/file_resolution[1]*aspect,
                                start_frame=start_frame,
                                input=input_files,
                                output=output_video,
                                delete_input=advanced['conversion_delete_input_sequence'],
                                exr_transfer=advanced.get("exr_transfer", "srgb") if file_format == "exr" else "")

def load_json(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}