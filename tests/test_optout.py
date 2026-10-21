from roastmygithub import optout


def test_opt_out_list_parses_logins_and_ignores_prose():
    text = "# Opt-out list\n\nSome words about how this works.\n\n# logins\nAlice\n@bob\n\n"
    assert optout.parse(text) == {"alice", "bob"}


def test_bundled_list_is_valid_and_empty_for_now():
    assert optout.parse(optout.DEFAULT_PATH.read_text()) == frozenset()
