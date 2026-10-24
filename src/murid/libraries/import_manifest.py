"""Strict validation of persisted audiobook import journals."""

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from .library import LibraryError


def relative_path(value: str) -> Path:
    """Resolve only canonical, safe relative paths from import state."""
    if not isinstance(value, str) or not value or "\0" in value:
        raise LibraryError("Import journal contains an unsafe relative path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or path.as_posix() != value:
        raise LibraryError("Import journal contains an unsafe relative path")
    if ".." in path.parts or "\\" in value or PureWindowsPath(value).drive:
        raise LibraryError("Import journal contains an unsafe relative path")
    return Path(*path.parts)


def _validate_relative_path(value: str) -> str:
    relative_path(value)
    return value


RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]


class ImportFile(BaseModel):
    """A source fingerprint; strict integers exclude booleans and numeric strings."""

    model_config = ConfigDict(strict=True)

    path: RelativePath
    size: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    audio: bool


class ImportManifest(BaseModel):
    """Validate stored state without requiring the original download to exist."""

    model_config = ConfigDict(strict=True)

    version: Annotated[int, Field(ge=1, le=1)]
    key: str
    library_id: str
    folder_id: str
    hardcover_id: str
    media_type: Literal["audiobook"]
    library_path: str
    destination: RelativePath
    files: Annotated[list[ImportFile], Field(min_length=1)]
    source_root: str
    metadata: dict
    phase: Literal["copying", "copied", "verified"]

    @field_validator("source_root")
    @classmethod
    def absolute_source(cls, value: str) -> str:
        """Validate placement without inspecting a potentially removed source."""
        if not Path(value).is_absolute():
            raise ValueError("source_root must be absolute")
        return value

    @field_validator("files")
    @classmethod
    def audio_inventory(cls, files: list[ImportFile]) -> list[ImportFile]:
        """Require audio and a distinct destination for every selected file."""
        if not any(entry.audio for entry in files):
            raise ValueError("no expected audio")
        if len({entry.path for entry in files}) != len(files):
            raise ValueError("duplicate file paths")
        return files
