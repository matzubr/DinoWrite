import shutil
from pathlib import Path
from re import search

import hou
import webbrowser as wb

from . import config
from .core import ffmpeg, helpers, ocio
from .core.log import hmsg, log
from .core.viewport import HouViewport

def start(data,kwargs):

    settingsfile = config.load()
    paths = settingsfile["paths"]
    advanced = settingsfile["advanced"]

    # Parsing settings
    fb_name =      paths.get("fb_name")
    fb_video_ext = paths.get("fb_video_ext")
    fb_folder = hou.text.expandString(paths.get("fb_folder"))

    frame_padding = search(r"\$F\d+",fb_name)
    if not frame_padding:
        log.error("No frame padding like '$F4' in 'fb_name' found")
        return 0
    else:
        frame_padding = frame_padding[0]

    # Parsing data
    file_name = data.get("name")
    file_format = data.get("fileformat")
    file_resolution = tuple((int(data.get("resx")), int(data.get("resy"))))

    frame_start = helpers.evalFrame(data.get("framestart"))
    frame_end = helpers.evalFrame(data.get("frameend"))
    if frame_start is None or frame_end is None:
        hmsg(f"Can't evaluate frame range:\n{data.get('framestart')} - {data.get('frameend')}", level="error")
        return 0
    frame_end = max(frame_start,frame_end)

    # Default path to write flipbook
    write_folder = Path(fb_folder.format(name=file_name)).resolve()
    
    if not write_folder.exists():
        write_folder.mkdir(parents=True, exist_ok=True)

    # Get newer folder version of flipbook (only 'vNNN' folders, compared as numbers)
    ver_str = helpers.nextVersion(write_folder)

    # Set output filename
    filename = fb_name.format(
        name=file_name, version=ver_str, fileformat=file_format)
    output_filepath = write_folder / ver_str / filename

    # Get Viewport
    viewport = HouViewport(kwargs)

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
        log.warning(f"No frames were written to:\n{sequence_folder.as_posix()}")

    if files_keeped and advanced['delete_incomplete_fb']:
        fb_length = int(frame_end - frame_start) + 1
        files = [x for x in sequence_folder.iterdir() if x.is_file()]
        tolerance = min(10, fb_length // 10) #extra padding up to 10 frames, smaller for short ranges

        if len(files) < fb_length - tolerance:
            [x.unlink() for x in files]
            if not any(sequence_folder.iterdir()):
                sequence_folder.rmdir()
            files_keeped=False
            log.warning(f"Incomplete flipbook deleted ({len(files)} of {fb_length} frames):\n{sequence_folder.as_posix()}")

    if data.get("convertvideo") and files_keeped:
        convert(settingsfile, viewport,
                sequence=output_filepath,
                frame_padding=frame_padding,
                frame_range=(frame_start, frame_end),
                resolution=file_resolution,
                pixel_aspect=float(data.get("aspect") or 1),
                video_ext=fb_video_ext)


COLOR_TRANSFORMS = ("ocio", "srgb", "gamma22", "bt709", "none")


def convert(settings: dict, viewport, sequence: Path, frame_padding: str, frame_range: tuple,
            resolution: tuple, pixel_aspect: float, video_ext: str) -> bool:
    """Convert written flipbook sequence to video.

    Color (advanced.color_transform):
        ocio    - OCIO display/view of the viewer via hoiiotool (falls back to srgb if it isn't available/fails)
        srgb, gamma22, bt709 - fixed transfer function for linear EXR
        none    - pass pixel values as is (for display-encoded sequences)

    Args:
        sequence (Path): flipbook output path with frame token, like .../name.v001.$F4.exr
        frame_padding (str): frame token in the file name, like "$F4"
    """
    advanced = settings["advanced"]
    padding = int(frame_padding.replace("$F", "") or 1)
    is_exr = sequence.suffix.lower() == ".exr"
    color_transform = advanced.get("color_transform", "ocio") if is_exr else "none"
    if color_transform not in COLOR_TRANSFORMS:
        log.warning("Unknown color_transform '%s', expected one of: %s. Using srgb",
                    color_transform, ", ".join(COLOR_TRANSFORMS))
        color_transform = "srgb"

    converter = ffmpeg.FFmpeg(cmd=settings["ffmpeg_cmd"], binary=advanced.get("ffmpeg_path", ""))
    if not converter.available:
        return False

    ffmpeg_input = sequence
    temp_folder = None
    if color_transform == "ocio":
        temp_folder = sequence.parent / "_ocio_tmp"
        display_sequence = temp_folder / (sequence.stem + ".png")
        if ocioTransform(advanced, viewport, sequence, display_sequence, frame_padding, frame_range, padding):
            ffmpeg_input = display_sequence
            color_transform = "none"  # already display-encoded
        else:
            log.warning("OCIO transform unavailable, falling back to srgb transfer")
            color_transform = "srgb"

    # name.v001.$F4.exr -> name.v001.mov (works for name_$F4.exr too)
    output_video = sequence.parent / (sequence.name.partition(frame_padding)[0].rstrip("._-") + f".{video_ext}")
    success = converter.convert_to_video(
        fps=helpers.ffmpegFps(hou.fps()),
        resolution=f"{resolution[0]}x{resolution[1]}",
        aspect=resolution[0] / resolution[1] * pixel_aspect,
        start_frame=int(frame_range[0]),
        input=ffmpeg_input.as_posix().replace(frame_padding, f"%0{padding}d"),
        output=output_video.as_posix(),
        exr_transfer="" if color_transform == "none" else color_transform)

    if temp_folder is not None and temp_folder.exists():
        shutil.rmtree(temp_folder, ignore_errors=True)

    if success and advanced.get("conversion_delete_input_sequence"):
        for frame in sequenceFiles(sequence, frame_padding):
            frame.unlink()
    return success


def ocioTransform(advanced: dict, viewport, sequence: Path, display_sequence: Path,
                  frame_padding: str, frame_range: tuple, padding: int) -> bool:
    tool = ocio.findOiiotool(advanced.get("oiiotool_path", ""))
    if not tool:
        log.warning("hoiiotool/oiiotool not found")
        return False
    display, view = ocio.displayView(viewport.getPaneTab(),
                                     advanced.get("ocio_display", ""), advanced.get("ocio_view", ""))
    if not display or not view:
        log.warning("Can't resolve OCIO display/view")
        return False
    return ocio.applyDisplayTransform(
        tool, ocio.configPath(),
        input_pattern=sequence.as_posix().replace(frame_padding, "#"),
        output_pattern=display_sequence.as_posix().replace(frame_padding, "#"),
        frame_range=frame_range, padding=padding, display=display, view=view,
        input_space=advanced.get("ocio_input_space", ocio.DEFAULT_INPUT_SPACE))


def sequenceFiles(sequence: Path, frame_padding: str) -> list:
    """Frames of this sequence only (not the video or other files in the folder)"""
    prefix, _, suffix = sequence.name.partition(frame_padding)
    if not sequence.parent.exists():
        return []
    return [f for f in sequence.parent.iterdir()
            if f.is_file() and f.name.startswith(prefix) and f.name.endswith(suffix)
            and f.name[len(prefix):len(f.name) - len(suffix)].isdigit()]
