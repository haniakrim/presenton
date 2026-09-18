from api.v1.ppt.endpoints.skywork import SkyworkOutlineSlide, _outline_reference_text


def test_outline_reference_text_numbers_and_joins_slides():
    outline = [
        SkyworkOutlineSlide(content="Intro to the four-step process"),
        SkyworkOutlineSlide(content="Discover: understand goals"),
    ]
    text = _outline_reference_text(outline)
    assert "Follow this approved outline" in text
    assert "Slide 1: Intro to the four-step process" in text
    assert "Slide 2: Discover: understand goals" in text


def test_outline_reference_text_skips_blank_slides():
    outline = [
        SkyworkOutlineSlide(content="Real content"),
        SkyworkOutlineSlide(content="   "),
    ]
    text = _outline_reference_text(outline)
    assert "Slide 1: Real content" in text
    assert "Slide 2" not in text


def test_outline_reference_text_returns_empty_for_none_or_empty():
    assert _outline_reference_text(None) == ""
    assert _outline_reference_text([]) == ""
    assert _outline_reference_text([SkyworkOutlineSlide(content="  ")]) == ""
