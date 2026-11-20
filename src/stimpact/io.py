"""Strict normalization of public Indego trip and station CSVs."""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

TRIP_COLUMNS = {
    "trip_id", "duration", "start_time", "end_time", "start_station", "start_lat", "start_lon",
    "end_station", "end_lat", "end_lon", "bike_id", "plan_duration", "trip_route_category",
    "passholder_type", "bike_type",
}
REQUIRED_TRIP_COLUMNS = TRIP_COLUMNS - {
    "bike_id", "plan_duration", "trip_route_category", "passholder_type", "bike_type",
}
ALIASES = {
    "start_station_id": "start_station", "end_station_id": "end_station",
    "started_at": "start_time", "ended_at": "end_time",
    "start_latitude": "start_lat", "start_longitude": "start_lon",
    "end_latitude": "end_lat", "end_longitude": "end_lon",
    "duration_minutes": "duration", "go_live_date": "official_open_date",
    "day_of_go_live_date": "official_open_date",
}
TIME_FORMATS = (
    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
)


def _read_csv(path: Path) -> pd.DataFrame:
    # DuckDB performs strict CSV ingestion; infer no types before schema validation.
    with duckdb.connect() as connection:
        return connection.read_csv(str(path), header=True, all_varchar=True,
                                   strict_mode=True).df().fillna("")


def _column_name(name: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", name.strip().lower().lstrip("\ufeff"))
    return ALIASES.get(normalized, normalized)


def _normalize_columns(frame: pd.DataFrame, allowed: set[str], required: set[str]) -> pd.DataFrame:
    columns = [_column_name(name) for name in frame.columns]
    unknown = set(columns) - allowed
    missing = required - set(columns)
    if unknown or missing or len(columns) != len(set(columns)):
        raise ValueError(f"Unrecognized schema: unknown={sorted(unknown)}, "
                         f"missing={sorted(missing)}, duplicates={len(columns) != len(set(columns))}")
    frame.columns = columns
    return frame


def _station_ids(values: pd.Series) -> pd.Series:
    cleaned = values.astype("string").str.strip()
    missing = cleaned.isna() | cleaned.str.lower().isin(["", "null", "nan", "na"])
    if (~missing & ~cleaned.str.fullmatch(r"\d+(?:\.0+)?", na=False)).any():
        raise ValueError("Station ID is not a nonnegative integer")
    return cleaned.mask(missing).str.replace(r"\.0+$", "", regex=True).str.lstrip("0").replace(
        "", "0")


def parse_times(values: pd.Series, formats: tuple[str, ...] = TIME_FORMATS) -> pd.Series:
    """Parse explicit local-time formats; unknown/missing dates are errors."""
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for date_format in formats:
        pending = result.isna()
        if not pending.any():
            break
        result.loc[pending] = pd.to_datetime(values.loc[pending], format=date_format,
                                             errors="coerce", exact=True)
    if result.isna().any():
        examples = values.loc[result.isna()].head(3).tolist()
        raise ValueError(f"Unknown or missing datetime format: {examples}")
    return result


def load_trips(path: str | Path, virtual_station_id: str = "3000", *,
               station_id_map: pd.DataFrame | None = None) -> pd.DataFrame:
    """Normalize one quarter; exclude missing/virtual endpoint IDs with audit counts.

    Durations in the public CSV are minutes and are also exposed as seconds.
    Timestamps remain naive Philadelphia local times, as documented by Indego.
    Short/round trips are retained here; panel cleaning is a later explicit step.
    """
    frame = _normalize_columns(_read_csv(Path(path)), TRIP_COLUMNS, REQUIRED_TRIP_COLUMNS)
    raw_rows = len(frame)
    for column in ("start_station", "end_station"):
        frame[column] = _station_ids(frame[column])
    missing = frame[["start_station", "end_station"]].isna().any(axis=1)
    virtual = ~missing & frame[["start_station", "end_station"]].eq(virtual_station_id).any(axis=1)
    frame = frame.loc[~missing & ~virtual].copy()
    for column in ("start_time", "end_time"):
        frame[column] = parse_times(frame[column])
    for column in ("duration", "start_lat", "start_lon", "end_lat", "end_lon"):
        values = frame[column].astype("string").str.strip()
        nulls = values.str.lower().isin(["", "null", "nan", "na"])
        numeric = pd.to_numeric(values.mask(nulls), errors="coerce")
        if (numeric.isna() & ~nulls).any():
            raise ValueError(f"Invalid numeric values in {column}")
        if column == "duration" and (numeric.isna().any() or (numeric < 0).any()):
            raise ValueError("Missing or negative trip duration")
        frame[column] = numeric.astype(float)
    frame["duration_seconds"] = frame["duration"] * 60
    frame.attrs["audit"] = {"raw_rows": raw_rows, "missing_station_rows": int(missing.sum()),
                            "virtual_station_rows": int(virtual.sum()), "retained_rows": len(frame)}
    if station_id_map is not None:
        from stimpact.identity import canonicalize_trips

        return canonicalize_trips(frame, station_id_map)
    return frame


def load_stations(path: str | Path, virtual_station_id: str = "3000") -> pd.DataFrame:
    columns = {"station_id", "station_name", "official_open_date", "status"}
    frame = _normalize_columns(_read_csv(Path(path)), columns, columns)
    frame = frame.loc[~frame.eq("").all(axis=1)].copy()
    frame["station_id"] = _station_ids(frame["station_id"])
    frame = frame.loc[frame["station_id"].ne(virtual_station_id)].copy()
    if frame["station_id"].isna().any() or frame["station_id"].duplicated().any():
        raise ValueError("Missing or duplicate station ID in station table")
    missing_dates = frame["official_open_date"].eq("")
    dates = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    dates.loc[~missing_dates] = parse_times(
        frame.loc[~missing_dates, "official_open_date"], ("%m/%d/%Y", "%Y-%m-%d"),
    )
    frame["official_open_date"] = dates
    return frame
