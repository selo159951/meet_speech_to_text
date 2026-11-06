import pytest

from backend.engines import whispercpp as wc


def tok(text, a, b):
    return {"text": text, "offsets": {"from": a, "to": b}}


def test_words_from_json_merges_subword_tokens():
    data = {
        "result": {"language": "tr"},
        "transcription": [{
            "tokens": [
                tok("[_BEG_]", 0, 0),
                tok(" mer", 100, 300),
                tok("haba", 300, 600),
                tok(" dünya", 700, 1200),
                tok("[_TT_150]", 1200, 1200),
                tok("<|endoftext|>", 1200, 1200),
            ],
        }, {
            "tokens": [tok(" nasıl", 1500, 1900), tok("sın", 1900, 2100), tok("?", 2100, 2150)],
        }],
    }
    words, lang = wc.words_from_json(data)
    assert lang == "tr"
    assert [w.text for w in words] == [" merhaba", " dünya", " nasılsın?"]
    assert (words[0].start, words[0].end) == (0.1, 0.6)
    assert words[2].end == 2.15


def test_words_from_json_first_token_without_space_and_empty():
    words, lang = wc.words_from_json({"transcription": [{"tokens": [tok("Hi", 0, 200)]}]})
    assert [w.text for w in words] == [" Hi"] and lang == ""
    assert wc.words_from_json({}) == ([], "")


def test_parse_progress():
    assert wc.parse_progress("whisper_print_progress_callback: progress =  45%") == 45
    assert wc.parse_progress("whisper_print_progress_callback: progress = 100%") == 100
    assert wc.parse_progress("something else") is None


def test_parse_devices():
    out = ("ggml_vulkan: Found 2 Vulkan devices:\n"
           "ggml_vulkan: 0 = AMD Radeon RX 7800 XT (AMD proprietary driver) | uma: 0 | fp16: 1\n"
           "ggml_vulkan: 1 = Intel(R) Arc(TM) A380 Graphics (Intel) | uma: 0 | fp16: 1\n")
    devs = wc.parse_devices(out)
    assert [d["name"].split(" (")[0] for d in devs] == ["AMD Radeon RX 7800 XT", "Intel(R) Arc(TM) A380 Graphics"]
    assert devs[0]["index"] == 0
    assert wc.parse_devices("nothing here") == []


def test_model_file_name():
    assert wc.model_file_name("large-v3-turbo", 2.0) == "large-v3-turbo-q5_0"
    assert wc.model_file_name("large-v3-turbo", 8.0) == "large-v3-turbo"
    assert wc.model_file_name("medium", None) == "medium"
    assert wc.model_file_name("small-q5_0", 2.0) == "small-q5_0"


def test_available_without_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(wc, "binary_dir", lambda: tmp_path)
    ok, why = wc.available()
    assert not ok and "not found" in why


@pytest.mark.skipif(not wc.binary_path().is_file(), reason="vendor/whispercpp not built")
def test_binary_lists_devices():
    ok, why = wc.available()
    assert isinstance(ok, bool) and why


def test_collapsed_timestamps_are_spread():
    data = {"transcription": [{"tokens": [
        tok(" Let", 8280, 8280), tok(" us", 8280, 8280), tok(" start", 8280, 8280),
        tok(" the", 9000, 9300)]}]}
    words, _ = wc.words_from_json(data)
    assert [w.text for w in words] == [" Let", " us", " start", " the"]
    assert words[0].start == 8.28 and abs(words[2].end - 9.0) < 1e-9
    assert all(w.end > w.start for w in words)
    assert all(words[i].end <= words[i + 1].start + 1e-9 for i in range(3))


def test_best_device_prefers_discrete():
    out = ("ggml_vulkan: 0 = Intel(R) Arc(TM) Pro Graphics (Intel Corporation) | uma: 1 | fp16: 1\n"
           "ggml_vulkan: 1 = NVIDIA RTX 1000 Ada (NVIDIA) | uma: 0 | fp16: 1\n")
    devs = wc.parse_devices(out)
    assert devs[0]["integrated"] and not devs[1]["integrated"]
    assert wc.best_device(devs)["index"] == 1
    only_igpu = wc.parse_devices(out.splitlines()[0])
    assert wc.best_device(only_igpu)["index"] == 0
    assert wc.best_device([]) is None
