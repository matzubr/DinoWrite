"""Flipbook sequence -> video conversion as a pollable job.

Everything that needs hou (fps, OCIO display/view, tool lookup) is resolved in the constructor,
on the main thread. Then the job only polls external processes: the GUI calls step() from a QTimer,
so Houdini stays usable while hoiiotool/ffmpeg work. Without UI, runBlocking() does the same in a loop.

Stages:
    ocio    - hoiiotool OCIO display transform, several processes on parts of the frame range
    encode  - ffmpeg, trying encoders one by one until one works
"""
import shutil
import tempfile
import time
from pathlib import Path

import hou

from . import ffmpeg, helpers, ocio, process
from .log import log

COLOR_TRANSFORMS = ("auto", "ocio", "srgb", "gamma22", "bt709", "none")
OCIO_TEMP_FOLDER = "_ocio_tmp"

PENDING, OCIO, ENCODE, DONE, FAILED, CANCELLED = "pending", "ocio", "encode", "done", "failed", "cancelled"


def sequenceFiles(sequence: Path, frame_padding: str) -> list:
    """Frames of this sequence only (not the video or other files in the folder)"""
    prefix, _, suffix = sequence.name.partition(frame_padding)
    if not sequence.parent.exists():
        return []
    return [f for f in sequence.parent.iterdir()
            if f.is_file() and f.name.startswith(prefix) and f.name.endswith(suffix)
            and f.name[len(prefix):len(f.name) - len(suffix)].isdigit()]


def _describe(display_view: tuple) -> str:
    return " / ".join(part or "?" for part in display_view)


def videoPath(sequence: Path, frame_padding: str, video_ext: str) -> Path:
    """name.v001.$F4.exr -> name.v001.mov (works for name_$F4.exr too)"""
    return sequence.parent / (sequence.name.partition(frame_padding)[0].rstrip("._-") + f".{video_ext}")


class ConversionJob:
    """Convert a written flipbook sequence to video.

    Color (advanced.color_transform):
        auto    - (default) "none" for regular viewport flipbooks, "ocio" for beauty pass flipbooks:
                  without "Beauty pass only" Houdini writes the whole viewport as you see it, with the display
                  transform already applied; only the beauty pass is linear. Transforming display-referred
                  frames again gives a darker, more contrasty, oversaturated video.
        ocio    - OCIO display/view via hoiiotool (falls back to srgb if it isn't available/fails)
        srgb, gamma22, bt709 - fixed transfer function for linear EXR
        none    - pass pixel values as is (for display-encoded sequences)

    Args:
        sequence (Path): flipbook output path with frame token, like .../name.v001.$F4.exr
        frame_padding (str): frame token in the file name, like "$F4"
    """

    def __init__(self, settings: dict, scene_viewer, sequence: Path, frame_padding: str, frame_range: tuple,
                 resolution: tuple, pixel_aspect: float, video_ext: str, display_referred: bool = True):
        advanced = settings["advanced"]
        self.sequence = Path(sequence)
        self.frame_padding = frame_padding
        self.padding = int(frame_padding.replace("$F", "") or 1)
        self.frame_range = (int(frame_range[0]), int(frame_range[1]))
        self.total_frames = self.frame_range[1] - self.frame_range[0] + 1
        self.video = videoPath(self.sequence, frame_padding, video_ext)
        self.delete_input = bool(advanced.get("conversion_delete_input_sequence"))
        self.temp_folder = self.sequence.parent / OCIO_TEMP_FOLDER

        self.encode_values = dict(
            fps=helpers.ffmpegFps(hou.fps()),
            resolution=f"{resolution[0]}x{resolution[1]}",
            aspect=resolution[0] / resolution[1] * pixel_aspect,
            start_frame=self.frame_range[0],
            output=self.video.as_posix())

        self.converter = ffmpeg.FFmpeg(cmd=settings["ffmpeg_cmd"], binary=advanced.get("ffmpeg_path", ""),
                                       codec=advanced.get("video_codec", "auto"))
        self.codecs = self.converter.codecs() if self.converter.available else []

        is_exr = self.sequence.suffix.lower() == ".exr"
        self.color_transform = advanced.get("color_transform", "auto") if is_exr else "none"
        if self.color_transform not in COLOR_TRANSFORMS:
            log.warning("Unknown color_transform '%s', expected one of: %s. Using auto",
                        self.color_transform, ", ".join(COLOR_TRANSFORMS))
            self.color_transform = "auto"
        if self.color_transform == "auto":
            self.color_transform = "none" if display_referred else "ocio"
            log.info("Color: %s (%s flipbook)", self.color_transform,
                     "viewport, display-referred" if display_referred else "beauty pass, linear")
        self.ocio_commands = []
        self.display = self.view = ""
        # Display the viewer shows (and display-referred flipbooks are encoded for)
        self.viewer_display = ocio.displayView(scene_viewer, source="viewer")[0] if is_exr else ""
        if self.color_transform == "ocio":
            self.ocio_commands = self._planOcio(advanced, scene_viewer)
            if not self.ocio_commands:
                log.warning("OCIO transform unavailable, falling back to srgb transfer")
                self.color_transform = "srgb"

        self.stage = PENDING
        self.error = ""
        self.codec = None
        self._processes = None
        self._progress_dir = None

    # ---------- planning ----------

    def _planOcio(self, advanced: dict, scene_viewer) -> list:
        tool = ocio.findOiiotool(advanced.get("oiiotool_path", ""))
        if not tool:
            log.warning("hoiiotool/oiiotool not found")
            return []
        source = advanced.get("ocio_source", "mplay")
        self.display, self.view = ocio.displayView(scene_viewer, advanced.get("ocio_display", ""),
                                                   advanced.get("ocio_view", ""), source=source)
        if not self.display or not self.view:
            log.warning("Can't resolve OCIO display/view")
            return []
        log.info("Video OCIO display/view: '%s' / '%s' (source: %s; viewer: %s; config default: %s)",
                 self.display, self.view, source, _describe(ocio.displayView(scene_viewer, source="viewer")),
                 _describe(ocio.displayView(None)))
        display_sequence = self.temp_folder / (self.sequence.stem + ".png")
        return ocio.displayCommands(
            tool, ocio.configPath(),
            input_pattern=self.sequence.as_posix().replace(self.frame_padding, "#"),
            output_pattern=display_sequence.as_posix().replace(self.frame_padding, "#"),
            frame_range=self.frame_range, padding=self.padding, display=self.display, view=self.view,
            input_space=advanced.get("ocio_input_space", ocio.DEFAULT_INPUT_SPACE),
            processes=advanced.get("ocio_processes", 0))

    # ---------- state ----------

    @property
    def finished(self) -> bool:
        return self.stage in (DONE, FAILED, CANCELLED)

    @property
    def succeeded(self) -> bool:
        return self.stage == DONE

    def ocioFramesDone(self) -> int:
        """Frames already written by all hoiiotool processes together"""
        return len(list(self.temp_folder.iterdir())) if self.temp_folder.exists() else 0

    @property
    def progress(self) -> float:
        """Progress of the current stage 0..1"""
        if self.stage == OCIO:
            return min(self.ocioFramesDone() / max(self.total_frames, 1), 1.0)
        if self.stage == ENCODE and self._progress_dir:
            value = ffmpeg.progressFromFile(Path(self._progress_dir.name) / "progress.txt", self.total_frames)
            return min(value or 0.0, 1.0)
        return 1.0 if self.finished else 0.0

    @property
    def status(self) -> str:
        """Human readable current state"""
        percent = f"{self.progress * 100:.0f}%"
        if self.stage == OCIO:
            return (f"OCIO {self.view}: {self.ocioFramesDone()}/{self.total_frames} frames "
                    f"· {len(self.ocio_commands)} processes")
        if self.stage == ENCODE:
            return f"Encoding {self.codec or 'video'}: {percent}"
        if self.stage == DONE:
            return f"Done: {self.video.name}"
        if self.stage == CANCELLED:
            return "Cancelled, image sequence is kept"
        if self.stage == FAILED:
            return f"Failed: {self.error}"
        return "Starting..."

    # ---------- running ----------

    def start(self):
        if not self.converter.available:
            return self._finish(FAILED, "ffmpeg not found")
        if not self.codecs:
            return self._finish(FAILED, "ffmpeg has none of the known encoders")
        if self.ocio_commands:
            self.temp_folder.mkdir(parents=True, exist_ok=True)
            self.stage = OCIO
            self._processes = process.Processes(self.ocio_commands, "DinoWrite: OCIO display transform")
        else:
            self._startEncode()

    def step(self) -> bool:
        """Advance the job; returns True when it's finished"""
        if self.stage == PENDING:
            self.start()
        if self.finished:
            return True
        result = self._processes.poll()
        if result is None:
            return False

        if self.stage == OCIO:
            if result:
                self.color_transform = "none"  # PNGs are already display-encoded
            else:
                log.warning("OCIO transform failed, falling back to srgb transfer")
                shutil.rmtree(self.temp_folder, ignore_errors=True)
                self.color_transform = "srgb"
            self._startEncode()
        elif self.stage == ENCODE:
            if result:
                self._finish(DONE)
            elif self.codecs:
                log.warning("Encoder %s failed, trying %s", self.codec, self.codecs[0])
                self._startEncode()
            else:
                self._finish(FAILED, f"ffmpeg failed: {result.tail(3) or result.error}")
        return self.finished

    def cancel(self):
        if self.finished:
            return
        if self._processes is not None:
            self._processes.cancel()
        self._finish(CANCELLED)

    def runBlocking(self):
        """Run to the end with Houdini progress (for hython / no UI). Returns the video path or None."""
        self.start()
        try:
            with hou.InterruptableOperation("DinoWrite: converting to video", open_interrupt_dialog=True) as op:
                while not self.step():
                    op.updateProgress(self.progress)
                    time.sleep(process.POLL_SECONDS)
        except hou.OperationInterrupted:
            self.cancel()
        return self.video if self.succeeded else None

    def _startEncode(self):
        self.stage = ENCODE
        self.codec = self.codecs.pop(0)
        if self._progress_dir is None:
            self._progress_dir = tempfile.TemporaryDirectory(prefix="dinowrite_")
        progress_file = Path(self._progress_dir.name) / "progress.txt"
        progress_file.unlink(missing_ok=True)
        source = self.temp_folder / (self.sequence.stem + ".png") if self.color_transform == "none" \
            and self.ocio_commands else self.sequence
        cmd = self.converter.encodeCommand(
            self.codec, progress_file,
            input=source.as_posix().replace(self.frame_padding, f"%0{self.padding}d"),
            exr_transfer="" if self.color_transform == "none" else self.color_transform,
            color_trc=self.colorTrc(),
            comment=self.colorDescription(),
            **self.encode_values)
        label = f"DinoWrite: encoding video ({self.codec})" if self.codec else "DinoWrite: encoding video"
        self._processes = process.Processes([cmd], label)

    def colorDescription(self) -> str:
        """Written into the video metadata (VLC: Tools -> Media Information -> Comments)"""
        if self.color_transform == "none" and self.ocio_commands:
            return f"DinoWrite: OCIO {self.display} / {self.view}"
        if self.color_transform == "none":
            return f"DinoWrite: as recorded (viewer display {self.viewer_display or 'unknown'})"
        return f"DinoWrite: {self.color_transform} transfer"

    def colorTrc(self) -> str:
        """Transfer tag of the encoded video, matching how its pixels were encoded"""
        if self.display and self.color_transform == "none" and self.ocio_commands:
            return ocio.displayTransfer(self.display)
        if self.color_transform == "none":
            return ocio.displayTransfer(self.viewer_display)
        return {"bt709": "bt709", "gamma22": "gamma22"}.get(self.color_transform, "iec61966-2-1")

    def _finish(self, stage: str, error: str = ""):
        self.stage, self.error = stage, error
        if self.temp_folder.exists():
            shutil.rmtree(self.temp_folder, ignore_errors=True)
        if self._progress_dir is not None:
            self._progress_dir.cleanup()
            self._progress_dir = None
        if stage == DONE:
            log.info("Video written: %s", self.video)
            if self.delete_input:
                for frame in sequenceFiles(self.sequence, self.frame_padding):
                    frame.unlink()
        else:
            self.video.unlink(missing_ok=True)  # partial video
            if stage == CANCELLED:
                log.warning("Video conversion cancelled, image sequence is kept")
            else:
                log.error("Video conversion failed: %s", error)
