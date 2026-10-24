from __future__ import annotations

import copy
import json
import random
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
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


def _current_pool_timestamp() -> str:
    now = datetime.now()
    if sys.platform == "win32":
        return now.strftime("%B %#d, %Y - %#I:%M %p")
    return now.strftime("%B %-d, %Y - %-I:%M %p")


def _find_character_property(properties: list[Property], name: str) -> Property | None:
    for prop in properties:
        if prop.name == name:
            return prop
        if prop.type_name == "StructProperty" and isinstance(prop.value, list):
            nested = _find_character_property(prop.value, name)
            if nested is not None:
                return nested
    return None


def _set_character_property(character: Character, name: str, value: Any) -> None:
    prop = _find_character_property(character.properties, name)
    if prop is None:
        raise PoolFormatError(f"Character template is missing property: {name}.")
    prop.value = value
    if prop.type_name == "BoolProperty" and prop.raw_body is not None:
        if len(prop.raw_body) == 1:
            prop.raw_body = b"\1" if value else b"\0"
        elif len(prop.raw_body) == 5:
            prop.raw_body = bytes(4) + (b"\1" if value else b"\0")
        else:
            prop.raw_body = None
    else:
        prop.raw_body = None
    prop.original_value = value if prop.raw_body is not None else None


def _load_character_templates() -> list[Character]:
    path = (
        Path(__file__).resolve().parent
        / "data"
        / "Files"
        / "Templates"
        / "New Character.txt"
    )
    templates = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(templates, list) or not templates:
        raise PoolFormatError("No character templates are available.")
    return [Character.from_dict(item) for item in templates]


def generate_character(
    first_name: str,
    last_name: str,
    nickname: str = "",
    biography: str = "",
    *,
    existing_characters: Iterable[Character] = (),
) -> Character:
    """Generate a randomized soldier from bundled templates.

    Name values are used as supplied; callers are responsible for preparing them.
    ``biography`` sets XCOM's ``BackgroundText`` property; when omitted, the
    selected template's biography is retained. ``existing_characters`` lets
    callers avoid reusing their appearances when an unused template is available.
    """
    templates = _load_character_templates()
    used_appearances = {
        appearance.to_bytes()
        for existing in existing_characters
        if (appearance := _find_character_property(existing.properties, "kAppearance"))
        is not None
    }
    available_templates = [
        template
        for template in templates
        if (appearance := _find_character_property(template.properties, "kAppearance"))
        is not None
        and appearance.to_bytes() not in used_appearances
    ]
    character = copy.deepcopy(random.choice(available_templates or templates))
    for name, value in (
        ("strFirstName", first_name),
        ("strLastName", last_name),
        ("strNickName", f"'{nickname}'" if nickname else ""),
        ("PoolTimestamp", _current_pool_timestamp()),
        ("CharacterTemplateName", "Soldier"),
        ("AllowedTypeSoldier", True),
        ("AllowedTypeVIP", True),
        ("AllowedTypeDarkVIP", True),
    ):
        _set_character_property(character, name, value)
    if biography:
        _set_character_property(character, "BackgroundText", biography)
    return character


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
