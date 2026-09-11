"""Compile [mopidy.query.SearchExpr][] trees to SQLite predicates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from mopidy.query import And, Compare, MatchAll, Not, SearchExpr

if TYPE_CHECKING:
    from mopidy.types import QueryValue

_SEARCH_FIELDS = (
    "uri",
    "track_name",
    "album",
    "artist",
    "composer",
    "performer",
    "albumartist",
    "genre",
    "track_no",
    "disc_no",
    "date",
    "comment",
    "musicbrainz_trackid",
    "musicbrainz_albumid",
    "musicbrainz_artistid",
)

_LIKE_ESCAPE = "\\"


def compile_search_sql(
    expr: SearchExpr, fields: Sequence[str] | None = None
) -> tuple[str, list[QueryValue]]:
    """Return SQL and params for matching tracks or distinct field values."""
    pred, params = _compile(expr)
    if fields is None:
        return (
            "SELECT * FROM tracks WHERE docid IN "
            f"(SELECT docid FROM search WHERE {pred})",
            params,
        )
    columns = ", ".join(f"search.{field}" for field in fields)
    return (
        f"SELECT DISTINCT {columns} FROM search JOIN tracks USING (docid) "
        f"WHERE search.{fields[0]} IS NOT NULL AND search.docid IN "
        f"(SELECT docid FROM search WHERE {pred})",
        params,
    )


def _compile(expr: SearchExpr) -> tuple[str, list[QueryValue]]:
    if isinstance(expr, MatchAll):
        return "1", []
    if isinstance(expr, Not):
        inner, params = _compile(expr.expr)
        return f"NOT ({inner})", params
    if isinstance(expr, And):
        compiled = [_compile(sub) for sub in expr.exprs]
        return (
            " AND ".join(f"({pred})" for pred, _ in compiled),
            [param for _, child_params in compiled for param in child_params],
        )
    if isinstance(expr, Compare):
        return _compile_compare(expr)
    msg = f"unknown expression node {expr!r}"
    raise TypeError(msg)


def _columns(field: str) -> tuple[str, ...]:
    if field == "any":
        return _SEARCH_FIELDS
    if field in _SEARCH_FIELDS:
        return (field,)
    msg = f"Invalid search field: {field}"
    raise LookupError(msg)


def _escape_like(value: str) -> str:
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


def _or_join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _compile_compare(expr: Compare) -> tuple[str, list[QueryValue]]:
    cols = _columns(expr.field)
    if expr.op in {"eq", "ne"}:
        parts = [f"({col} IS NOT NULL AND {col} = ?)" for col in cols]
        pred = _or_join(parts)
        return (f"NOT {pred}" if expr.op == "ne" else pred), [expr.value] * len(
            cols
        )
    if expr.op in {"contains", "starts_with"}:
        escaped = _escape_like(expr.value)
        pattern = "'%' || ? || '%'" if expr.op == "contains" else "? || '%'"
        parts = [
            (
                f"({col} IS NOT NULL AND {col} COLLATE NOCASE"
                f" LIKE {pattern} ESCAPE ?)"
            )
            for col in cols
        ]
        params: list[QueryValue] = [escaped, _LIKE_ESCAPE] * len(cols)
        return _or_join(parts), params
    msg = f"unknown operator {expr.op!r}"
    raise AssertionError(msg)
