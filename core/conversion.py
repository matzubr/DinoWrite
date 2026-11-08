"""Flipbook sequence -> video conversion as a pollable job.

Everything that needs hou (fps, ffmpeg lookup) is resolved in the constructor, on the main thread.
Then the job only polls ffmpeg: the GUI calls step() from a QTimer, so Houdini stays usable while it
encodes. Encoders are tried one by one until one works.

Color: a viewport flipbook stores the viewport image as you see it (display transform already applied),
linearized with the inverse sRGB curve when written to EXR. MPlay shows it right after recording with
plain sRGB, so EXR is encoded back with the sRGB curve (like "EXR Transfer Func" of the FFmpeg Encode
Video TOP). JPG/PNG are already sRGB and are encoded as is.
"""
import tempfile
from pathlib import Path

import hou

from . import ffmpeg, helpers, process
from .log import log

PENDING, ENCODE, DONE, FAILED, CANCELLED = "pending", "encode", "done", "failed", "cancelled"
COLOR_TRC = "iec61966-2-1"  # sRGB


def sequenceFiles(sequence: Path, frame_padding: str) -> list:
    """Frames of this sequence only (not the video or other files in the folder)"""
    prefix, _, suffix = sequence.name.partition(frame_padding)
    if not sequence.parent.exists():
        return []
    return [f for f in sequence.parent.iterdir()
            if f.is_file() and f.name.startswith(prefix) and f.name.endswith(suffix)
            and f.name[len(prefix):len(f.name) - len(suffix)].isdigit()]


def videoPath(sequence: Path, frame_padding: str, video_ext: str) -> Path:
    """name.v001.$F4.exr -> name.v001.mov (works for name_$F4.exr too)"""
    return sequence.parent / (sequence.name.partition(frame_padding)[0].rstrip("._-") + f".{video_ext}")


class ConversionJob:
    """Convert a written flipbook sequence to video.

    Args:
        sequence (Path): flipbook output path with frame token, like .../name.v001.$F4.exr
        frame_padding (str): frame token in the file name, like "$F4"
    """

    def __init__(self, settings: dict, sequence: Path, frame_padding: str, frame_range: tuple,
                 resolution: tuple, pixel_aspect: float, video_ext: str):
        advanced = settings["advanced"]
        self.sequence = Path(sequence)
        self.frame_padding = frame_padding
        self.padding = int(frame_padding.replace("$F", "") or 1)
        self.frame_range = (int(frame_range[0]), int(frame_range[1]))
        self.total_frames = self.frame_range[1] - self.frame_range[0] + 1
        self.video = videoPath(self.sequence, frame_padding, video_ext)
        self.delete_input = bool(advanced.get("conversion_delete_input_sequence"))
        linear = self.sequence.suffix.lower() == ".exr"

        self.encode_values = dict(
            fps=helpers.ffmpegFps(hou.fps()),
            resolution=f"{resolution[0]}x{resolution[1]}",
            aspect=resolution[0] / resolution[1] * pixel_aspect,
            start_frame=self.frame_range[0],
            input=self.sequence.as_posix().replace(frame_padding, f"%0{self.padding}d"),
            output=self.video.as_posix(),
            srgb=linear,
            color_trc=COLOR_TRC,
            comment="DinoWrite: sRGB, like MPlay after recording")

        self.converter = ffmpeg.FFmpeg(cmd=settings["ffmpeg_cmd"], binary=advanced.get("ffmpeg_path", ""),
                                       codec=advanced.get("video_codec", "auto"))
        self.codecs = self.converter.codecs() if self.converter.available else []

        self.stage = PENDING
        self.error = ""
        self.codec = None
        self._process = None
        self._progress_dir = None

    # ---------- state ----------

    @property
    def finished(self) -> bool:
        return self.stage in (DONE, FAILED, CANCELLED)

    @property
    def succeeded(self) -> bool:
        return self.stage == DONE

    @property
    def progress(self) -> float:
        """0..1"""
        if self.stage == ENCODE and self._progress_dir:
            value = ffmpeg.progressFromFile(Path(self._progress_dir.name) / "progress.txt", self.total_frames)
            return min(value or 0.0, 1.0)
        return 1.0 if self.finished else 0.0

    @property
    def status(self) -> str:
        """Human readable current state"""
        if self.stage == ENCODE:
            return f"Encoding {self.codec or 'video'}: {self.progress * 100:.0f}%"
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
        self._startEncode()

    def step(self) -> bool:
        """Advance the job; returns True when it's finished"""
        if self.stage == PENDING:
            self.start()
        if self.finished:
            return True
        result = self._process.poll()
        if result is None:
            return False
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
        if self._process is not None:
            self._process.cancel()
        self._finish(CANCELLED)

    def _startEncode(self):
        self.stage = ENCODE
        self.codec = self.codecs.pop(0)
        if self._progress_dir is None:
            self._progress_dir = tempfile.TemporaryDirectory(prefix="dinowrite_")
        progress_file = Path(self._progress_dir.name) / "progress.txt"
        progress_file.unlink(missing_ok=True)
        cmd = self.converter.encodeCommand(self.codec, progress_file, **self.encode_values)
        label = f"DinoWrite: encoding video ({self.codec})" if self.codec else "DinoWrite: encoding video"
        self._process = process.Process(cmd, label)

    def _finish(self, stage: str, error: str = ""):
        self.stage, self.error = stage, error
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
