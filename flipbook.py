import shutil
from pathlib import Path
from re import search

import hou
import webbrowser as wb

from . import config
from .core import ffmpeg, helpers, ocio
from .core.log import hmsg, log
from .core.viewport import TRUE_RESOLUTION_MODES, HouViewport, processEvents, fitsResolution

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

    record(viewport, flipbook_options, file_resolution,
           mode=advanced.get("true_resolution", "auto"),
           black_background=data.get("blackbg"),
           hide_background_image=data.get("bgimage"))

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

    video = None
    if data.get("convertvideo") and files_keeped:
        video = convert(settingsfile, viewport,
                sequence=output_filepath,
                frame_padding=frame_padding,
                frame_range=(frame_start, frame_end),
                resolution=file_resolution,
                pixel_aspect=float(data.get("aspect") or 1),
                video_ext=fb_video_ext)

    if data.get("openfolder"):
        openResult(advanced.get("open_after", "video"), video, sequence_folder, write_folder)


def openResult(open_after: str, video, sequence_folder: Path, write_folder: Path):
    """Open the video in the default player, or the folder with the result.

    open_after: "video" - the converted video if there is one, otherwise the sequence folder
                "folder" - always the folder
    """
    if open_after == "video" and video is not None and Path(video).exists():
        target = Path(video)
    elif sequence_folder.exists():
        target = sequence_folder
    else:
        target = write_folder
    log.info("Opening: %s", target)
    wb.open(target.as_uri())


COLOR_TRANSFORMS = ("ocio", "srgb", "gamma22", "bt709", "none")


def chooseRecorder(viewport, resolution: tuple, mode: str):
    """Viewer to record from: the maximized viewport, or a torn off copy sized to the resolution.

    Returns:
        HouViewport: recorder (call .close() after recording, it's a no-op for the main viewer)
    """
    if mode not in TRUE_RESOLUTION_MODES:
        log.warning("Unknown true_resolution '%s', expected one of: %s. Using auto",
                    mode, ", ".join(TRUE_RESOLUTION_MODES))
        mode = "auto"
    if mode == "off":
        return viewport
    if mode == "auto":
        viewport.maximize_viewport()
        processEvents()
        if fitsResolution(viewport.viewportSize(), resolution):
            return viewport
        viewport.maximize_viewport(False)
    try:
        torn, achieved = viewport.tearOff(resolution)
    except Exception as e:  # any Houdini/Qt failure: record the usual way instead
        log.warning("Can't tear off viewer copy, recording in the maximized viewport: %s", e)
        return viewport
    if not fitsResolution(achieved, resolution):
        log.warning("Viewer window is limited to %sx%s by the OS, flipbook will be scaled to %sx%s",
                    achieved[0], achieved[1], resolution[0], resolution[1])
    else:
        log.info("Recording %sx%s in a torn off viewer copy", resolution[0], resolution[1])
    return torn


def record(viewport, flipbook_options, resolution: tuple, mode: str = "auto",
           black_background: bool = False, hide_background_image: bool = False):
    """Record flipbook, always returning viewers to their original state"""
    recorder = viewport
    prev_color_scheme = None
    try:
        recorder = chooseRecorder(viewport, resolution, mode)
        if recorder is viewport:
            # Maximize window to get better quality
            viewport.maximize_viewport()

        # Remember viewer state before changing it
        if black_background:
            prev_color_scheme = recorder.colorScheme()
            recorder.colorScheme("dark")
        if hide_background_image:
            recorder.displayBackgroundImage(False)

        recorder.startFlipbook(flipbook_options)
    finally:
        if prev_color_scheme is not None:
            recorder.colorScheme(prev_color_scheme)
        if hide_background_image:
            recorder.displayBackgroundImage()
        recorder.close()
        viewport.maximize_viewport(False)


def convert(settings: dict, viewport, sequence: Path, frame_padding: str, frame_range: tuple,
            resolution: tuple, pixel_aspect: float, video_ext: str):
    """Convert written flipbook sequence to video.

    Color (advanced.color_transform):
        ocio    - OCIO display/view of the viewer via hoiiotool (falls back to srgb if it isn't available/fails)
        srgb, gamma22, bt709 - fixed transfer function for linear EXR
        none    - pass pixel values as is (for display-encoded sequences)

    Args:
        sequence (Path): flipbook output path with frame token, like .../name.v001.$F4.exr
        frame_padding (str): frame token in the file name, like "$F4"

    Returns:
        Path | None: written video, None when conversion failed or was cancelled
    """
    advanced = settings["advanced"]
    padding = int(frame_padding.replace("$F", "") or 1)
    is_exr = sequence.suffix.lower() == ".exr"
    color_transform = advanced.get("color_transform", "ocio") if is_exr else "none"
    if color_transform not in COLOR_TRANSFORMS:
        log.warning("Unknown color_transform '%s', expected one of: %s. Using srgb",
                    color_transform, ", ".join(COLOR_TRANSFORMS))
        color_transform = "srgb"

    converter = ffmpeg.FFmpeg(cmd=settings["ffmpeg_cmd"], binary=advanced.get("ffmpeg_path", ""),
                              codec=advanced.get("video_codec", "auto"))
    if not converter.available:
        return None

    ffmpeg_input = sequence
    temp_folder = None
    if color_transform == "ocio":
        temp_folder = sequence.parent / "_ocio_tmp"
        display_sequence = temp_folder / (sequence.stem + ".png")
        result = ocioTransform(advanced, viewport, sequence, display_sequence, frame_padding, frame_range, padding)
        if getattr(result, "cancelled", False):
            shutil.rmtree(temp_folder, ignore_errors=True)
            log.warning("Video conversion cancelled, image sequence is kept")
            return None
        if result:
            ffmpeg_input = display_sequence
            color_transform = "none"  # already display-encoded
        else:
            log.warning("OCIO transform unavailable, falling back to srgb transfer")
            color_transform = "srgb"

    # name.v001.$F4.exr -> name.v001.mov (works for name_$F4.exr too)
    output_video = sequence.parent / (sequence.name.partition(frame_padding)[0].rstrip("._-") + f".{video_ext}")
    result = converter.convert_to_video(
        fps=helpers.ffmpegFps(hou.fps()),
        resolution=f"{resolution[0]}x{resolution[1]}",
        aspect=resolution[0] / resolution[1] * pixel_aspect,
        start_frame=int(frame_range[0]),
        input=ffmpeg_input.as_posix().replace(frame_padding, f"%0{padding}d"),
        output=output_video.as_posix(),
        exr_transfer="" if color_transform == "none" else color_transform,
        total_frames=int(frame_range[1]) - int(frame_range[0]) + 1)

    if temp_folder is not None and temp_folder.exists():
        shutil.rmtree(temp_folder, ignore_errors=True)

    if getattr(result, "cancelled", False):
        log.warning("Video conversion cancelled, image sequence is kept")
        Path(output_video).unlink(missing_ok=True)  # partial video
    if result and advanced.get("conversion_delete_input_sequence"):
        for frame in sequenceFiles(sequence, frame_padding):
            frame.unlink()
    return output_video if result else None


def ocioTransform(advanced: dict, viewport, sequence: Path, display_sequence: Path,
                  frame_padding: str, frame_range: tuple, padding: int):
    """Returns process.Result of hoiiotool, or None when OCIO isn't available"""
    tool = ocio.findOiiotool(advanced.get("oiiotool_path", ""))
    if not tool:
        log.warning("hoiiotool/oiiotool not found")
        return None
    display, view = ocio.displayView(viewport.getPaneTab(),
                                     advanced.get("ocio_display", ""), advanced.get("ocio_view", ""))
    if not display or not view:
        log.warning("Can't resolve OCIO display/view")
        return None
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
