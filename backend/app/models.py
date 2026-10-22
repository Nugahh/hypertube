from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

SOURCE_ID_LENGTH = 2000  # a magnet link with its trackers; init_db widens the column of an existing database


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(5), default="en")
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Movie(Base):
    """A search result worth remembering: what the site shows, and where to get it (never sent to the browser)."""

    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(SOURCE_ID_LENGTH), unique=True)  # the provider's own id (Jackett's guid: a magnet link of 700 characters for some)
    title: Mapped[str] = mapped_column(String(300))
    year: Mapped[int | None]
    resolution: Mapped[str | None] = mapped_column(String(10))
    size: Mapped[int] = mapped_column(BigInteger)
    seeders: Mapped[int]
    peers: Mapped[int]
    provider: Mapped[str] = mapped_column(String(100))
    cover: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str] = mapped_column(Text)  # Jackett's download URL: it carries the API key, server side only
    # idle: nothing downloaded; downloading: the torrent runs; ready: the whole video is on disk
    status: Mapped[str] = mapped_column(String(12), default="idle")
    infohash: Mapped[str | None] = mapped_column(String(64))
    file_path: Mapped[str | None] = mapped_column(Text)  # relative to the download directory
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the download finished
    last_watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kept: Mapped[bool] = mapped_column(default=False)  # the member chose to download it: it ends in their library and is never cleaned up
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    info: Mapped["MovieInfo | None"] = relationship(lazy="joined", cascade="all, delete-orphan")


class MovieInfo(Base):
    """What TMDb knows about a movie, asked once. Every field is None when TMDb knows nothing about it."""

    __tablename__ = "movie_infos"

    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    tmdb_id: Mapped[int | None]
    kind: Mapped[str | None] = mapped_column(String(5))  # movie | tv
    overview: Mapped[str | None] = mapped_column(Text)
    runtime: Mapped[int | None]  # minutes
    rating: Mapped[float | None]
    year: Mapped[int | None]
    poster: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(8))  # original language of the video
    genres: Mapped[list | None] = mapped_column(JSON)
    directors: Mapped[list | None] = mapped_column(JSON)
    producers: Mapped[list | None] = mapped_column(JSON)
    cast: Mapped[list | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(lazy="joined")


class Watched(Base):
    """A member started watching a movie: the thumbnails show it."""

    __tablename__ = "watched"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CatalogTitle(Base):
    """A film or series TMDb lists, kept when the catalogue shows it: the database knows them without asking again."""

    __tablename__ = "catalog"

    kind: Mapped[str] = mapped_column(String(5), primary_key=True)  # movie | tv
    tmdb_id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    year: Mapped[int | None]
    overview: Mapped[str | None] = mapped_column(Text)
    poster: Mapped[str | None] = mapped_column(String(500))
    rating: Mapped[float | None]
    genres: Mapped[list | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CatalogBookmark(Base):
    """A catalogue title a member put in "my list" or in their favorites: a film is only a copy once a provider has it, TMDb's id is always there."""

    __tablename__ = "catalog_bookmarks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    media: Mapped[str] = mapped_column(String(5), primary_key=True)  # movie | tv
    tmdb_id: Mapped[int] = mapped_column(primary_key=True)
    shelf: Mapped[str] = mapped_column(String(8), primary_key=True)  # list | favorite
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Setting(Base):
    """One setting of the member (key, value as text)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class Progress(Base):
    """Where a member is in a movie: the player reports it every few seconds ("continue watching" shows a bar)."""

    __tablename__ = "progress"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[float] = mapped_column(Float)  # seconds
    duration: Mapped[float] = mapped_column(Float)  # seconds
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Bookmark(Base):
    """A film a member put in "my list" or in their favorites."""

    __tablename__ = "bookmarks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)  # list | favorite
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExtraSubtitle(Base):
    """A subtitle a member imported (a file, or one downloaded from OpenSubtitles), stored as WebVTT for everyone."""

    __tablename__ = "extra_subtitles"

    id: Mapped[int] = mapped_column(primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lang: Mapped[str] = mapped_column(String(2))
    label: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))  # upload | opensubtitles
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
