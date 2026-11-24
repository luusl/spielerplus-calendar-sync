from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def _env_int(env: dict[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def _env_bool(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


@dataclass(frozen=True)
class Settings:
    """Shared configuration, read from the environment / ``.env``.

    In single-job setups this is all the configuration there is. In
    multi-job setups (see :class:`JobConfig`) it also supplies the
    defaults any job doesn't override itself — e.g. most jobs share one
    SpielerPlus login and one Google OAuth client, differing only in
    which profile/calendar they target.
    """

    spielerplus_email: str
    spielerplus_password: str
    google_calendar_id: str
    google_credentials_path: Path
    google_token_path: Path
    spielerplus_user_id: str | None = None
    timezone: str = "Europe/Berlin"
    sync_tag: str = "spielerplus-sync"
    jobs_file: Path | None = None
    use_meeting_time: bool = False
    include_location: bool = False
    location_lookahead_days: int = 14

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = env if env is not None else os.environ
        try:
            spielerplus_email = env["SPIELERPLUS_EMAIL"]
            spielerplus_password = env["SPIELERPLUS_PASSWORD"]
        except KeyError as exc:
            raise ConfigError(f"missing required environment variable: {exc.args[0]}") from exc

        jobs_file = env.get("CALENDAR_SYNC_JOBS_FILE")

        return cls(
            spielerplus_email=spielerplus_email,
            spielerplus_password=spielerplus_password,
            spielerplus_user_id=env.get("SPIELERPLUS_USER_ID") or None,
            google_calendar_id=env.get("GOOGLE_CALENDAR_ID", "primary"),
            google_credentials_path=Path(env.get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")),
            google_token_path=Path(env.get("GOOGLE_TOKEN_PATH", "google_token.json")),
            timezone=env.get("CALENDAR_SYNC_TIMEZONE", "Europe/Berlin"),
            sync_tag=env.get("CALENDAR_SYNC_TAG", "spielerplus-sync"),
            jobs_file=Path(jobs_file) if jobs_file else None,
            use_meeting_time=_env_bool(env, "CALENDAR_SYNC_USE_MEETING_TIME"),
            include_location=_env_bool(env, "CALENDAR_SYNC_INCLUDE_LOCATION"),
            location_lookahead_days=_env_int(env, "CALENDAR_SYNC_LOCATION_LOOKAHEAD_DAYS", 14),
        )


@dataclass(frozen=True)
class JobConfig:
    """One sync target within a multi-job setup: a SpielerPlus profile
    paired with a Google Calendar.

    Every field but ``name`` is optional and falls back to the matching
    :class:`Settings` value when left unset — see :meth:`resolve`.
    """

    name: str
    spielerplus_user_id: str | None = None
    google_calendar_id: str | None = None
    google_token_path: Path | None = None
    sync_tag: str | None = None
    timezone: str | None = None
    title_prefix: str | None = None
    use_meeting_time: bool | None = None
    include_location: bool | None = None

    def resolve(self, settings: Settings) -> "ResolvedJob":
        calendar_id = self.google_calendar_id or settings.google_calendar_id
        if not calendar_id:
            raise ConfigError(f"job {self.name!r} has no google_calendar_id, and none is set as a default")

        return ResolvedJob(
            name=self.name,
            spielerplus_user_id=self.spielerplus_user_id or settings.spielerplus_user_id,
            google_calendar_id=calendar_id,
            google_token_path=self.google_token_path or settings.google_token_path,
            sync_tag=self.sync_tag or settings.sync_tag,
            timezone=self.timezone or settings.timezone,
            title_prefix=self.title_prefix,
            use_meeting_time=(
                settings.use_meeting_time if self.use_meeting_time is None else self.use_meeting_time
            ),
            include_location=(
                settings.include_location if self.include_location is None else self.include_location
            ),
        )


@dataclass(frozen=True)
class ResolvedJob:
    """A :class:`JobConfig` with all defaults from :class:`Settings` filled in."""

    name: str
    spielerplus_user_id: str | None
    google_calendar_id: str
    google_token_path: Path
    sync_tag: str
    timezone: str
    title_prefix: str | None = None
    use_meeting_time: bool = False
    include_location: bool = False


def load_jobs(path: str | Path) -> list[JobConfig]:
    """Parse a TOML file of ``[[job]]`` tables into :class:`JobConfig` objects.

    See ``jobs.example.toml`` for the expected format.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"could not read jobs file {path}: {exc}") from exc

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in jobs file {path}: {exc}") from exc

    raw_jobs = data.get("job", [])
    if not raw_jobs:
        raise ConfigError(f"jobs file {path} defines no [[job]] entries")

    jobs: list[JobConfig] = []
    seen_names: set[str] = set()
    for entry in raw_jobs:
        try:
            name = entry["name"]
        except KeyError as exc:
            raise ConfigError(f"job entry is missing the required 'name' field: {entry!r}") from exc
        if name in seen_names:
            raise ConfigError(f"duplicate job name {name!r} in {path}")
        seen_names.add(name)

        flags = {}
        for flag in ("use_meeting_time", "include_location"):
            value = entry.get(flag)
            if value is not None and not isinstance(value, bool):
                raise ConfigError(f"job {name!r}: {flag} must be true or false")
            flags[flag] = value

        token_path = entry.get("google_token_path")
        jobs.append(
            JobConfig(
                name=name,
                spielerplus_user_id=entry.get("spielerplus_user_id"),
                google_calendar_id=entry.get("google_calendar_id"),
                google_token_path=Path(token_path) if token_path else None,
                sync_tag=entry.get("sync_tag"),
                timezone=entry.get("timezone"),
                title_prefix=entry.get("title_prefix"),
                use_meeting_time=flags["use_meeting_time"],
                include_location=flags["include_location"],
            )
        )
    return jobs
