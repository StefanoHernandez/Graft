import pytest

from graft.ingestion.storage import delete_source, read_source, save_source

BOT = "11111111-1111-1111-1111-111111111111"
DOC = "22222222-2222-2222-2222-222222222222"
OTHER_DOC = "33333333-3333-3333-3333-333333333333"


def test_save_then_read_round_trip(tmp_path):
    key = save_source(tmp_path, BOT, DOC, b"hello \xc3\xa8")
    assert read_source(tmp_path, key) == b"hello \xc3\xa8"


def test_key_is_derived_from_ids_only(tmp_path):
    key = save_source(tmp_path, BOT, DOC, b"x")
    assert key == f"{BOT}/{DOC}/source"
    assert (tmp_path / key).is_file()


def test_same_filename_twice_never_collides(tmp_path):
    # The caller's filename is metadata; two documents can share it safely.
    first = save_source(tmp_path, BOT, DOC, b"one")
    second = save_source(tmp_path, BOT, OTHER_DOC, b"two")
    assert first != second
    assert read_source(tmp_path, first) == b"one"
    assert read_source(tmp_path, second) == b"two"


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    save_source(tmp_path, BOT, DOC, b"payload")
    files = sorted(p.name for p in (tmp_path / BOT / DOC).iterdir())
    assert files == ["source"]


def test_overwrite_replaces_content(tmp_path):
    save_source(tmp_path, BOT, DOC, b"first")
    key = save_source(tmp_path, BOT, DOC, b"second")
    assert read_source(tmp_path, key) == b"second"


@pytest.mark.parametrize(
    "key",
    [
        "../escape",
        f"{BOT}/../../escape",
        "/etc/passwd",
        f"{BOT}/{DOC}/../../../etc/passwd",
    ],
)
def test_read_refuses_keys_escaping_the_root(tmp_path, key):
    # A storage_key read back from the DB is still untrusted input.
    (tmp_path.parent / "escape").write_bytes(b"secret")
    with pytest.raises(ValueError):
        read_source(tmp_path, key)


def test_delete_refuses_keys_escaping_the_root(tmp_path):
    outside = tmp_path.parent / "escape"
    outside.write_bytes(b"secret")
    with pytest.raises(ValueError):
        delete_source(tmp_path, "../escape")
    assert outside.exists()


def test_read_missing_key_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_source(tmp_path, f"{BOT}/{DOC}/source")


def test_delete_removes_the_document_directory(tmp_path):
    key = save_source(tmp_path, BOT, DOC, b"x")
    delete_source(tmp_path, key)
    assert not (tmp_path / BOT / DOC).exists()


def test_delete_is_idempotent(tmp_path):
    key = save_source(tmp_path, BOT, DOC, b"x")
    delete_source(tmp_path, key)
    delete_source(tmp_path, key)  # a failed cleanup must be safe to retry
