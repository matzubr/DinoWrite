"""Scene audio for the video: the file set in Houdini's Audio panel (playbar sound), synced to the frames.

hou.audio has only setters, so the settings are read from the hscript 'audiopanel' command, which
prints them as flags: ... -m 1 -a 'file.wav' -f 1001 -O 0 ...
    -m 1     the source is an audio file (0: CHOPs, not supported)
    -a file  the audio file
    -f N     the frame the audio is synced to
    -O sec   offset of that frame from the start of the file
"""
import shlex
from dataclasses import dataclass
from pathlib import Path

import hou

from .log import log


@dataclass
class SceneAudio:
    path: str
    sync_frame: float = 1.0
    offset: float = 0.0  # seconds into the file at sync_frame

    def secondsAt(self, frame: float, fps: float) -> float:
        """Position in the audio file at the given frame"""
        return self.offset + (frame - self.sync_frame) / fps


def parseAudiopanel(text: str) -> dict:
    """Flags of 'audiopanel' output: {'-m': '1', '-a': 'file.wav', '-f': '1001', '-O': '0'}"""
    try:
        tokens = shlex.split(text or "")
    except ValueError:
        tokens = (text or "").split()
    values = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in ("-s", "-t", "-o", "-r") and index + 2 < len(tokens):
            values[f"{token} {tokens[index + 1]}"] = tokens[index + 2]  # sub options: -o d 1
            index += 3
        elif token in ("-m", "-a", "-f", "-O") and index + 1 < len(tokens):
            values[token] = tokens[index + 1]
            index += 2
        else:
            index += 1
    return values


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sceneAudio():
    """SceneAudio of the Audio panel, or None when no audio file is set (logged)"""
    try:
        output, _ = hou.hscript("audiopanel")
    except Exception as e:  # noqa: BLE001
        log.warning("Can't read the Audio panel: %s", e)
        return None
    values = parseAudiopanel(output)
    path = hou.text.expandString(values.get("-a", "")).strip()
    if values.get("-m", "1") != "1" or not path:
        log.info("No scene audio: the Audio panel has no audio file")
        return None
    if not Path(path).is_file():
        log.warning("Scene audio not found, video without sound: %s", path)
        return None
    return SceneAudio(path, _float(values.get("-f"), 1.0), _float(values.get("-O"), 0.0))


def inputArgs(audio: SceneAudio, start_frame: float, fps: float) -> list:
    """ffmpeg input of the audio file starting at the first video frame"""
    seconds = audio.secondsAt(start_frame, fps)
    if seconds >= 0:
        return ["-ss", f"{seconds:.6f}", "-i", audio.path]
    return ["-itsoffset", f"{-seconds:.6f}", "-i", audio.path]  # sound starts after the first frame


def outputArgs() -> list:
    """Video from the sequence, sound from the file; the video decides the length (silence pads the sound)"""
    return ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-shortest"]
