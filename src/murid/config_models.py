"""Typed validation for the YAML configuration, independent of file loading."""

import os
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlparse

from croniter import croniter
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

MediaType = Literal["ebook", "audiobook"]
NonEmptyString = Annotated[str, Field(min_length=1)]
PositiveSeconds = Annotated[int, Field(gt=0)]


def _list_slug(value: str) -> str:
    if not value or any(char.isspace() or char in "/?#" for char in value):
        raise ValueError("must be a non-empty list slug (the last part of the list URL)")
    return value


def _absolute_path(value: str) -> str:
    if not os.path.isabs(value):
        raise ValueError("must be an absolute path")
    return value


def _float_only(value: Any) -> Any:
    # Pydantic accepts integers for strict float fields; the YAML contract does not.
    if not isinstance(value, float):
        raise ValueError("must be a float")
    return value


ListSlug = Annotated[str, AfterValidator(_list_slug)]
AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]


class SettingsModel(BaseModel):
    """Reject coercion and keep credentials out of validation error rendering."""

    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class DefaultedSettings(SettingsModel):
    """Treat null fields as omitted and allow additional settings in this section."""

    model_config = ConfigDict(extra="allow", validate_default=True)

    @model_validator(mode="before")
    @classmethod
    def null_defaults(cls, value: Any) -> Any:
        """Treat null known fields as omitted, including required fields."""
        if isinstance(value, dict):
            return {
                key: item
                for key, item in value.items()
                # Pylint does not recognize Pydantic's class-level fields descriptor.
                if item is not None or key not in cls.model_fields  # pylint: disable=unsupported-membership-test
            }
        return value


class ReadingListSettings(SettingsModel):
    """Media requested from one Hardcover list."""

    type: MediaType | Annotated[list[MediaType], Field(min_length=1)] = "ebook"


class HardcoverSettings(SettingsModel):
    """One Hardcover account with explicitly selected reading lists."""

    api_key: Annotated[str, Field(pattern=r"^Bearer ")]
    reading_list: Annotated[dict[ListSlug, ReadingListSettings], Field(min_length=1)]


class PathMapping(DefaultedSettings):
    """Paired paths as seen by qBittorrent and Murid."""

    qbit_path: str | None = None
    murid_path: str | None = None

    @model_validator(mode="after")
    def paired_paths(self) -> Self:
        """Require both paths when mapping downloads and check the local path."""
        if bool(self.qbit_path) != bool(self.murid_path):
            raise ValueError("qbit_path and murid_path must be set together")
        if self.murid_path and not os.path.exists(self.murid_path):
            raise ValueError("murid_path does not exist")
        return self


class QbittorrentSettings(DefaultedSettings):
    """Connection settings plus passthrough options for qbittorrent-api."""

    host: str
    username: str
    password: str
    port: Annotated[int, Field(ge=1, le=65535)]
    verify_cert: bool = True
    category: str = "murid"
    mapping: PathMapping = Field(default_factory=PathMapping)

    @field_validator("host")
    @classmethod
    def trim_host(cls, value: str) -> str:
        """Keep the existing host spelling without trailing slashes."""
        return value.rstrip("/")


class CalibreSettings(DefaultedSettings):
    """Calibre backend settings; library is optional for audio-only requests."""

    calibredb_executable: str | None = "calibredb"
    library: NonEmptyString | None = None
    server_username: str | None = None
    server_password: str | None = None
    command_timeout_seconds: PositiveSeconds = 120

    @model_validator(mode="before")
    @classmethod
    def reject_old_library_options(cls, value: Any) -> Any:
        """Explain the replacement for retired Calibre library options."""
        if isinstance(value, dict) and value.keys() & {"library_path", "server_url"}:
            raise ValueError("library_path and server_url have been replaced by calibre.library")
        return value

    @field_validator("library")
    @classmethod
    def accessible_library(cls, value: str | None) -> str | None:
        """Accept a local library or an HTTP(S) content server."""
        if value is None:
            return value
        try:
            parsed = urlparse(value)
        except ValueError as error:
            raise ValueError("invalid Calibre server URL") from error
        if parsed.scheme in ("http", "https"):
            if not parsed.netloc:
                raise ValueError("Calibre server URL has no host")
        elif not os.path.exists(value):
            raise ValueError("Calibre database path does not exist")
        return value


class AudiobookshelfSettings(SettingsModel):
    """Audiobook access and import settings without contacting the server."""

    url: NonEmptyString
    api_key: NonEmptyString
    library_id: NonEmptyString
    library_path: AbsolutePath
    filetypes: Annotated[list[Literal["m4b", "mp3"]], Field(min_length=1)] = Field(
        default_factory=lambda: ["m4b", "mp3"]
    )
    staging_path: AbsolutePath | None = None
    folder_id: NonEmptyString | None = None
    scan_timeout_seconds: PositiveSeconds = 120

    @field_validator("url")
    @classmethod
    def server_url(cls, value: str) -> str:
        """Require HTTP(S) without embedded credentials, query, or fragment."""
        try:
            parsed = urlparse(value)
            valid = (
                parsed.scheme in ("http", "https")
                and bool(parsed.hostname)
                and not any((parsed.username, parsed.password, parsed.query, parsed.fragment))
            )
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("must be an HTTP(S) URL without credentials, query, or fragment")
        return value.rstrip("/")


class MuridSettings(DefaultedSettings):
    """Application settings and requirements shared across backends."""

    hardcover_accounts: Annotated[list[HardcoverSettings], Field(min_length=1)]
    mam_id: str
    redact_sensitive_data: bool = True
    matcher_threshold: Annotated[
        float, BeforeValidator(_float_only), Field(ge=0, le=1, allow_inf_nan=False)
    ] = 0.92
    lang_codes: Annotated[list[str], Field(min_length=1)] = Field(default_factory=lambda: ["ENG"])
    qbittorrent: QbittorrentSettings
    calibre: CalibreSettings = Field(default_factory=CalibreSettings)
    audiobookshelf: AudiobookshelfSettings | None = None
    schedule: str = "0 * * * *"
    # Apprise accepts its own configuration formats; leave validation to that library.
    apprise: Any = None
    filetypes: list[NonEmptyString] = Field(default_factory=lambda: ["epub", "mobi", "azw3", "azw"])
    exclude_vip: bool = False
    blacklisted_torrent_ids: list[int] = Field(default_factory=list)
    torrent_timeout_seconds: PositiveSeconds = 1800

    @field_validator("schedule")
    @classmethod
    def cron_schedule(cls, value: str) -> str:
        """Check the schedule with the same parser used at runtime."""
        try:
            croniter(value)
        except (ValueError, KeyError) as error:
            raise ValueError("must be a valid cron expression") from error
        return value

    @field_validator("calibre", "audiobookshelf")
    @classmethod
    def required_backend(cls, value: Any, info: ValidationInfo) -> Any:
        """Require the appropriate library for every requested medium."""
        media_types = set()
        for account in info.data.get("hardcover_accounts", []):
            for options in account.reading_list.values():
                media_types.update(
                    [options.type] if isinstance(options.type, str) else options.type
                )
        if info.field_name == "calibre" and "ebook" in media_types and value.library is None:
            raise ValueError("ebook requests require calibre.library")
        if info.field_name == "audiobookshelf" and "audiobook" in media_types and value is None:
            raise ValueError("Audiobook requests require audiobookshelf configuration")
        return value
