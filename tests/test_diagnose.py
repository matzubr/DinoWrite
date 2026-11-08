from types import SimpleNamespace

from DinoWrite.core import diagnose

SPACES = ["ACES2065-1", "ACEScc", "ACEScg", "Linear P3-D65", "Linear Rec.709 (sRGB)", "sRGB - Texture", "Raw"]


def test_candidates():
    assert diagnose.candidates(SPACES) == [
        ("file metadata", ""),
        ("scene_linear role", "scene_linear"),
        ("Linear Rec.709 (sRGB)", "Linear Rec.709 (sRGB)"),
        ("ACEScg", "ACEScg"),
        ("ACES2065-1", "ACES2065-1"),
    ]


def test_check_command():
    from pathlib import Path

    cmd = diagnose.checkCommand("hoiiotool", "cfg.ocio", Path("/f/a.0001.exr"), Path("/f/out.png"),
                                "Rec.1886 Rec.709 - Display", "ACES 1.0 - SDR Video", "")
    assert "--ociodisplay" in cmd and not any(c.startswith("--ociodisplay:from") for c in cmd)
    cmd = diagnose.checkCommand("hoiiotool", "", Path("/f/a.0001.exr"), Path("/f/out.png"), "D", "V", "ACEScg")
    assert "--ociodisplay:from=ACEScg" in cmd and "--colorconfig" not in cmd


def test_diagnose_writes_one_png_per_candidate(tmp_path, monkeypatch):
    for frame in (2, 1):
        (tmp_path / f"fb.v001.{frame:04d}.exr").write_bytes(b"exr")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--info" in cmd:
            return SimpleNamespace(returncode=0, stdout="    oiio:ColorSpace: \"lin_rec709\"\n    compression: zip\n",
                                   stderr="")
        open(cmd[-1], "w").close()
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(diagnose.subprocess, "run", fake_run)
    monkeypatch.setattr(diagnose.ocio, "findOiiotool", lambda custom="": "hoiiotool")
    monkeypatch.setattr(diagnose.ocio, "configPath", lambda: "cfg.ocio")
    out = diagnose.diagnoseColors(tmp_path, display="D", view="V", spaces=SPACES, open_folder=False)

    assert calls[0][-1].endswith("fb.v001.0001.exr"), "first frame"
    assert sorted(p.name for p in out.glob("*.png")) == [
        "01_file_metadata.png", "02_scene_linear_role.png", "03_Linear_Rec.709_sRGB.png",
        "04_ACEScg.png", "05_ACES2065-1.png"]
    readme = (out / "README.txt").read_text()
    assert 'oiio:ColorSpace: "lin_rec709"' in readme and "compression" not in readme
