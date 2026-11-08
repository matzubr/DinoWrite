from types import SimpleNamespace

from DinoWrite.core import ocio


def test_display_command():
    cmd = ocio.displayCommand("hoiiotool", "/cfg/config.ocio", "/My Shots/a.#.exr", "/tmp/a.#.png",
                              (1001, 1100), 4, "sRGB - Display", "ACES 1.0 - SDR Video")
    assert cmd == ["hoiiotool", "--colorconfig", "/cfg/config.ocio",
                   "--frames", "1001-1100", "--framepadding", "4", "/My Shots/a.#.exr",
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


def _viewer(using_ocio=True, display="sRGB - Display", view="ACES 1.0 - SDR Video"):
    return SimpleNamespace(usingOCIO=lambda: using_ocio, getOCIODisplay=lambda: display, getOCIOView=lambda: view)


def _color_defaults(monkeypatch, hou, display="Default Display", view="Default View"):
    color = SimpleNamespace(ocio_defaultDisplay=lambda: display, ocio_defaultView=lambda: view)
    monkeypatch.setattr(hou, "Color", color, raising=False)


def test_display_view_from_viewer(monkeypatch, hou):
    _color_defaults(monkeypatch, hou)
    assert ocio.displayView(_viewer()) == ("sRGB - Display", "ACES 1.0 - SDR Video")


def test_display_view_settings_override_viewer(monkeypatch, hou):
    _color_defaults(monkeypatch, hou)
    assert ocio.displayView(_viewer(), view="Un-tone-mapped") == ("sRGB - Display", "Un-tone-mapped")


def test_display_view_falls_back_to_config_defaults(monkeypatch, hou):
    _color_defaults(monkeypatch, hou)
    assert ocio.displayView(_viewer(using_ocio=False)) == ("Default Display", "Default View")
