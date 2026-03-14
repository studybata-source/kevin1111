from bot.services.lyrics import _dominant_script, _score_candidate


def test_dominant_script_prefers_latin_for_transliterated_lines() -> None:
    assert _dominant_script("ni tu aundi ae te dil chill ho janda") == "latin"


def test_lyrics_scoring_penalizes_wrong_script_for_latin_query() -> None:
    latin_candidate = {
        "trackName": "Excuses",
        "artistName": "AP Dhillon",
        "plainLyrics": "Tu mere vall takkda hi nahi ni",
    }
    telugu_candidate = {
        "trackName": "Excuses",
        "artistName": "AP Dhillon",
        "plainLyrics": "నిన్ను చూస్తే నా హృదయం మోగుతుంటుంది",
    }

    latin_score = _score_candidate(latin_candidate, "Excuses", "AP Dhillon", "Excuses AP Dhillon")
    telugu_score = _score_candidate(telugu_candidate, "Excuses", "AP Dhillon", "Excuses AP Dhillon")

    assert latin_score > telugu_score
