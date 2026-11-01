from __future__ import annotations

import json
import random
import sys
from collections.abc import Iterable, Mapping
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
        characters_without_appearance = [
            character
            for character in self.characters
            if not any(prop.name == "kAppearance" for prop in character.properties)
        ]
        characters_with_appearance = [
            character
            for character in self.characters
            if any(prop.name == "kAppearance" for prop in character.properties)
        ]
        for character in characters_without_appearance + characters_with_appearance:
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


def _empty_character_appearance() -> list[Property]:
    return [
        Property("nmHead", "NameProperty", ""),
        Property("iGender", "IntProperty", 1),
        Property("iRace", "IntProperty", 0),
        Property("nmHaircut", "NameProperty", ""),
        Property("iHairColor", "IntProperty", 0),
        Property("iFacialHair", "IntProperty", 0),
        Property("nmBeard", "NameProperty", ""),
        Property("iSkinColor", "IntProperty", 0),
        Property("iEyeColor", "IntProperty", 0),
        Property("nmFlag", "NameProperty", ""),
        Property("iVoice", "IntProperty", 0),
        Property("iAttitude", "IntProperty", 0),
        Property("iArmorDeco", "IntProperty", 0),
        Property("iArmorTint", "IntProperty", 0),
        Property("iArmorTintSecondary", "IntProperty", 0),
        Property("iWeaponTint", "IntProperty", 0),
        Property("iTattooTint", "IntProperty", 0),
        Property("nmWeaponPattern", "NameProperty", ""),
        Property("nmPawn", "NameProperty", "None"),
        Property("nmTorso", "NameProperty", ""),
        Property("nmArms", "NameProperty", ""),
        Property("nmLegs", "NameProperty", ""),
        Property("nmHelmet", "NameProperty", ""),
        Property("nmEye", "NameProperty", "DefaultEyes"),
        Property("nmTeeth", "NameProperty", "DefaultTeeth"),
        Property("nmFacePropLower", "NameProperty", ""),
        Property("nmFacePropUpper", "NameProperty", ""),
        Property("nmPatterns", "NameProperty", ""),
        Property("nmVoice", "NameProperty", ""),
        Property("nmLanguage", "NameProperty", "None"),
        Property("nmTattoo_LeftArm", "NameProperty", ""),
        Property("nmTattoo_RightArm", "NameProperty", ""),
        Property("nmScars", "NameProperty", ""),
        Property("nmTorso_Underlay", "NameProperty", ""),
        Property("nmArms_Underlay", "NameProperty", ""),
        Property("nmLegs_Underlay", "NameProperty", ""),
        Property("nmFacePaint", "NameProperty", ""),
        Property("nmLeftArm", "NameProperty", ""),
        Property("nmRightArm", "NameProperty", ""),
        Property("nmLeftArmDeco", "NameProperty", ""),
        Property("nmRightArmDeco", "NameProperty", ""),
        Property("nmLeftForearm", "NameProperty", ""),
        Property("nmRightForearm", "NameProperty", ""),
        Property("nmThighs", "NameProperty", ""),
        Property("nmShins", "NameProperty", "None"),
        Property("nmTorsoDeco", "NameProperty", ""),
    ]


def _current_pool_timestamp() -> str:
    now = datetime.now()
    if sys.platform == "win32":
        return now.strftime("%B %#d, %Y - %#I:%M %p")
    return now.strftime("%B %-d, %Y - %-I:%M %p")


def _load_character_generation_rules() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parent
        / "data"
        / "Files"
        / "Templates"
        / "Character Generation Rules.json"
    )
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PoolFormatError(
            f"Could not read character generation rules: {exc}"
        ) from exc
    if not isinstance(rules, dict) or not isinstance(
        rules.get("character_template_names"), dict
    ):
        raise PoolFormatError("Character generation rules are invalid.")
    return rules


def _load_character_generation_data() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parent
        / "data"
        / "Files"
        / "Templates"
        / "Character Generation Data.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PoolFormatError(
            f"Could not read character generation data: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("Soldier"), dict):
        raise PoolFormatError("Character generation data is invalid.")
    return data


def _generate_character(
    generation_rules: dict[str, Any],
    generation_data: dict[str, Any],
    first_name: str,
    last_name: str,
    nickname: str,
    character_template_name: str | None = None,
    soldier_class_template_name: str | None = None,
    country: str | None = None,
    background_text: str | None = None,
) -> Character:
    template_name = character_template_name or generation_rules.get(
        "default_character_template_name"
    )
    template_rules = generation_rules["character_template_names"].get(template_name)
    if template_rules is None:
        allowed_names = ", ".join(generation_rules["character_template_names"])
        raise ValueError(
            f"Unsupported character_template_name {template_name!r}; "
            f"choose one of: {allowed_names}."
        )

    class_names = template_rules.get("soldier_classes", [])
    if not class_names:
        raise PoolFormatError(
            f"No soldier classes are configured for {template_name!r}."
        )
    if soldier_class_template_name is not None:
        if soldier_class_template_name not in class_names:
            allowed_classes = ", ".join(class_names)
            raise ValueError(
                f"Unsupported soldier_class_template_name "
                f"{soldier_class_template_name!r} for {template_name!r}; "
                f"choose one of: {allowed_classes}."
            )
        selected_class = soldier_class_template_name
    else:
        selected_class = random.choice(class_names)

    template_data = generation_data.get(template_name, {})
    soldier_data = generation_data["Soldier"]
    if template_rules.get("country_source") == "generation_data":
        country_names = template_data.get("countries", [])
    else:
        country_names = template_rules.get("countries", [])
    if not country_names:
        raise PoolFormatError(f"No countries are configured for {template_name!r}.")
    if country is not None:
        if country not in country_names:
            allowed_countries = ", ".join(country_names)
            raise ValueError(
                f"Unsupported country {country!r} for {template_name!r}; "
                f"choose one of: {allowed_countries}."
            )
        selected_country = country
    else:
        selected_country = random.choice(country_names)

    limits = generation_rules["field_limits"]
    first_name = first_name[: limits["strFirstName"]]
    last_name = last_name[: limits["strLastName"]]
    nickname = nickname[: limits["strNickName"]]
    if not background_text:
        backgrounds = template_data.get("background_texts") or soldier_data.get(
            "background_texts", []
        )
        if not backgrounds:
            raise PoolFormatError(
                f"No background text is configured for {template_name!r}."
            )
        background_text = random.choice(backgrounds)
    background_text = background_text[: limits["BackgroundText"]]
    return Character(
        [
            Property("strFirstName", "StrProperty", first_name),
            Property("strLastName", "StrProperty", last_name),
            Property(
                "strNickName",
                "StrProperty",
                f"'{nickname}'" if nickname else "",
            ),
            Property("m_SoldierClassTemplateName", "NameProperty", selected_class),
            Property("CharacterTemplateName", "NameProperty", template_name),
            Property("Country", "NameProperty", selected_country),
            Property(
                "AllowedTypeSoldier",
                "BoolProperty",
                generation_rules["allowed_type_soldier"],
            ),
            Property(
                "AllowedTypeVIP", "BoolProperty", template_rules["allowed_type_vip"]
            ),
            Property(
                "AllowedTypeDarkVIP",
                "BoolProperty",
                template_rules["allowed_type_dark_vip"],
            ),
            Property("PoolTimestamp", "StrProperty", _current_pool_timestamp()),
            Property("BackgroundText", "StrProperty", background_text),
        ]
    )


def generate_character(
    first_name: str,
    last_name: str,
    nickname: str = "",
    biography: str = "",
    *,
    character_template_name: str | None = None,
    soldier_class_template_name: str | None = None,
    country: str | None = None,
    background_text: str | None = None,
    existing_characters: Iterable[Character] = (),
) -> Character:
    """Generate a randomized soldier from bundled templates.

    Name values are used as supplied; callers are responsible for preparing them.
    ``biography`` (or ``background_text``) sets XCOM's ``BackgroundText``;
    when omitted, a background is selected from the extracted generation data.
    Appearance data is omitted so the game can generate it. The
    ``existing_characters`` argument is retained for compatibility.
    """
    generation_rules = _load_character_generation_rules()
    generation_data = _load_character_generation_data()
    return _generate_character(
        generation_rules,
        generation_data,
        first_name,
        last_name,
        nickname,
        character_template_name,
        soldier_class_template_name,
        country,
        background_text if background_text is not None else biography,
    )


def generate_characters(
    requests: Iterable[Mapping[str, str]],
    *,
    existing_characters: Iterable[Character] = (),
) -> list[Character]:
    """Generate soldiers for name requests using shared rules and data.

    Each request must contain ``first_name`` and ``last_name`` and may contain
    ``nickname``, ``character_template_name``, ``soldier_class_template_name``,
    ``country``, and ``background_text`` (or ``biography``). Appearance data is
    omitted so the game can generate it.
    """
    request_list = list(requests)
    if not request_list:
        return []
    generation_rules = _load_character_generation_rules()
    generation_data = _load_character_generation_data()
    return [
        _generate_character(
            generation_rules,
            generation_data,
            request["first_name"],
            request["last_name"],
            request.get("nickname", ""),
            request.get("character_template_name"),
            request.get("soldier_class_template_name"),
            request.get("country"),
            request.get("background_text", request.get("biography")),
        )
        for request in request_list
    ]


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
