from __future__ import annotations

import json
import random
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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

_MAX_POOL_INPUT_BYTES = 64 * 1024 * 1024
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _load_strict_rules() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parent
        / "data"
        / "Files"
        / "Templates"
        / "Character Pool Strict Rules.json"
    )
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PoolFormatError(f"Could not read strict validation rules: {exc}") from exc

    if not isinstance(rules, dict):
        raise PoolFormatError("Strict validation rules are invalid.")

    property_types = rules.get("property_types")
    contexts = rules.get("property_contexts")
    child_contexts = rules.get("struct_child_contexts")
    struct_tags = rules.get("struct_tags")
    struct_layouts = rules.get("struct_layouts")
    valid_property_types = {
        "ArrayProperty",
        "BoolProperty",
        "IntProperty",
        "NameProperty",
        "StrProperty",
        "StructProperty",
    }
    if not isinstance(property_types, dict) or not all(
        isinstance(name, str)
        and isinstance(type_name, str)
        and type_name in valid_property_types
        for name, type_name in property_types.items()
    ):
        raise PoolFormatError("Strict validation rules are invalid.")

    if not isinstance(contexts, dict) or not all(
        isinstance(context, str)
        and isinstance(names, list)
        and all(isinstance(name, str) for name in names)
        for context, names in contexts.items()
    ):
        raise PoolFormatError("Strict validation rules are invalid.")

    if not {"header", "character", "appearance"}.issubset(contexts):
        raise PoolFormatError("Strict validation rules are invalid.")

    if (
        any(name not in property_types for names in contexts.values() for name in names)
        or not isinstance(child_contexts, dict)
        or not all(
            isinstance(name, str)
            and property_types.get(name) == "StructProperty"
            and isinstance(context, str)
            and context in contexts
            for name, context in child_contexts.items()
        )
    ):
        raise PoolFormatError("Strict validation rules are invalid.")

    if (
        not isinstance(struct_tags, dict)
        or not all(
            isinstance(name, str)
            and property_types.get(name) == "StructProperty"
            and isinstance(tag, str)
            for name, tag in struct_tags.items()
        )
        or not isinstance(struct_layouts, dict)
        or not all(
            isinstance(name, str)
            and property_types.get(name) == "StructProperty"
            and isinstance(layouts, list)
            and bool(layouts)
            and all(isinstance(layout, str) for layout in layouts)
            for name, layouts in struct_layouts.items()
        )
    ):
        raise PoolFormatError("Strict validation rules are invalid.")

    string_field_lists = (
        "relaxed_string_fields",
        "string_exemptions",
        "string_length_exemptions",
    )
    if not all(
        isinstance(rules.get(field_name), list)
        and all(
            isinstance(name, str) and name in property_types
            for name in rules[field_name]
        )
        for field_name in string_field_lists
    ):
        raise PoolFormatError("Strict validation rules are invalid.")

    nonnegative_integer_fields = (
        "max_string_length",
        "max_background_text_length",
        "max_pool_file_name_length",
        "max_struct_levels",
    )
    if (
        not all(
            _is_nonnegative_int(rules.get(field_name))
            for field_name in nonnegative_integer_fields
        )
        or not isinstance(rules.get("min_int_property_value"), int)
        or isinstance(rules.get("min_int_property_value"), bool)
        or not isinstance(rules.get("max_int_property_value"), int)
        or isinstance(rules.get("max_int_property_value"), bool)
        or rules["min_int_property_value"] > rules["max_int_property_value"]
        or not isinstance(rules.get("string_pattern"), str)
        or not isinstance(rules.get("pool_file_name_pattern"), str)
    ):
        raise PoolFormatError("Strict validation rules are invalid.")
    try:
        rules["_compiled_string_pattern"] = re.compile(
            f"(?:{rules['string_pattern']})\\Z"
        )
        rules["_compiled_pool_file_name_pattern"] = re.compile(
            f"(?:{rules['pool_file_name_pattern']})\\Z"
        )
    except re.error as exc:
        raise PoolFormatError("Strict validation string pattern is invalid.") from exc
    return rules


def _read_pool_file(path: str | Path) -> bytes:
    with Path(path).open("rb") as source:
        data = source.read(_MAX_POOL_INPUT_BYTES + 1)
    if len(data) > _MAX_POOL_INPUT_BYTES:
        raise PoolFormatError("Pool input exceeds the 64 MiB size limit.")
    return data


def _validate_properties(
    properties: list[Property],
    location: str,
    context: str,
    rules: dict[str, Any],
    struct_levels: int = 0,
) -> None:
    allowed_names = rules["property_contexts"].get(context, [])
    for prop in properties:
        if not isinstance(prop, Property) or not isinstance(prop.name, str):
            raise PoolFormatError(f"Invalid property at {location}.")
        if prop.name not in allowed_names:
            raise PoolFormatError(f"Unknown property {prop.name!r} at {location}.")
        expected_type = rules["property_types"].get(prop.name)
        if expected_type is None:
            raise PoolFormatError(f"Unknown property {prop.name!r} at {location}.")
        if prop.type_name != expected_type:
            raise PoolFormatError(
                f"Property {prop.name!r} at {location} must be {expected_type}, "
                f"not {prop.type_name!r}."
            )

        if prop.type_name == "StructProperty":
            next_levels = struct_levels + 1
            if next_levels > rules["max_struct_levels"]:
                raise PoolFormatError(
                    f"Struct nesting at {location}.{prop.name} exceeds the strict "
                    f"limit of {rules['max_struct_levels']} levels."
                )
            if not isinstance(prop.value, list):
                raise PoolFormatError(
                    f"Struct property {prop.name!r} at {location} must contain a list."
                )
            child_context = rules["struct_child_contexts"].get(prop.name)
            if child_context is None:
                raise PoolFormatError(
                    f"Struct property {prop.name!r} has no strict child context."
                )
            expected_tag = rules["struct_tags"].get(prop.name)
            if expected_tag is not None and prop.struct_tag != expected_tag:
                raise PoolFormatError(
                    f"Struct property {prop.name!r} at {location} must use tag "
                    f"{expected_tag!r}."
                )
            expected_layout = rules["struct_layouts"].get(prop.name)
            if (
                expected_layout is not None
                and prop.struct_layout not in expected_layout
            ):
                raise PoolFormatError(
                    f"Struct property {prop.name!r} at {location} must use layout "
                    f"one of {expected_layout!r}."
                )
            _validate_properties(
                prop.value,
                f"{location}.{prop.name}",
                child_context,
                rules,
                next_levels,
            )
        elif prop.type_name in ("IntProperty", "ArrayProperty"):
            if type(prop.value) is not int:
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} must have an integer value."
                )
            if prop.type_name == "IntProperty" and not (
                rules["min_int_property_value"]
                <= prop.value
                <= rules["max_int_property_value"]
            ):
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} must be between "
                    f"{rules['min_int_property_value']} and "
                    f"{rules['max_int_property_value']} inclusive."
                )
        elif prop.type_name == "BoolProperty":
            if type(prop.value) is not bool:
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} must be true or false."
                )
            if prop.raw_body is not None and prop.raw_body not in (
                b"\0",
                b"\1",
                bytes(4) + b"\0",
                bytes(4) + b"\1",
            ):
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} has an invalid boolean encoding."
                )
        elif prop.type_name in ("StrProperty", "NameProperty"):
            if not isinstance(prop.value, str):
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} must have a string value."
                )
            if prop.type_name == "NameProperty" and type(prop.name_number) is not int:
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} must have an integer name_number."
                )
            string_length_limit = (
                rules["max_pool_file_name_length"]
                if prop.name == "PoolFileName"
                else rules["max_background_text_length"]
                if prop.name == "BackgroundText"
                else rules["max_string_length"]
            )
            if (
                prop.name not in rules["string_length_exemptions"]
                and len(prop.value) > string_length_limit
            ):
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} exceeds the strict string "
                    f"length limit of {string_length_limit} characters."
                )
            if prop.name == "PoolFileName":
                if not rules["_compiled_pool_file_name_pattern"].fullmatch(prop.value):
                    raise PoolFormatError(
                        f"Property {prop.name!r} at {location} must be a relative "
                        "path or filename ending with '.bin'."
                    )
            elif prop.name in rules["relaxed_string_fields"]:
                printable_value = prop.value
                if prop.name == "BackgroundText":
                    printable_value = printable_value.replace("\r", "").replace(
                        "\n", ""
                    )
                if printable_value and not printable_value.isprintable():
                    raise PoolFormatError(
                        f"Property {prop.name!r} at {location} must contain only "
                        "printable characters."
                    )
            elif prop.name not in rules["string_exemptions"] and not rules[
                "_compiled_string_pattern"
            ].fullmatch(prop.value):
                raise PoolFormatError(
                    f"Property {prop.name!r} at {location} contains characters "
                    "outside [A-Za-z0-9_]."
                )


def _validate_character(
    character: Character, location: str, rules: dict[str, Any] | None = None
) -> None:
    if rules is None:
        rules = _load_strict_rules()
    _validate_properties(character.properties, location, "character", rules)


def _validate_pool(pool: Pool) -> None:
    rules = _load_strict_rules()
    _validate_properties(pool.header_properties, "header", "header", rules)
    for index, character in enumerate(pool.characters):
        _validate_properties(
            character.properties, f"characters[{index}]", "character", rules
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

    def to_bytes(self, *, strict: bool = True) -> bytes:
        if strict:
            _validate_character(self, "character")
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

    def to_bytes(self, *, strict: bool = True) -> bytes:
        if strict:
            _validate_pool(self)
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
                            self.file_name
                            or "CharacterPool\\Importable\\Unsaved Pool.bin",
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
                    "PoolFileName",
                    "StrProperty",
                    self.file_name or "CharacterPool\\Importable\\Unsaved Pool.bin",
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
            content.extend(character.to_bytes(strict=False))
        return bytes(content)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": "xcom2-characterpool-json-v1",
            "pool_file_name": self.file_name,
            "header_properties": [prop.to_dict() for prop in self.header_properties],
            "characters": [character.to_dict() for character in self.characters],
        }

    @classmethod
    def from_json(cls, document: dict[str, Any], *, strict: bool = True) -> Pool:
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
        pool_file_name = document.get("pool_file_name")
        if pool_file_name:
            if strict and not isinstance(pool_file_name, str):
                raise PoolFormatError("pool_file_name must be a string in strict mode.")
            pool.file_name = str(pool_file_name)
        if strict:
            _validate_pool(pool)
        return pool


def _current_pool_timestamp() -> str:
    current = datetime.now()
    return (
        f"{_MONTH_NAMES[current.month - 1]} {current.day}, {current.year} - "
        f"{current:%I:%M %p}"
    )


def _random_date(start_year: int, end_year: int) -> date:
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    return start + timedelta(days=random.randrange((end - start).days + 1))


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
        countries = generation_data.get("countries_by_template", {}).get(
            template_name, {}
        )
        country_names = list(countries)
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
        backgrounds = template_data.get("background_texts", [])
        if not backgrounds and template_name == "Soldier":
            backgrounds = soldier_data.get("background_texts", [])
            if not backgrounds:
                raise PoolFormatError(
                    f"No background text is configured for {template_name!r}."
                )
        if backgrounds:
            background_text = random.choice(backgrounds)
            background_headers: list[str] = []
            if template_name == "Soldier":
                country_label = countries.get(selected_country, selected_country)
                background_headers.append(f"Country of Origin: {country_label}")
            birth_years = {
                "Soldier": (1990, 2010),
                "ReaperSoldier": (1985, 2005),
                "SkirmisherSoldier": (2020, 2034),
                "TemplarSoldier": (1990, 2010),
            }.get(template_name)
            if birth_years is not None:
                birth_date = _random_date(*birth_years)
                background_headers.append(
                    f"Date of Birth: {_MONTH_NAMES[birth_date.month - 1]} "
                    f"{birth_date.day}, {birth_date.year}"
                )
            if background_headers:
                header_text = "\n".join(background_headers)
                background_text = f"{header_text}\n\n{background_text}"
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
    strict: bool = True,
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
    character = _generate_character(
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
    if strict:
        _validate_character(character, "generated character")
    return character


def generate_characters(
    requests: Iterable[Mapping[str, str]],
    *,
    existing_characters: Iterable[Character] = (),
    strict: bool = True,
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
    characters = [
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
    if strict:
        rules = _load_strict_rules()
        for index, character in enumerate(characters):
            _validate_character(character, f"generated characters[{index}]", rules)
    return characters


def read_pool(path: str | Path | bytes, *, strict: bool = True) -> Pool:
    data = path if isinstance(path, bytes) else _read_pool_file(path)
    if len(data) > _MAX_POOL_INPUT_BYTES:
        raise PoolFormatError("Pool input exceeds the 64 MiB size limit.")
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
    pool = Pool(header, characters)
    if strict:
        _validate_pool(pool)
    return pool


def write_pool(pool: Pool, path: str | Path, *, strict: bool = True) -> None:
    Path(path).write_bytes(pool.to_bytes(strict=strict))


def save_json(pool: Pool, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(pool.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json(path: str | Path, *, strict: bool = True) -> Pool:
    try:
        document = json.loads(_read_pool_file(path).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PoolFormatError(f"Could not read JSON pool: {exc}") from exc
    if not isinstance(document, dict):
        raise PoolFormatError("Pool JSON must contain an object at the top level.")
    return Pool.from_json(document, strict=strict)
