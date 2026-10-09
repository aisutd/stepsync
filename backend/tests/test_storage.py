import pytest

from app.storage import safe_title, save_video
from app.video import VideoError


@pytest.mark.parametrize("title,expected", [
    ('Dance: "practice" / take\\2?*<>|', 'Dance_ _practice_ _ take_2_____'),
    ('  Dance... ', 'Dance'),
    ('..', 'YouTube video'),
    ('CON', '_CON'),
    ('nul.example', '_nul.example'),
    ('LPT1', '_LPT1'),
    ('../outside', '.._outside'),
    ('clip\x00\n', 'clip__'),
])
def test_windows_title(title, expected):
    assert safe_title(title) == expected


def test_long_title():
    assert len(safe_title('x' * 1000).encode('utf-16-le')) <= 300


def test_existing_file_untouched(tmp_path):
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'validated mp4')
    directory = tmp_path / 'Downloads'
    directory.mkdir()
    existing = directory / 'Dance.mp4'
    existing.write_bytes(b'original file')
    saved = save_video(source, 'Dance', directory)
    assert saved.name == 'Dance (1).mp4'
    assert existing.read_bytes() == b'original file'
    assert saved.read_bytes() == source.read_bytes()


def test_unwritable_destination(tmp_path):
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'mp4')
    blocked = tmp_path / 'Downloads'
    blocked.write_bytes(b'not a directory')
    with pytest.raises(VideoError) as caught:
        save_video(source, 'Dance', blocked)
    assert caught.value.code == 'save_failed'
    assert blocked.read_bytes() == b'not a directory'
