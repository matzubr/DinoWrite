from types import SimpleNamespace

from DinoWrite.core import ocio


def test_display_command():
    cmd = ocio.displayCommand("hoiiotool", "/cfg/config.ocio", "/My Shots/a.#.exr", "/tmp/a.#.png",
                              (1001, 1100), 4, "sRGB - Display", "ACES 1.0 - SDR Video")
    assert cmd == ["hoiiotool", "--colorconfig", "/cfg/config.ocio",
                   "--frames", "1001-1100", "--framepadding", "4", "/My Shots/a.#.exr", "--ch", "R,G,B",
                   "--ociodisplay:from=scene_linear", "sRGB - Display", "ACES 1.0 - SDR Video",
                   "-d", "uint16", "-o", "/tmp/a.#.png"]


def test_display_command_without_config_and_input_space():
    cmd = ocio.displayCommand("oiiotool", "", "a.#.exr", "a.#.png", (1, 2), 4, "sRGB", "Standard", input_space="")
    assert "--colorconfig" not in cmd
    assert "--ociodisplay" in cmd


def test_find_oiiotool_prefers_houdini(tmp_path, monkeypatch, hou):
    tool = tmp_path / "bin" / "hoiiotool"
    tool.parent.mkdir()
    tool.touch()
    monkeypatch.setattr(hou, "getenv", lambda name, default=None: {"HFS": tmp_path.as_posix()}.get(name, default))
    assert ocio.findOiiotool() == tool.as_posix()


def _viewer(using_ocio=True, display="Rec.1886 Rec.709 - Display", view="ACES 1.0 - SDR Video"):
    return SimpleNamespace(usingOCIO=lambda: using_ocio, getOCIODisplay=lambda: display, getOCIOView=lambda: view)


VIEWS = {"sRGB - Display": ("ACES 1.0 - SDR Video", "Un-tone-mapped"),
         "Rec.1886 Rec.709 - Display": ("ACES 1.0 - SDR Video", "Raw")}


def _color_defaults(monkeypatch, hou, display="sRGB - Display", view="ACES 1.0 - SDR Video"):
    color = SimpleNamespace(ocio_defaultDisplay=lambda: display, ocio_defaultView=lambda: view,
                            ocio_views=lambda d: VIEWS.get(d, ("Only View",)))
    monkeypatch.setattr(hou, "Color", color, raising=False)


def test_default_source_is_mplay_config_defaults_not_viewer(monkeypatch, hou):
    """MPlay shows the flipbook with the config default display; the viewer may use Rec.1886"""
    _color_defaults(monkeypatch, hou)
    assert ocio.displayView(_viewer()) == ("sRGB - Display", "ACES 1.0 - SDR Video")


def test_viewer_source(monkeypatch, hou):
    _color_defaults(monkeypatch, hou)
    assert ocio.displayView(_viewer(), source="viewer") == ("Rec.1886 Rec.709 - Display", "ACES 1.0 - SDR Video")
    assert ocio.displayView(_viewer(using_ocio=False), source="viewer") == ("sRGB - Display", "ACES 1.0 - SDR Video")


def test_explicit_display_and_view(monkeypatch, hou):
    _color_defaults(monkeypatch, hou)
    assert ocio.displayView(_viewer(), view="Un-tone-mapped") == ("sRGB - Display", "Un-tone-mapped")
    # a display without a view gets the first view of that display, not a view of another display
    assert ocio.displayView(None, display="Other Display") == ("Other Display", "Only View")


def test_display_transfer_tag():
    assert ocio.displayTransfer("sRGB - Display") == "iec61966-2-1"
    assert ocio.displayTransfer("Rec.1886 Rec.709 - Display") == "bt709"
    assert ocio.displayTransfer("Gamma 2.2 Rec.709 - Display") == "bt709"
    assert ocio.displayTransfer("") == "iec61966-2-1"


def test_split_frames():
    assert ocio.splitFrames(1, 10, 3) == [(1, 4), (5, 7), (8, 10)]
    assert ocio.splitFrames(1001, 1001, 8) == [(1001, 1001)]
    assert ocio.splitFrames(1, 1151, 8)[-1] == (1009, 1151)  # 7 parts of 144 + 143


def test_process_count(monkeypatch):
    monkeypatch.setattr(ocio.os, "cpu_count", lambda: 32)
    assert ocio.processCount(0, 1000) == 8
    assert ocio.processCount(3, 1000) == 3
    assert ocio.processCount(0, 2) == 2


def test_display_commands_split_range_and_threads(monkeypatch):
    monkeypatch.setattr(ocio.os, "cpu_count", lambda: 16)
    cmds = ocio.displayCommands("hoiiotool", "", "a.#.exr", "a.#.png", (1, 100), 4, "sRGB", "View", processes=4)
    assert [c[c.index("--frames") + 1] for c in cmds] == ["1-25", "26-50", "51-75", "76-100"]
    assert all(c[1:3] == ["--threads", "4"] for c in cmds)


ACES_CG_SPACES = ["ACES2065-1", "ACEScc", "ACEScct", "ACEScg", "Linear P3-D65", "Linear Rec.2020",
                  "Linear Rec.709 (sRGB)", "sRGB - Texture", "Raw"]


def test_input_space_auto_finds_linear_rec709():
    assert ocio.inputSpace("auto", ACES_CG_SPACES) == "Linear Rec.709 (sRGB)"
    assert ocio.inputSpace("", ["ACEScg", "lin_srgb"]) == "lin_srgb"
    assert ocio.inputSpace("auto", ["Utility - Linear - sRGB", "ACES - ACEScg"]) == "Utility - Linear - sRGB"


def test_input_space_setting_wins_and_fallback():
    assert ocio.inputSpace("ACEScg", ACES_CG_SPACES) == "ACEScg"
    assert ocio.inputSpace("auto", ["ACEScg", "sRGB - Texture"]) == ocio.FALLBACK_INPUT_SPACE
