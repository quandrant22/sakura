"""upload_store: токен — только для файла внутри BROWSER_UPLOAD_DIR, одноразовый, с TTL."""
import base64
import os

import pytest

from desktop.core.upload_store import UploadError, UploadStore


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "uploads"
    (d / "docs").mkdir(parents=True)
    (d / "docs" / "cv.pdf").write_bytes(b"%PDF-1.4")
    (d / ".env").write_text("WS_TOKEN=x")
    (tmp_path / "outside.txt").write_text("secret")
    return d


def test_issue_and_take_once(folder):
    store = UploadStore(str(folder))
    token = store.issue("docs/cv.pdf")
    item = store.take(token)
    assert item == {"name": "cv.pdf", "mime": "application/pdf", "size": 8,
                    "data_b64": base64.b64encode(b"%PDF-1.4").decode()}
    with pytest.raises(UploadError, match="недействителен"):
        store.take(token)


def test_absolute_path_inside_folder_ok(folder):
    store = UploadStore(str(folder))
    assert store.take(store.issue(str(folder / "docs" / "cv.pdf")))["name"] == "cv.pdf"


@pytest.mark.parametrize("path", [
    "../outside.txt",
    "docs/../../outside.txt",
    "",
    ".",
])
def test_refuses_outside_or_empty(folder, path):
    with pytest.raises(UploadError):
        UploadStore(str(folder)).issue(path)


def test_refuses_absolute_outside(folder, tmp_path):
    with pytest.raises(UploadError, match="вне папки"):
        UploadStore(str(folder)).issue(str(tmp_path / "outside.txt"))


def test_refuses_symlink_escape(folder, tmp_path):
    link = folder / "link.txt"
    try:
        os.symlink(tmp_path / "outside.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("символические ссылки недоступны")
    with pytest.raises(UploadError, match="вне папки"):
        UploadStore(str(folder)).issue("link.txt")


def test_refuses_env_and_missing(folder):
    store = UploadStore(str(folder))
    with pytest.raises(UploadError, match="секреты"):
        store.issue(".env")
    with pytest.raises(UploadError, match="не найден"):
        store.issue("nope.txt")


def test_no_folder_configured(folder):
    with pytest.raises(UploadError, match="не задана"):
        UploadStore("").issue("docs/cv.pdf")
    with pytest.raises(UploadError, match="не задана"):
        UploadStore(str(folder / "missing")).issue("docs/cv.pdf")


def test_size_limit_and_ttl(folder):
    now = [0.0]
    store = UploadStore(str(folder), ttl=10, max_bytes=4, clock=lambda: now[0])
    with pytest.raises(UploadError, match="больше"):
        store.issue("docs/cv.pdf")
    store = UploadStore(str(folder), ttl=10, clock=lambda: now[0])
    token = store.issue("docs/cv.pdf")
    now[0] = 11
    with pytest.raises(UploadError, match="недействителен"):
        store.take(token)


def test_root_change_rechecks_issued_token(folder, tmp_path):
    store = UploadStore(str(folder))
    token = store.issue("docs/cv.pdf")
    other = tmp_path / "other"
    other.mkdir()
    store.set_root(str(other))
    with pytest.raises(UploadError, match="вне папки"):
        store.take(token)


def test_error_text_has_no_path(folder, tmp_path):
    try:
        UploadStore(str(folder)).issue(str(tmp_path / "outside.txt"))
    except UploadError as e:
        assert str(tmp_path) not in str(e)
