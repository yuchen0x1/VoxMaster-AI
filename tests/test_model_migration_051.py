"""Offline model migration regressions, including a stale pre-lock source."""

import hashlib
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

from vox import models_store as store


@pytest.fixture
def models(tmp_path, monkeypatch):
    payloads = {"vocals.onnx": b"tiny vocal model", "accompaniment.onnx": b"tiny backing model"}
    monkeypatch.setattr(store, "app_data", lambda: tmp_path / "config")
    monkeypatch.setattr(
        store, "FILES",
        {name: (len(body), hashlib.sha256(body).hexdigest()) for name, body in payloads.items()},
    )
    monkeypatch.setattr(store, "SIZE", sum(map(len, payloads.values())))

    def no_network(*args, **kwargs):
        pytest.fail("Migration must not download models")

    monkeypatch.setattr(store.urllib.request, "urlopen", no_network)
    store.save_settings(directory=str(tmp_path / "original"), mode="CPU")
    src = store.directory().resolve()
    src.mkdir(parents=True)
    for name, body in payloads.items():
        (src / name).write_bytes(body)
    (src / "keep.txt").write_bytes(b"unrelated source data")
    return src, payloads


def snapshot(*roots):
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
    }


def test_stale_migration_is_rejected_without_touching_any_location(models, tmp_path, monkeypatch):
    src, payloads = models
    base_a, base_b = tmp_path / "A", tmp_path / "B"
    dst_a, dst_b = (base_a / store.FOLDER).resolve(), (base_b / store.FOLDER).resolve()
    dst_a.mkdir(parents=True)
    (dst_a / "keep.txt").write_bytes(b"unrelated destination data")
    original_lock = store.locked
    original_directory = store.directory
    active_locks, reads = [], []
    after_b = None
    injected = False

    def read_directory():
        reads.append(tuple(active_locks))
        return original_directory()

    @contextmanager
    def interleaved_lock(root, name="model-manager"):
        nonlocal injected, after_b
        if Path(root) == src and name == "model-manager" and not injected:
            # A has read src but has not locked it. B completes before A resumes.
            injected = True
            store.migrate(base_b, Event())
            after_b = snapshot(src, dst_a, dst_b, store.app_data())
        with original_lock(root, name):
            active_locks.append(Path(root))
            try:
                yield
            finally:
                active_locks.pop()

    monkeypatch.setattr(store, "locked", interleaved_lock)
    monkeypatch.setattr(store, "directory", read_directory)
    with pytest.raises(RuntimeError, match="目录.*变更"):
        store.migrate(base_a, Event())

    assert (src, dst_a) in reads  # Revalidation must happen with BOTH locks held.
    assert store.directory().resolve() == dst_b
    assert snapshot(src, dst_a, dst_b, store.app_data()) == after_b
    assert all((dst_b / name).read_bytes() == body for name, body in payloads.items())
    assert not any((src / name).exists() for name in payloads)
    assert not active_locks
    # Rejection releases both real QLockFiles.
    with original_lock(src), original_lock(dst_a):
        pass


@pytest.mark.parametrize('operation', ['install', 'remove'])
def test_default_model_operation_rejects_directory_moved_before_lock(models, tmp_path, monkeypatch,
                                                                  operation):
    src, payloads = models
    destination = tmp_path / 'new active'
    original_lock = store.locked
    injected, after_move = False, None
    transfers = []

    def transfer(url, part, size, sha, cancel, progress):
        transfers.append(url)
        part.write_bytes(payloads[part.name.removesuffix('.part')])

    @contextmanager
    def interleaved_lock(root, name='model-manager'):
        nonlocal injected, after_move
        if Path(root) == src and name == 'model-manager' and not injected:
            injected = True
            store.migrate(destination, Event())
            after_move = snapshot(src, destination, store.app_data())
        with original_lock(root, name):
            yield

    monkeypatch.setattr(store, 'locked', interleaved_lock)
    monkeypatch.setattr(store, 'transfer', transfer)
    with pytest.raises(RuntimeError, match='目录.*变更'):
        if operation == 'install':
            store.install(Event(), lambda *_: None)
        else:
            store.remove()
    assert not transfers
    assert store.directory().resolve() == (destination / store.FOLDER).resolve()
    assert snapshot(src, destination, store.app_data()) == after_move
    store.verify()


def test_explicit_model_install_does_not_follow_active_directory(models, tmp_path, monkeypatch):
    src, payloads = models
    store.migrate(tmp_path / 'new active', Event())
    active = store.directory().resolve()
    before = snapshot(active, store.app_data())

    def transfer(url, part, size, sha, cancel, progress):
        part.write_bytes(payloads[part.name.removesuffix('.part')])

    monkeypatch.setattr(store, 'transfer', transfer)
    store.install(Event(), lambda *_: None, root=src)
    store.verify(src)
    assert store.directory().resolve() == active
    assert snapshot(active, store.app_data()) == before


@pytest.mark.parametrize("existing", [False, True])
def test_single_migration_preserves_settings_and_unrelated_files(models, tmp_path, existing):
    src, payloads = models
    dst = (tmp_path / "destination" / store.FOLDER).resolve()
    dst.mkdir(parents=True)
    (dst / "keep.txt").write_bytes(b"destination data")
    if existing:
        for name, body in payloads.items():
            (dst / name).write_bytes(body)

    store.migrate(dst.parent, Event())

    assert store.directory().resolve() == dst
    assert store.settings()["mode"] == "CPU"
    store.verify(dst)
    assert all(not (src / name).exists() for name in payloads)
    assert (src / "keep.txt").read_bytes() == b"unrelated source data"
    assert (dst / "keep.txt").read_bytes() == b"destination data"
    assert {path.name for path in dst.iterdir()} == {*payloads, "keep.txt"}


def test_current_directory_migration_is_noop_even_with_partial_download(models, monkeypatch):
    src, _ = models
    (src / "vocals.onnx.part").write_bytes(b"partial")
    before = snapshot(src, store.app_data())

    def unexpected_lock(*args, **kwargs):
        pytest.fail("Migrating to the active directory should be a no-op")

    monkeypatch.setattr(store, "locked", unexpected_lock)
    store.migrate(src.parent, Event())
    assert snapshot(src, store.app_data()) == before


def test_partial_download_rejects_migration_without_changing_files(models, tmp_path):
    src, _ = models
    (src / "vocals.onnx.part").write_bytes(b"partial")
    dst = tmp_path / "destination" / store.FOLDER
    dst.mkdir(parents=True)
    (dst / "keep.txt").write_bytes(b"destination data")
    before = snapshot(src, dst, store.app_data())

    with pytest.raises(ValueError, match="完成或取消下载"):
        store.migrate(dst.parent, Event())

    assert store.directory().resolve() == src
    assert snapshot(src, dst, store.app_data()) == before


@pytest.mark.parametrize("failure", ["copy", "verify", "settings", "cancel"])
def test_failed_migration_keeps_active_source_and_cleans_temporary_files(
    models, tmp_path, monkeypatch, failure
):
    src, payloads = models
    dst = tmp_path / "destination" / store.FOLDER
    dst.mkdir(parents=True)
    (dst / "keep.txt").write_bytes(b"destination data")
    before = snapshot(src, store.app_data())
    cancel = Event()
    if failure in ("copy", "verify"):
        def failed_copy(source, target):
            Path(target).write_bytes(b"interrupted copy")
            if failure == "copy":
                raise OSError("copy failed")

        monkeypatch.setattr(store.shutil, "copyfile", failed_copy)
    elif failure == "settings":
        def failed_save(**changes):
            raise OSError("settings failed")

        monkeypatch.setattr(store, "save_settings", failed_save)
    else:
        cancel.set()

    with pytest.raises((OSError, ValueError, InterruptedError)):
        store.migrate(dst.parent, cancel)

    assert store.directory().resolve() == src
    assert snapshot(src, store.app_data()) == before
    store.verify(src)
    assert (dst / "keep.txt").read_bytes() == b"destination data"
    # A failed config commit may leave verified copies, never missing source files.
    expected = {"keep.txt", *payloads} if failure == "settings" else {"keep.txt"}
    assert {path.name for path in dst.iterdir()} == expected


def test_destination_conflict_does_not_delete_active_models(models, tmp_path):
    src, _ = models
    dst = tmp_path / "destination" / store.FOLDER
    dst.mkdir(parents=True)
    (dst / "vocals.onnx").write_bytes(b"different destination model")
    before = snapshot(src, dst, store.app_data())

    with pytest.raises(ValueError, match="目标位置已有不同内容"):
        store.migrate(dst.parent, Event())

    assert store.directory().resolve() == src
    assert snapshot(src, dst, store.app_data()) == before
