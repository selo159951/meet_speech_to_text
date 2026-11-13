import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import glossary, store  # noqa: E402
from backend.merge import Word  # noqa: E402

TERMS = ["Koray Ersu", "İvedik", "Teknopark"]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SESDEFTERI_HOME", str(tmp_path))


def W(text, prob=1.0, start=0.0, end=0.5):
    return Word(start, end, text, prob)


def texts(words):
    return [w.text for w in words]


# ---------------------------------------------------------------- fold
def test_fold_ivedik_variants_equal():
    assert glossary.fold("İvedik") == glossary.fold("Ivedik") == glossary.fold("ivedik") == "ivedik"


def test_fold_ignores_spaces_and_case():
    assert glossary.fold("Koray Ersu") == glossary.fold("korayersu") == "korayersu"


@pytest.mark.parametrize("src,dst", [("ç", "c"), ("ş", "s"), ("ğ", "g"), ("ö", "o"), ("ü", "u"), ("ı", "i"),
                                     ("Ç", "c"), ("Ş", "s"), ("Ğ", "g"), ("Ö", "o"), ("Ü", "u"), ("İ", "i")])
def test_fold_turkish_letters(src, dst):
    assert glossary.fold(src) == dst


def test_fold_drops_punctuation():
    assert glossary.fold("Ivedik,") == "ivedik"
    assert glossary.fold("") == ""


# ---------------------------------------------------------------- apply
def test_apply_fuzzy_respells_unsure_word():
    glossary.set_terms(TERMS)
    out, changes = glossary.apply([W(" Koriersu", 0.2)])
    assert texts(out) == [" Koray Ersu"]
    assert changes[0]["from"] == "Koriersu" and changes[0]["to"] == "Koray Ersu"


@pytest.mark.parametrize("prob", [0.0, 0.3, 0.7, 0.95, 1.0])
def test_apply_exact_folded_match_any_prob(prob):
    glossary.set_terms(TERMS)
    out, changes = glossary.apply([W(" Ivedik", prob)])
    assert texts(out) == [" İvedik"]
    assert changes == [{"from": "Ivedik", "to": "İvedik", "why": "spelling"}]


def test_apply_keeps_punctuation():
    glossary.set_terms(TERMS)
    out, _ = glossary.apply([W(" Ivedik,")])
    assert texts(out) == [" İvedik,"]
    out, _ = glossary.apply([W(' "ivedik".')])
    assert texts(out) == [' "İvedik".']


def test_apply_multiword_window_timing_and_prob():
    glossary.set_terms(TERMS)
    words = [Word(1.0, 1.4, " Koray", 0.3), Word(1.5, 2.2, " ersu", 0.3)]
    out, changes = glossary.apply(words)
    assert len(out) == 1
    assert (out[0].start, out[0].end) == (1.0, 2.2)
    assert out[0].text == " Koray Ersu"
    assert out[0].prob == 1.0
    assert changes == [{"from": "Koray ersu", "to": "Koray Ersu", "why": "spelling"}]


def test_apply_split_term_over_three_words():
    glossary.set_terms(["Teknopark"])
    out, _ = glossary.apply([W(" Tek", 0.5, 0, 1), W(" no", 0.5, 1, 2), W(" park", 0.5, 2, 3)])
    assert texts(out) == [" Teknopark"]
    assert (out[0].start, out[0].end) == (0, 3)


def test_apply_corrected_word_gets_full_prob_and_keeps_timing():
    glossary.set_terms(TERMS)
    out, _ = glossary.apply([Word(4.0, 4.6, " Ivedik", 0.1)])
    assert out[0].prob == 1.0 and (out[0].start, out[0].end) == (4.0, 4.6)


def test_apply_changes_have_from_to_why():
    glossary.set_terms(TERMS)
    _, changes = glossary.apply([W(" Koriersu", 0.2), W(" Ivedik")])
    assert len(changes) == 2
    for c in changes:
        assert set(c) == {"from", "to", "why"}
    assert changes[0]["why"] == "similar" and changes[1]["why"] == "spelling"


def test_apply_no_change_entry_when_only_punctuation_differs():
    glossary.set_terms(TERMS)
    words = [W(" İvedik,", 0.2), W(" Teknopark.", 0.2)]
    out, changes = glossary.apply(words)
    assert changes == []
    assert texts(out) == [" İvedik,", " Teknopark."]


def test_apply_surrounding_words_untouched():
    glossary.set_terms(TERMS)
    out, _ = glossary.apply([W(" Ben"), W(" Ivedik"), W(" gittim")])
    assert texts(out) == [" Ben", " İvedik", " gittim"]


# ---------------------------------------------------------------- safety
def test_sure_word_never_fuzzy_replaced():
    glossary.set_terms(["Selim"])
    out, changes = glossary.apply([W(" Selam", 0.95)])
    assert texts(out) == [" Selam"] and changes == []


def test_unsure_threshold_is_strict():
    glossary.set_terms(["Koray Ersu"])
    out, _ = glossary.apply([W(" Koriersu", 0.6)])  # not below FUZZY_MAX_PROB
    assert texts(out) == [" Koriersu"]


def test_fuzzy_window_does_not_swallow_sure_neighbour():
    glossary.set_terms(TERMS)
    out, _ = glossary.apply([W(" Koray", 0.3), W(" Ersu", 0.3), W(" at", 0.9)])
    assert texts(out) == [" Koray", " Ersu", " at"]  # already right: untouched, "at" kept
    out, _ = glossary.apply([W(" Kori", 0.3), W(" ersu", 0.3), W(" at", 0.9)])
    assert texts(out) == [" Koray Ersu", " at"]
    out, _ = glossary.apply([W(" Koriersu", 0.3), W(" at", 0.9)])
    assert texts(out) == [" Koray Ersu", " at"]


def test_not_glued_across_sentence_end():
    glossary.set_terms(["Volkan You"])
    out, changes = glossary.apply([W(" Volkan.", 0.3), W(" You", 0.3)])
    assert texts(out) == [" Volkan.", " You"] and changes == []


def test_term_not_matched_against_much_longer_window():
    glossary.set_terms(["Teknopark"])
    out, _ = glossary.apply([W(" Teknoparkimizdeki", 0.2)])
    assert texts(out) == [" Teknoparkimizdeki"]
    out, _ = glossary.apply([W(" Tek", 0.2), W(" noparkimizdeki", 0.2)])
    assert texts(out) == [" Tek", " noparkimizdeki"]


def test_short_words_never_fuzzy_matched():
    glossary.set_terms(["Alpi", "Mert"])
    out, changes = glossary.apply([W(" Alp", 0.1), W(" Met", 0.1)])
    assert texts(out) == [" Alp", " Met"] and changes == []


def test_nothing_configured_returns_words_unchanged():
    words = [W(" Koriersu", 0.1), W(" Ivedik", 0.1)]
    out, changes = glossary.apply(words)
    assert out == words and changes == []


# ---------------------------------------------------------------- learning
def test_learn_from_user_correction():
    learned = glossary.learn("I am Özge Koriersu at Technopark Ankara Ivedik Olsebe.",
                             "I am Özge Koray Ersu at Technopark Ankara İvedik OSB.")
    assert ("Koriersu", "Koray Ersu") in learned
    fixes = {f["wrong"]: f for f in glossary.get()["fixes"]}
    assert fixes["koriersu"]["right"] == "Koray Ersu"
    assert fixes["koriersu"]["count"] == 1 and fixes["koriersu"]["manual"] is False


def test_learn_ignores_lowercase_rewrite():
    assert glossary.learn("Gittik Ankara", "gittik ankara") == []
    assert glossary.learn("Bu Koriersu", "bu koray ersu") == []
    assert glossary.get()["fixes"] == []


def test_learn_ignores_sentence_start_capital():
    assert glossary.learn("koray ersu geldi", "Koray ersu geldi") == []
    assert glossary.get()["fixes"] == []


def test_learn_ignores_unrelated_rewrite_and_identical():
    assert glossary.learn("Bugün hava güzel", "Yarın Toplantı var") == []
    assert glossary.learn("aynı Metin", "aynı Metin") == []
    assert glossary.learn("", "Koray Ersu") == []


def test_fix_learned_once_only_where_model_unsure():
    glossary.add_fix("Koriersu", "Koray Ersu")
    out, changes = glossary.apply([W(" Koriersu", 0.5)])
    assert texts(out) == [" Koray Ersu"] and changes[0]["why"] == "fix"
    out, changes = glossary.apply([W(" Koriersu", 0.95)])
    assert texts(out) == [" Koriersu"] and changes == []


def test_fix_learned_twice_applies_at_high_prob():
    glossary.add_fix("Koriersu", "Koray Ersu")
    glossary.add_fix("Koriersu", "Koray Ersu")
    assert glossary.get()["fixes"][0]["count"] == 2
    out, changes = glossary.apply([W(" Koriersu", 0.95)])
    assert texts(out) == [" Koray Ersu"] and changes[0]["why"] == "fix"


def test_manual_fix_applies_at_high_prob():
    glossary.add_fix("Koriersu", "Koray Ersu", manual=True)
    out, _ = glossary.apply([W(" Koriersu", 0.95)])
    assert texts(out) == [" Koray Ersu"]


def test_manual_flag_is_sticky():
    glossary.add_fix("Koriersu", "Koray Ersu", manual=True)
    glossary.add_fix("Koriersu", "Koray Ersu")
    assert glossary.get()["fixes"][0]["manual"] is True


def test_remove_fix():
    glossary.add_fix("Koriersu", "Koray Ersu", manual=True)
    assert glossary.remove_fix("KORIERSU")["fixes"] == []
    out, _ = glossary.apply([W(" Koriersu", 0.95)])
    assert texts(out) == [" Koriersu"]
    glossary.remove_fix("nothing")  # unknown key is harmless


def test_get_lists_fixes_with_count_and_manual():
    glossary.add_fix("Koriersu", "Koray Ersu", manual=True)
    glossary.add_fix("Ivedik", "İvedik")
    fixes = {f["wrong"]: f for f in glossary.get()["fixes"]}
    assert fixes["koriersu"] == {"wrong": "koriersu", "right": "Koray Ersu", "count": 1, "manual": True}
    assert fixes["ivedik"] == {"wrong": "ivedik", "right": "İvedik", "count": 1, "manual": False}


def test_add_fix_ignores_empty_or_identical():
    glossary.add_fix("", "x")
    glossary.add_fix("abc", "")
    glossary.add_fix("same", "same")
    assert glossary.get()["fixes"] == []


# ---------------------------------------------------------------- terms
def test_set_terms_dedupes_by_fold_and_trims():
    g = glossary.set_terms(["  Koray   Ersu ", "korayersu", "İvedik", "Ivedik", "", "   ", "Teknopark"])
    assert g["terms"] == ["Koray Ersu", "İvedik", "Teknopark"]


def test_hotwords_none_when_empty_and_csv_otherwise():
    assert glossary.hotwords() is None
    glossary.set_terms(["Koray Ersu", "İvedik"])
    hw = glossary.hotwords()
    assert isinstance(hw, str)
    assert set(hw.split(", ")) == {"Koray Ersu", "İvedik"}


def test_all_terms_includes_fix_targets_and_people():
    from backend import people

    glossary.set_terms(["Teknopark"])
    glossary.add_fix("Koriersu", "Koray Ersu")
    people.create_person("Selim Oğuz")
    terms = glossary.all_terms()
    assert {"Teknopark", "Koray Ersu", "Selim Oğuz"} <= set(terms)
    assert len(terms) == len({glossary.fold(t) for t in terms})
    assert "Selim Oğuz" in glossary.hotwords()


def test_all_terms_dedupes_across_sources():
    glossary.set_terms(["Koray Ersu"])
    glossary.add_fix("Koriersu", "koray ersu")
    assert len(glossary.all_terms()) == 1


# ---------------------------------------------------------------- store integration
def _job_with(text):
    jid = store.create_job("m.wav")
    segs = [{"id": 0, "speaker": 0, "start": 0.0, "end": 2.0, "text_original": text, "text_edited": text,
             "words": []}]
    store.update_job(jid, status="done", segments=segs, speakers={"0": "Speaker 1"})
    return jid


def test_save_edits_learns_fix():
    jid = _job_with("Ben Koriersu dayım")
    store.save_edits(jid, edits={0: "Ben Koray Ersu dayım"})
    fixes = {f["wrong"]: f["right"] for f in glossary.get()["fixes"]}
    assert fixes == {"koriersu": "Koray Ersu"}
    assert store.read_transcript(jid)["segments"][0]["text_original"] == "Ben Koriersu dayım"


def test_save_edits_without_change_learns_nothing():
    jid = _job_with("Ben Koriersu dayım")
    store.save_edits(jid, edits={0: "Ben Koriersu dayım"})
    assert glossary.get()["fixes"] == []


# ---------------------------------------------------------------- bridge
def test_bridge_round_trip():
    from backend.bridge import Api

    api = Api()
    assert api.get_glossary() == {"terms": [], "fixes": []}
    g = api.set_glossary_terms(["Koray Ersu", " İvedik ", "korayersu"])
    assert g["terms"] == ["Koray Ersu", "İvedik"]
    g = api.add_glossary_fix("Koriersu", "Koray Ersu")
    assert g["fixes"] == [{"wrong": "koriersu", "right": "Koray Ersu", "count": 1, "manual": True}]
    assert api.get_glossary() == g
    g = api.remove_glossary_fix("koriersu")
    assert g["fixes"] == [] and g["terms"] == ["Koray Ersu", "İvedik"]
