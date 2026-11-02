from __future__ import annotations

from openvelox.i18n import STRINGS, Translator


def test_en_zh_keys_match() -> None:
    assert set(STRINGS["en"]) == set(STRINGS["zh"])
    for key, text in STRINGS["en"].items():
        assert text, key
        assert STRINGS["zh"][key], key


def test_translator_switch() -> None:
    tr = Translator("en")
    assert "OpenVelox" in tr("app_title")
    tr.set_language("zh")
    assert "透射" in tr("app_title")
    assert "已从" in tr("status_opened", n=3, name="demo.emd")
