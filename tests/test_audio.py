"""Scene audio: Audio panel parsing, sync to the first frame, real ffmpeg muxing"""
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
from DinoWrite import config
from DinoWrite.core import audio, conversion

AUDIOPANEL = ("audiopanel -s p './audio' -s g 'CHOP' -s r off -s s 0 -s l 0.3 -t p stop -t l off "
              "-o m off -o d 1 -o l 1 -r i 0 -m 1 -a '$HIP/audio/my music.wav' -f 1001 -O 2.5")


def test_parse_audiopanel():
    values = audio.parseAudiopanel(AUDIOPANEL)
    assert values["-a"] == "$HIP/audio/my music.wav"
    assert values["-f"] == "1001" and values["-O"] == "2.5" and values["-m"] == "1"
    assert values["-o d"] == "1" and values["-s l"] == "0.3"


def test_scene_audio_from_audiopanel(hou, monkeypatch, tmp_path):
    wav = tmp_path / "audio" / "my music.wav"
    wav.parent.mkdir()
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr(hou, "hscript", lambda cmd: (AUDIOPANEL, ""), raising=False)
    monkeypatch.setattr(hou, "text", SimpleNamespace(
        expandString=lambda text: text.replace("$HIP", tmp_path.as_posix())), raising=False)
    found = audio.sceneAudio()
    assert found.path == wav.as_posix() and found.sync_frame == 1001 and found.offset == 2.5

    monkeypatch.setattr(hou, "hscript", lambda cmd: (AUDIOPANEL.replace("-m 1", "-m 0"), ""), raising=False)
    assert audio.sceneAudio() is None, "CHOP audio isn't supported"
    monkeypatch.setattr(hou, "hscript", lambda cmd: (AUDIOPANEL.replace("my music", "missing"), ""), raising=False)
    assert audio.sceneAudio() is None


def test_sync_to_first_frame():
    sound = audio.SceneAudio("a.wav", sync_frame=1001, offset=2.5)
    assert audio.inputArgs(sound, 1001, 24) == ["-ss", "2.500000", "-i", "a.wav"]
    assert audio.inputArgs(sound, 1025, 24) == ["-ss", "3.500000", "-i", "a.wav"]
    late = audio.SceneAudio("a.wav", sync_frame=1049, offset=0)  # sound starts 2 s after the first frame
    assert audio.inputArgs(late, 1001, 24) == ["-itsoffset", "2.000000", "-i", "a.wav"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg in PATH")
def test_real_video_with_scene_audio(hou, monkeypatch, tmp_path):
    """1 s of sound for a 2 s video: the video keeps its length, the sound is padded with silence"""
    monkeypatch.setenv(config.USER_SETTINGS_ENV, (tmp_path / "user.json").as_posix())
    settings = config.load()
    settings["advanced"]["conversion_delete_input_sequence"] = False
    monkeypatch.setattr(hou, "fps", lambda: 24.0, raising=False)
    monkeypatch.setattr(hou, "getenv", lambda name, default=None: default)
    folder = tmp_path / "v001"
    folder.mkdir()
    run = {"check": True, "stdin": subprocess.DEVNULL, "timeout": 60, "capture_output": True}
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x32:r=24",
                    "-frames:v", "48", "-start_number", "1001", (folder / "shot.v001.%04d.png").as_posix()], **run)
    wav = tmp_path / "sound.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1", wav.as_posix()], **run)
    monkeypatch.setattr(audio, "sceneAudio", lambda: audio.SceneAudio(wav.as_posix(), 1001, 0))

    job = conversion.ConversionJob(settings, folder / "shot.v001.$F4.png", "$F4", (1001, 1048), (64, 32), 1.0,
                                   "mov")
    while not job.step():
        time.sleep(0.05)
    assert job.succeeded, job.error
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                            "-of", "csv=p=0", job.video.as_posix()], text=True, **run).stdout
    streams = dict(line.split(",") for line in probe.split())
    assert set(streams) == {"video", "audio"}
    assert abs(float(streams["audio"]) - 2.0) < 0.1 and abs(float(streams["video"]) - 2.0) < 0.1
