import subprocess
import sys
import tempfile
from pathlib import Path
from re import search

import hou
import webbrowser as wb

from . import config
from .core import conversion, helpers
from .core.log import hmsg, log
from .core.process import NO_WINDOW
from .core.viewport import TRUE_RESOLUTION_MODES, HouViewport, fitsResolution

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
    if frame_end < frame_start:
        hmsg(f"End frame {frame_end} is before start frame {frame_start}", level="error")
        return 0

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
    # The viewport as seen (not the scene linear beauty pass): the video is encoded like MPlay shows it
    flipbook_options.beautyPassOnly(False)
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

    def finished(video, cancelled=False):
        if data.get("openfolder") and not cancelled:
            openResult(advanced.get("open_after", "video"), video, sequence_folder, write_folder)

    if not files_keeped:
        return finished(None)

    job = conversion.ConversionJob(settingsfile,
                                   sequence=output_filepath,
                                   frame_padding=frame_padding,
                                   frame_range=(frame_start, frame_end),
                                   resolution=file_resolution,
                                   pixel_aspect=float(data.get("aspect") or 1),
                                   video_ext=fb_video_ext,
                                   convert_video=bool(data.get("convertvideo")),
                                   scene_viewer=viewport.getPaneTab(),
                                   camera=viewport.cameraName())
    if not job.hasWork:
        return finished(None)
    # Video / EXR pass run in the background: Houdini stays usable, progress/cancel in a small window
    from .gui.job_window import JobWindow
    JobWindow(job, on_finished=lambda: finished(job.video if job.video and job.video.exists() else None,
                                                cancelled=job.stage == conversion.CANCELLED))


def openResult(open_after: str, video, sequence_folder: Path, write_folder: Path):
    """Open the video in the default player, or the folder with the result.

    open_after: "video" - the converted video if there is one, otherwise the folder
                "folder" - always the folder
    The folder is the one above the sequence (vNNN) with vNNN selected: drag it into Nuke to read the sequence.
    """
    if open_after == "video" and video is not None and Path(video).exists():
        log.info("Opening: %s", video)
        return openPath(Path(video))
    if sequence_folder.exists():
        log.info("Opening: %s", sequence_folder.parent)
        return openPath(sequence_folder, select=True)
    log.info("Opening: %s", write_folder)
    return openPath(write_folder)


def openCommand(path: Path, select: bool = False, platform: str = sys.platform):
    """Command that opens path (or shows it selected in its folder) without waiting for the app"""
    if platform == "win32":
        # explorer returns at once; os.startfile/webbrowser wait while the shell starts the player
        return f'explorer /select,"{path}"' if select else ["explorer", str(path)]
    if platform == "darwin":
        return ["open", "-R", str(path)] if select else ["open", str(path)]
    return ["xdg-open", str(path.parent if select else path)]


def openPath(path: Path, select: bool = False):
    try:
        subprocess.Popen(openCommand(path, select), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **NO_WINDOW)
    except OSError as e:
        log.warning("Can't open %s: %s", path, e)
        wb.open((path.parent if select else path).as_uri())


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
    if getattr(viewport, "isLop", lambda: False)():
        # Solaris keeps its lighting (Headlight Only...) in options Python can't read or copy:
        # a cloned viewer starts with Normal Lighting. Record in the user's viewer instead.
        log.info("Solaris viewer: recording in the maximized viewport (a viewer copy loses its lighting)")
        return viewport
    if mode == "auto":
        viewport.maximize_viewport()
        if fitsResolution(viewport.settle(), resolution):
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
    prev_background_image = None
    was_maximized = viewport.isMaximized()
    try:
        recorder = chooseRecorder(viewport, resolution, mode)
        if recorder is viewport:
            # Maximize window to get better quality
            viewport.maximize_viewport()
            viewport.settle()

        # Remember viewer state before changing it
        if (black_background or hide_background_image) and getattr(recorder, "isLop", lambda: False)():
            # Houdini bug: setting any viewport display option from Python in Solaris breaks the lighting
            # menu ("(no entries)") and the flipbook falls back to Normal Lighting
            log.info("Solaris viewer: black background / background image skipped (they reset its lighting)")
            black_background = hide_background_image = False
        if black_background:
            prev_color_scheme = recorder.colorScheme()
            recorder.colorScheme("dark")
        if hide_background_image:
            prev_background_image = recorder.displayBackgroundImage()
            recorder.displayBackgroundImage(False)

        warmUp(recorder, flipbook_options)
        recorder.startFlipbook(flipbook_options)
    finally:
        if prev_color_scheme is not None:
            recorder.colorScheme(prev_color_scheme)
        if prev_background_image is not None:
            recorder.displayBackgroundImage(prev_background_image)
        recorder.close()
        viewport.maximize_viewport(was_maximized)


def warmUp(recorder, flipbook_options):
    """Render one throwaway frame before the real flipbook.

    The viewport was just resized (maximized or torn off at 4K): even after it settled, the first
    flipbook frame could come out at the old size. One frame into a temp folder takes that hit.
    """
    try:
        warm = flipbook_options.stash()
        first = flipbook_options.frameRange()[0]
        with tempfile.TemporaryDirectory(prefix="dinowrite_warmup_") as temp:
            warm.output((Path(temp) / "warmup.$F4.jpg").as_posix())
            warm.frameRange((first, first))
            warm.outputToMPlay(False)
            recorder.startFlipbook(warm)
    except Exception as e:  # warm-up is only an optimization, never block the real flipbook
        log.warning("Warm-up frame failed: %s", e)

