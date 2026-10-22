from datetime import datetime, timedelta, timezone

import pytest

from app import maintenance, models
from tests.fakes import FakeEngine

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
days = lambda n: NOW - timedelta(days=n)


@pytest.fixture
def lib(session_factory, tmp_path):
    engine = FakeEngine(tmp_path / "dl", {})
    session = session_factory()
    counter = iter(range(1, 100))

    def movie(file, status="ready", watched=None, ready=None, infohash=None, created=None):
        n = next(counter)
        row = models.Movie(
            source_id=f"id-{n}", title=file, size=1, seeders=1, peers=1, provider="p", link="l",
            status=status, infohash=infohash, file_path=f"pack-{n}/{file}", last_watched_at=watched,
            ready_at=ready, created_at=created or days(0),
        )
        session.add(row)
        session.commit()
        path = engine.download_dir / row.file_path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video")
        return row

    session.movie, session.engine = movie, engine
    yield session
    session.close()


def purge(lib):
    return maintenance.purge_unwatched(lib, lib.engine, NOW, max_age=timedelta(days=30))  # the age is a setting (3 days by default)


def test_a_movie_not_watched_for_a_month_is_erased_from_disk(lib):
    old = lib.movie("old.mp4", watched=days(31), ready=days(60))
    assert purge(lib) == 1
    assert not (lib.engine.download_dir / "pack-1").exists()
    lib.refresh(old)
    assert (old.status, old.infohash, old.file_path) == ("idle", None, None)


def test_a_movie_watched_recently_stays_even_if_downloaded_long_ago(lib):
    kept = lib.movie("kept.mp4", watched=days(5), ready=days(90))
    assert purge(lib) == 0
    assert (lib.engine.download_dir / kept.file_path).exists()


def test_a_downloaded_movie_nobody_ever_watched_counts_from_its_download_date(lib):
    lib.movie("never-old.mp4", watched=None, ready=days(40))
    lib.movie("never-new.mp4", watched=None, ready=days(2))
    assert purge(lib) == 1
    assert (lib.engine.download_dir / "pack-2" / "never-new.mp4").exists()


def test_a_stalled_download_nobody_touched_for_a_month_is_stopped_and_erased(lib):
    stuck = lib.movie("stuck.mp4", status="downloading", infohash="abc", created=days(45))
    assert purge(lib) == 1
    assert lib.engine.removed == ["abc"]
    lib.refresh(stuck)
    assert stuck.status == "idle"


def test_the_exact_limit_is_the_age_setting(lib):
    lib.movie("edge.mp4", watched=days(30) + timedelta(minutes=1), ready=days(60))
    assert purge(lib) == 0


def test_idle_movies_have_nothing_to_erase(lib):
    lib.add(models.Movie(source_id="x", title="x", size=1, seeders=1, peers=1, provider="p", link="l", status="idle", created_at=days(90)))
    lib.commit()
    assert purge(lib) == 0


def test_a_file_already_gone_does_not_stop_the_cleanup(lib):
    first = lib.movie("gone.mp4", watched=days(40), ready=days(60))
    lib.movie("old.mp4", watched=days(40), ready=days(60))
    (lib.engine.download_dir / first.file_path).unlink()
    assert purge(lib) == 2


def test_a_folder_shared_with_a_movie_that_stays_is_not_deleted(lib):
    old = lib.movie("old.mp4", watched=days(40), ready=days(60))
    kept = lib.movie("kept.mp4", watched=days(1), ready=days(60))
    shared = lib.engine.download_dir / "shared"
    shared.mkdir()
    for row, name in ((old, "old.mp4"), (kept, "kept.mp4")):
        (shared / name).write_bytes(b"video")
        row.file_path = f"shared/{name}"
    lib.commit()
    purge(lib)
    assert not (shared / "old.mp4").exists()
    assert (shared / "kept.mp4").exists()


def test_finished_downloads_are_noticed_even_if_nobody_asks(lib):
    row = lib.movie("done.mp4", status="downloading", infohash="hash-x")
    lib.engine.torrents["hash-x"] = type("T", (), {"is_complete": True})()
    maintenance.sync_downloads(lib, lib.engine, NOW)
    lib.refresh(row)
    assert row.status == "ready" and row.ready_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)
    assert lib.engine.removed == ["hash-x"]


def test_a_film_the_member_downloaded_is_never_cleaned_up(lib):
    mine = lib.movie("mine.mp4", watched=days(400), ready=days(400))
    mine.kept = True
    lib.commit()
    assert purge(lib) == 0
    assert (lib.engine.download_dir / mine.file_path).exists()


def test_a_cache_setting_of_zero_is_read_back(lib):
    from app import settings

    lib.movie("old.mp4", watched=days(100), ready=days(100))
    lib.add(models.Setting(key=settings.CACHE_DAYS, value="0"))
    lib.commit()
    assert settings.cache_days(lib) == 0
