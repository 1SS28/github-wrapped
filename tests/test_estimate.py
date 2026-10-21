from roastmygithub.estimate import voice_credits


def test_voice_is_a_tenth_of_a_credit_per_character_rounded_up_per_request():
    assert voice_credits(["a" * 101, "b" * 9, ""]) == 11 + 1
    assert voice_credits(["x" * 850]) == 85  # a 60 s script: the voice part of the bill
