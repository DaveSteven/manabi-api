from app.content import rich, subtitles


def test_cleaner_retains_japanese_semantics_and_removes_executable_content():
    value = rich('<p class="source" onclick="evil()"><ruby>漢<rt>かん</rt></ruby><u>字</u><script>alert(1)</script><img src=x onerror=evil()></p>')
    assert value['html'] == '<p><ruby>漢<rt>かん</rt></ruby><u>字</u></p>'
    assert value['text'] == '漢かん字'


def test_plain_angle_brackets_and_unbalanced_markup():
    assert rich('A < B & C')['text'] == 'A < B & C'
    assert rich('<p><u>文字')['html'] == '<p><u>文字</u></p>'


def test_subtitle_conversion_does_not_invent_invalid_times():
    segments, invalid = subtitles('<p data-starttime="00:00:01,50" data-endtime="00:00:02.000">声<u>です</u></p><p data-starttime="bad">不明</p>')
    assert segments == [{'start_ms':1500,'end_ms':2000,'text':'声です'}]
    assert invalid == 1
