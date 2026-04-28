import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import halt as halt_mod


def test_halt_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(halt_mod, "HALT_FILE", str(tmp_path / ".HALT"))
    assert not halt_mod.is_halted()
    halt_mod.halt("test")
    assert halt_mod.is_halted()
    assert halt_mod.reason() == "test"
    halt_mod.resume()
    assert not halt_mod.is_halted()


def test_halt_survives_corrupt_file(tmp_path, monkeypatch):
    p = tmp_path / ".HALT"
    p.write_text("not-json")
    monkeypatch.setattr(halt_mod, "HALT_FILE", str(p))
    assert halt_mod.is_halted()
    # Falls back to plain text; "not-json" is treated as the literal reason.
    assert halt_mod.reason() == "not-json"


def test_halt_resume_when_not_halted(tmp_path, monkeypatch):
    monkeypatch.setattr(halt_mod, "HALT_FILE", str(tmp_path / ".HALT"))
    res = halt_mod.resume()
    assert res["ok"] is True
    assert res["was_halted"] is False
