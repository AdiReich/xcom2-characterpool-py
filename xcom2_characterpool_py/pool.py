from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .format import (
    PoolFormatError,
    Property,
    _read_i32,
    _write_i32,
    read_properties,
    write_properties,
)


@dataclass
class Character:
    properties: list[Property]

    def get(self, name: str, default: Any = None) -> Any:
        for prop in self.properties:
            if prop.name == name:
                return prop.value
        return default

    @property
    def full_name(self) -> str:
        parts = [
            self.get(key, "") for key in ("strFirstName", "strNickName", "strLastName")
        ]
        return " ".join(str(part).strip(" '") for part in parts if part)

    def to_dict(self) -> dict[str, Any]:
        return {"properties": [prop.to_dict() for prop in self.properties]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Character:
        properties = value.get("properties")
        if not isinstance(properties, list):
            raise PoolFormatError("Each character must contain a 'properties' list.")
        return cls([Property.from_dict(prop) for prop in properties])

    def to_bytes(self) -> bytes:
        return write_properties(self.properties)


@dataclass
class Pool:
    header_properties: list[Property] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)

    @property
    def file_name(self) -> str:
        return next(
            (
                str(prop.value)
                for prop in self.header_properties
                if prop.name == "PoolFileName"
            ),
            "",
        )

    @file_name.setter
    def file_name(self, value: str) -> None:
        for prop in self.header_properties:
            if prop.name == "PoolFileName":
                prop.value = value
                return
        self.header_properties.append(Property("PoolFileName", "StrProperty", value))

    def to_bytes(self) -> bytes:
        header: list[Property] = []
        count_written = False
        file_name_written = False
        for prop in self.header_properties:
            if prop.name == "CharacterPool":
                if not count_written:
                    header.append(
                        Property("CharacterPool", "ArrayProperty", len(self.characters))
                    )
                    count_written = True
            elif prop.name == "PoolFileName":
                if not file_name_written:
                    header.append(
                        Property(
                            "PoolFileName",
                            "StrProperty",
                            self.file_name or "Unsaved Pool",
                        )
                    )
                    file_name_written = True
            else:
                header.append(prop)
        if not count_written:
            header.insert(
                0, Property("CharacterPool", "ArrayProperty", len(self.characters))
            )
        if not file_name_written:
            header.append(
                Property(
                    "PoolFileName", "StrProperty", self.file_name or "Unsaved Pool"
                )
            )
        content = bytearray(b"\xff\xff\xff\xff")
        content.extend(write_properties(header))
        content.extend(_write_i32(len(self.characters)))
        for character in self.characters:
            content.extend(character.to_bytes())
        return bytes(content)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": "xcom2-characterpool-json-v1",
            "pool_file_name": self.file_name,
            "header_properties": [prop.to_dict() for prop in self.header_properties],
            "characters": [character.to_dict() for character in self.characters],
        }

    @classmethod
    def from_json(cls, document: dict[str, Any]) -> Pool:
        if document.get("format") != "xcom2-characterpool-json-v1":
            raise PoolFormatError(
                "Unrecognized JSON format. Expected xcom2-characterpool-json-v1."
            )
        header = document.get("header_properties", [])
        characters = document.get("characters")
        if not isinstance(header, list) or not isinstance(characters, list):
            raise PoolFormatError(
                "JSON must contain header_properties and characters lists."
            )
        pool = cls(
            [Property.from_dict(prop) for prop in header],
            [Character.from_dict(item) for item in characters],
        )
        if document.get("pool_file_name"):
            pool.file_name = str(document["pool_file_name"])
        return pool


def read_pool(path: str | Path | bytes) -> Pool:
    data = path if isinstance(path, bytes) else Path(path).read_bytes()
    if len(data) < 4 or data[:4] != b"\xff\xff\xff\xff":
        raise PoolFormatError(
            "Invalid character-pool header; expected four 0xFF bytes."
        )
    header, offset = read_properties(data, 4)
    expected_count, offset = _read_i32(data, offset)
    count_property = next(
        (prop for prop in header if prop.name == "CharacterPool"), None
    )
    actual_count = int(count_property.value) if count_property else 0
    if expected_count != actual_count:
        raise PoolFormatError(
            f"Character count mismatch in header: {actual_count} != {expected_count}."
        )
    characters = []
    for _ in range(expected_count):
        properties, offset = read_properties(data, offset)
        characters.append(Character(properties))
    if offset != len(data):
        raise PoolFormatError(f"Unexpected trailing data ({len(data) - offset} bytes).")
    return Pool(header, characters)


def write_pool(pool: Pool, path: str | Path) -> None:
    Path(path).write_bytes(pool.to_bytes())


def save_json(pool: Pool, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(pool.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json(path: str | Path) -> Pool:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PoolFormatError(f"Could not read JSON pool: {exc}") from exc
    if not isinstance(document, dict):
        raise PoolFormatError("Pool JSON must contain an object at the top level.")
    return Pool.from_json(document)
