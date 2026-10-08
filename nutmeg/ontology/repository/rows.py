"""Row → dataclass mapping shared by the repositories."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import fields
from typing import Any, TypeVar

T = TypeVar('T')


def from_row(
    cls: type[T],
    row: Mapping[str, Any],
    json_fields: Iterable[str] = (),
    **convert: Callable[[Any], Any],
) -> T:
    """Build ``cls`` from one SQL result mapping.

    Each name in ``json_fields`` is read from its ``<name>_json`` column and decoded
    (NULL stays ``None``); ``convert`` maps a field to a callable (an enum, ``bool``,
    ``float``) applied to non-NULL values. Columns ``cls`` does not declare are ignored.
    """
    values = dict(row)
    for name in json_fields:
        raw = values.pop(f'{name}_json')
        values[name] = None if raw is None else json.loads(raw)
    for name, function in convert.items():
        if values[name] is not None:
            values[name] = function(values[name])
    declared = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in values.items() if key in declared})
