"""After recording: flipbook sequence -> video, kept EXR -> ACEScg / DWAA / passport. A pollable job.

Everything that needs hou (fps, viewer OCIO, tool lookup) is resolved in the constructor, on the main
thread. Then the job only polls external processes: the GUI calls step() from a QTimer, so Houdini
stays usable meanwhile.

Stages (each one optional):
    encode - ffmpeg from the recorded EXR, encoders tried one by one until one works.
             A viewport flipbook EXR is the viewport as seen, linearized with the inverse sRGB curve:
             encoded back with the sRGB curve it looks like MPlay right after recording. JPG/PNG as is.
             Scene audio (Audio panel file) and the flipbook passport go into the video.
    exr    - hoiiotool rewrites the kept EXR in place: ACEScg with a baked OCIO transform (see
             core/acescg.py), DWAA compression, the passport in the header. Several processes on parts
             of the frame range. Skipped when the sequence is deleted after the video.
             Kept PNG/JPG: the same pass into the OCIO role matte_paint (Nuke's default for 8-bit),
             only when that transform is possible.
"""
import os
import shutil
import tempfile
from pathlib import Path

import hou

from . import acescg, audio, ffmpeg, helpers, passport, process
from .log import log

PENDING, ENCODE, EXR, DONE, FAILED, CANCELLED = "pending", "encode", "exr", "done", "failed", "cancelled"
COLOR_TRC = "iec61966-2-1"  # sRGB
EXR_TEMP_FOLDER = "_dinowrite_tmp"


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
    """Video and/or ACEScg EXR from a written flipbook sequence.

    Args:
        sequence (Path): flipbook output path with frame token, like .../name.v001.$F4.exr
        frame_padding (str): frame token in the file name, like "$F4"
        convert_video (bool): encode the video
        scene_viewer (hou.SceneViewer, optional): the recorded viewer, its OCIO display/view is inverted
        camera (str): camera name for the passport
    """

    def __init__(self, settings: dict, sequence: Path, frame_padding: str, frame_range: tuple,
                 resolution: tuple, pixel_aspect: float, video_ext: str, convert_video: bool = True,
                 scene_viewer=None, camera: str = ""):
        advanced = settings["advanced"]
        self.sequence = Path(sequence)
        self.frame_padding = frame_padding
        self.padding = int(frame_padding.replace("$F", "") or 1)
        self.frame_range = (int(frame_range[0]), int(frame_range[1]))
        self.total_frames = self.frame_range[1] - self.frame_range[0] + 1
        self.convert_video = convert_video
        self.video = videoPath(self.sequence, frame_padding, video_ext) if convert_video else None
        self.delete_input = convert_video and bool(advanced.get("conversion_delete_input_sequence"))
        self.ext = self.sequence.suffix.lower().lstrip(".")
        is_exr = self.ext == "exr"
        is_ldr = self.ext in acescg.LDR_EXTS
        self.temp_folder = self.sequence.parent / EXR_TEMP_FOLDER
        fps = hou.fps()

        recolor = not self.delete_input and (
            (is_exr and advanced.get("exr_acescg", True)) or (is_ldr and advanced.get("ldr_matte_paint", True)))
        self._exr_dir = tempfile.TemporaryDirectory(prefix="dinowrite_exr_") if (is_exr or is_ldr) else None
        ctf = Path(self._exr_dir.name) / acescg.CTF_NAME if self._exr_dir else None
        display_view = acescg.plan(scene_viewer, ctf, self.ext) if recolor else None
        self.acescg = bool(display_view) and is_exr
        self.matte_paint = bool(display_view) and is_ldr
        self.target_colorspace = acescg.MATTE_PAINT if is_ldr else acescg.ACESCG_NAME
        if display_view:
            log.info("%s -> %s: inverse of '%s' / '%s'", self.ext.upper(), self.target_colorspace, *display_view)

        scene_audio = audio.sceneAudio() if convert_video and advanced.get("video_audio", True) else None
        self.passport = passport.collect(camera, self.frame_range, resolution,
                                         display_view or acescg.viewerDisplayView(scene_viewer),
                                         scene_audio.path if scene_audio else "")

        self.encode_values = dict(
            fps=helpers.ffmpegFps(hou.fps()),
            resolution=f"{resolution[0]}x{resolution[1]}",
            aspect=resolution[0] / resolution[1] * pixel_aspect,
            start_frame=self.frame_range[0],
            input=self.sequence.as_posix().replace(frame_padding, f"%0{self.padding}d"),
            output=self.video.as_posix() if self.video else "",
            srgb=is_exr,
            color_trc=COLOR_TRC,
            comment="DinoWrite: sRGB, like MPlay after recording",
            audio_input=audio.inputArgs(scene_audio, self.frame_range[0], fps) if scene_audio else (),
            audio=audio.outputArgs() if scene_audio else (),
            metadata=passport.ffmpegArgs(dict(self.passport, video_color="sRGB, like MPlay after recording"),
                                         title=self.video.stem if self.video else ""))
        if scene_audio:
            log.info("Video with scene audio: %s", scene_audio.path)
        self.converter = self.codecs = None
        if convert_video:
            self.converter = ffmpeg.FFmpeg(cmd=settings["ffmpeg_cmd"], binary=advanced.get("ffmpeg_path", ""),
                                           codec=advanced.get("video_codec", "auto"))
            self.codecs = self.converter.codecs() if self.converter.available else []

        # Kept EXR: ACEScg, compression, passport in one hoiiotool pass
        self.exr_commands = []
        self.compression = acescg.compressionArg(advanced.get("exr_compression", "dwaa"))
        rewrite = not self.delete_input and (is_exr or self.matte_paint)  # PNG/JPG only to change the colors
        tool = acescg.findOiiotool(advanced.get("oiiotool_path", "")) if rewrite else ""
        if rewrite and not tool:
            log.warning("%s kept as recorded: hoiiotool/oiiotool not found", self.ext.upper())
        if tool:
            pattern = self.sequence.name.replace(frame_padding, "#")
            self.exr_commands = acescg.commands(
                tool, (self.sequence.parent / pattern).as_posix(), (self.temp_folder / pattern).as_posix(),
                self.frame_range, self.padding, ctf.as_posix() if display_view else "",
                self.compression, passport.oiiotoolArgs(self.passport), self.target_colorspace)

        self.stage = PENDING
        self.error = ""
        self.codec = None
        self._processes = []
        self._progress_dir = None

    # ---------- state ----------

    @property
    def hasWork(self) -> bool:
        return self.convert_video or bool(self.exr_commands)

    @property
    def title(self) -> str:
        return self.video.name if self.video else self.sequence.name.replace(self.frame_padding, "####")

    @property
    def finished(self) -> bool:
        return self.stage in (DONE, FAILED, CANCELLED)

    @property
    def succeeded(self) -> bool:
        return self.stage == DONE

    def exrFramesDone(self) -> int:
        return len(list(self.temp_folder.iterdir())) if self.temp_folder.exists() else 0

    @property
    def progress(self) -> float:
        """Progress of the current stage 0..1"""
        if self.stage == ENCODE and self._progress_dir:
            value = ffmpeg.progressFromFile(Path(self._progress_dir.name) / "progress.txt", self.total_frames)
            return min(value or 0.0, 1.0)
        if self.stage == EXR:
            return min(self.exrFramesDone() / max(self.total_frames, 1), 1.0)
        return 1.0 if self.finished else 0.0

    @property
    def status(self) -> str:
        """Human readable current state"""
        if self.stage == ENCODE:
            return f"Encoding {self.codec or 'video'}: {self.progress * 100:.0f}%"
        if self.stage == EXR:
            return f"{self.exrLabel()}: {self.exrFramesDone()}/{self.total_frames} frames"
        if self.stage == DONE:
            return f"Done: {self.title}"
        if self.stage == CANCELLED:
            return "Cancelled, image sequence is kept"
        if self.stage == FAILED:
            return f"Failed: {self.error}"
        return "Starting..."

    # ---------- running ----------

    def start(self):
        if not self.convert_video:
            return self._startExr() if self.exr_commands else self._finish(DONE)
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
        result = self._poll()
        if result is None:
            return False

        if self.stage == ENCODE:
            if result:
                self._videoDone()
            elif self.codecs:
                log.warning("Encoder %s failed, trying %s", self.codec, self.codecs[0])
                self._startEncode()
            else:
                self.video.unlink(missing_ok=True)  # partial video
                self._finish(FAILED, f"ffmpeg failed: {result.tail(3) or result.error}")
        elif self.stage == EXR:
            if result:
                for frame in self.temp_folder.iterdir():
                    os.replace(frame, self.sequence.parent / frame.name)
                log.info("%s: %s", self.exrLabel(), self.sequence.parent)
                self._finish(DONE)
            else:
                self._finish(FAILED, f"{self.exrLabel()} failed, {self.ext.upper()} kept as recorded")
        return self.finished

    def cancel(self):
        if self.finished:
            return
        for proc in self._processes:
            proc.cancel()
        if self.stage == ENCODE:
            self.video.unlink(missing_ok=True)
        self._finish(CANCELLED)

    def _poll(self):
        """None while running, the first failure or the last success when all finished"""
        results = [proc.poll() for proc in self._processes]
        failed = [r for r in results if r is not None and not r]
        if failed:
            for proc, result in zip(self._processes, results):
                if result is None:
                    proc.cancel()  # one part failed: the rest is useless
            return failed[0]
        if any(r is None for r in results):
            return None
        return results[-1]

    def _startEncode(self):
        self.stage = ENCODE
        self.codec = self.codecs.pop(0)
        if self._progress_dir is None:
            self._progress_dir = tempfile.TemporaryDirectory(prefix="dinowrite_")
        progress_file = Path(self._progress_dir.name) / "progress.txt"
        progress_file.unlink(missing_ok=True)
        cmd = self.converter.encodeCommand(self.codec, progress_file, **self.encode_values)
        label = f"DinoWrite: encoding video ({self.codec})" if self.codec else "DinoWrite: encoding video"
        self._processes = [process.Process(cmd, label)]

    def _videoDone(self):
        log.info("Video written: %s", self.video)
        if self.delete_input:
            for frame in sequenceFiles(self.sequence, self.frame_padding):
                frame.unlink()
        if self.exr_commands:
            self._startExr()
        else:
            self._finish(DONE)

    def exrLabel(self) -> str:
        """EXR -> ACEScg, DWAA / PNG -> matte_paint"""
        if self.ext != "exr":
            return f"{self.ext.upper()} -> {acescg.MATTE_PAINT}"
        parts = (["ACEScg"] if self.acescg else []) + [self.compression.split(":")[0].upper()]
        return "EXR -> " + ", ".join(parts)

    def _startExr(self):
        self.stage = EXR
        shutil.rmtree(self.temp_folder, ignore_errors=True)
        self.temp_folder.mkdir(parents=True)
        self._processes = [process.Process(cmd, f"DinoWrite: {self.exrLabel()}") for cmd in self.exr_commands]

    def _finish(self, stage: str, error: str = ""):
        self.stage, self.error = stage, error
        shutil.rmtree(self.temp_folder, ignore_errors=True)
        for temp in (self._progress_dir, self._exr_dir):
            if temp is not None:
                temp.cleanup()
        self._progress_dir = self._exr_dir = None
        if stage == CANCELLED:
            log.warning("Cancelled, image sequence is kept as recorded")
        elif stage == FAILED:
            log.error("%s", error)
