"""Audio storage helpers: extension checks, staged uploads, restart cleanup."""
import io

import pytest

from app.services import audio


class FakeUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = io.BytesIO(data)

    async def seek(self, offset: int) -> None:
        self.file.seek(offset)


def test_has_supported_ext():
    assert audio.has_supported_ext("a.mp3")
    assert audio.has_supported_ext("A.M4A")
    assert audio.has_supported_ext("clip.opus")
    assert audio.has_supported_ext("no-extension")
    assert not audio.has_supported_ext("notes.txt")
    assert not audio.has_supported_ext("video.mp4")


@pytest.mark.asyncio
async def test_stage_upload_streams_to_incoming(tmp_path):
    upload = FakeUpload("lesson.M4A", b"fake-audio")
    path = await audio.stage_upload(tmp_path, upload)
    assert path.parent == tmp_path / "incoming"
    assert path.suffix == ".m4a"
    assert path.read_bytes() == b"fake-audio"


def test_cleanup_incoming_removes_orphans(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "a.mp3").write_bytes(b"x")
    (incoming / "b.mp3").write_bytes(b"y")
    assert audio.cleanup_incoming(tmp_path) == 2
    assert list(incoming.iterdir()) == []
    # no directory is not an error
    assert audio.cleanup_incoming(tmp_path / "missing") == 0
