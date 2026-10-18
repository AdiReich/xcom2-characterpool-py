from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .format import PoolFormatError, Property
from .pool import Character, Pool, load_json, read_pool, save_json, write_pool

DATA_DIR = Path(__file__).resolve().parent / "data" / "Files"


def _read_asset(path: Path) -> str:
    encoding = (
        "utf-16" if path.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    )
    return path.read_text(encoding=encoding)


def _character(first_name: str, last_name: str, nickname: str = "") -> Character:
    appearance = [
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
    now = (
        datetime.now().strftime("%B %-d, %Y - %-I:%M %p")
        if sys.platform != "win32"
        else datetime.now().strftime("%B %#d, %Y - %#I:%M %p")
    )
    return Character(
        [
            Property("strFirstName", "StrProperty", first_name),
            Property("strLastName", "StrProperty", last_name),
            Property("strNickName", "StrProperty", f"'{nickname}'" if nickname else ""),
            Property("CharacterTemplateName", "NameProperty", "Soldier"),
            Property("m_SoldierClassTemplateName", "NameProperty", "Rookie"),
            Property("Country", "NameProperty", "Country_USA"),
            Property("kAppearance", "StructProperty", appearance),
            Property("AllowedTypeSoldier", "BoolProperty", True),
            Property("AllowedTypeVIP", "BoolProperty", False),
            Property("AllowedTypeDarkVIP", "BoolProperty", False),
            Property("PoolTimestamp", "StrProperty", now),
            Property("BackgroundText", "StrProperty", ""),
        ]
    )


def _get_property(properties: list[Property], key: str) -> Property | None:
    for prop in properties:
        if prop.name == key:
            return prop
        if prop.type_name == "StructProperty" and isinstance(prop.value, list):
            nested = _get_property(prop.value, key)
            if nested is not None:
                return nested
    return None


def _character_identity(character: Character) -> tuple[tuple[str, Any], ...]:
    def property_value(prop: Property) -> Any:
        if prop.type_name == "StructProperty":
            return "".join(
                child.name + str(property_value(child)) for child in prop.value
            )
        if isinstance(prop.value, bool):
            return "1" if prop.value else "0"
        return None if prop.value is None else str(prop.value)

    return tuple((prop.name, property_value(prop)) for prop in character.properties)


def _set_value(prop: Property, value: str) -> None:
    if prop.type_name in ("IntProperty", "ArrayProperty"):
        prop.value = int(value)
    elif prop.type_name == "BoolProperty":
        normalized = value.casefold()
        if normalized not in ("true", "false", "1", "0"):
            raise PoolFormatError(f"Expected true/false for {prop.name}.")
        prop.value = normalized in ("true", "1")
    else:
        prop.value = value
    prop.raw_body = None
    prop.original_value = None


def _load_templates() -> list[dict[str, str]]:
    template_dir = DATA_DIR / "Templates"
    localizations: dict[str, str] = {}
    for loc_path in (DATA_DIR / "Localization").glob("*_en.txt"):
        for line in _read_asset(loc_path).splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                localizations.setdefault(key, value)

    templates = []
    for path in sorted(template_dir.glob("*.txt")):
        if path.name == "Persistent Choices.txt":
            origin = "Vanilla Choices"
        elif path.stem in (
            "Vanilla",
            "WotC",
            "Tactical Legacy Pack",
            "Anarchy's Children",
            "Alien Hunters",
            "Shens Last Gift",
            "Resistance Warrior Pack",
            "CapnBubs",
            "Female Hair Pack",
            "Male Hair Pack",
        ):
            origin = path.stem
        else:
            continue
        for line in _read_asset(path).splitlines():
            fields: dict[str, str] = {}
            for piece in line.split(","):
                if "=" in piece:
                    key, value = piece.split("=", 1)
                    fields[key.strip()] = value.strip()
            name = fields.get("TemplateName")
            if not name:
                continue
            fields.update(
                {
                    "Name": name,
                    "Display": localizations.get(name, name),
                    "Origin": origin,
                }
            )
            templates.append(fields)
    return templates


def _cmd_inspect(args: argparse.Namespace) -> int:
    for path in args.pools:
        pool = read_pool(path)
        print(
            f"{path}: {len(pool.characters)} characters; pool name: {pool.file_name or '(unnamed)'}"
        )
        for index, character in enumerate(pool.characters):
            print(f"  {index:4d}  {character.full_name or '(unnamed)'}")
    return 0


def _cmd_inspect_character(args: argparse.Namespace) -> int:
    pool = read_pool(args.pool)
    if args.index < 0 or args.index >= len(pool.characters):
        raise PoolFormatError(f"Character index out of range: {args.index}.")
    character = pool.characters[args.index]
    print(
        json.dumps(
            {
                "index": args.index,
                "name": character.full_name,
                **character.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    pools = [read_pool(path) for path in args.pools]
    result = Pool(list(pools[0].header_properties), [])
    seen: set[tuple[tuple[str, Any], ...]] = set()
    duplicates = 0
    for pool in pools:
        for character in pool.characters:
            identity = _character_identity(character)
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            result.characters.append(character)
    result.file_name = f"CharacterPool\\Importable\\{Path(args.output).name}"
    write_pool(result, args.output)
    print(
        f"Merged {len(pools)} pools: wrote {len(result.characters)} characters to {args.output} ({duplicates} duplicates skipped)."
    )
    return 0


def _cmd_new(args: argparse.Namespace) -> int:
    name = f"CharacterPool\\Importable\\{Path(args.output).name}"
    characters = (
        []
        if args.empty
        else [_character(args.first_name, args.last_name, args.nickname)]
    )
    pool = Pool([Property("PoolFileName", "StrProperty", name)], characters)
    write_pool(pool, args.output)
    print(f"Created pool with {len(characters)} characters: {args.output}")
    return 0


def _cmd_export_json(args: argparse.Namespace) -> int:
    pool = read_pool(args.pool)
    if args.output == "-":
        print(json.dumps(pool.to_json(), ensure_ascii=False, indent=2))
    else:
        save_json(pool, args.output)
        print(f"Exported {len(pool.characters)} characters to {args.output}")
    return 0


def _cmd_import_json(args: argparse.Namespace) -> int:
    pool = load_json(args.json_file)
    pool.file_name = f"CharacterPool\\Importable\\{Path(args.output).name}"
    write_pool(pool, args.output)
    print(f"Wrote {len(pool.characters)} characters to {args.output}")
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    pool = read_pool(args.pool)
    pool.characters.append(_character(args.first_name, args.last_name, args.nickname))
    write_pool(pool, args.output)
    print(f"Added character; pool now contains {len(pool.characters)} characters.")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    pool = read_pool(args.pool)
    indexes = set(args.index)
    invalid = sorted(
        index for index in indexes if index < 0 or index >= len(pool.characters)
    )
    if invalid:
        raise PoolFormatError(
            f"Character index out of range: {', '.join(map(str, invalid))}."
        )
    pool.characters = [
        character
        for index, character in enumerate(pool.characters)
        if index not in indexes
    ]
    write_pool(pool, args.output)
    print(
        f"Deleted {len(indexes)} characters; pool now contains {len(pool.characters)}."
    )
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    pool = read_pool(args.pool)
    if args.index < 0 or args.index >= len(pool.characters):
        raise PoolFormatError(f"Character index out of range: {args.index}.")
    character = pool.characters[args.index]
    for assignment in args.property:
        if "=" not in assignment:
            raise PoolFormatError(
                f"Invalid assignment {assignment!r}; expected PROPERTY=VALUE."
            )
        key, value = assignment.split("=", 1)
        prop = _get_property(character.properties, key)
        if prop is None:
            raise PoolFormatError(f"Character property not found: {key}.")
        _set_value(prop, value)
    write_pool(pool, args.output)
    print(f"Updated character {args.index}: {character.full_name}")
    return 0


def _cmd_templates(args: argparse.Namespace) -> int:
    templates = _load_templates()
    filters = (
        ("search", args.search),
        ("PartType", args.part_type),
        ("Origin", args.origin),
    )
    for field, needle in filters:
        if needle:
            key = "Display" if field == "search" else field
            templates = [
                item
                for item in templates
                if needle.casefold()
                in (
                    item.get(key, "")
                    + (" " + item.get("Name", "") if field == "search" else "")
                ).casefold()
            ]
    for item in templates[: args.limit]:
        print(
            f"{item['Display']}\t{item['Name']}\t{item.get('PartType', '')}\t{item['Origin']}"
        )
    print(f"{min(len(templates), args.limit)} of {len(templates)} matching templates")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xcom2-characterpool",
        description="Inspect, edit, create, and merge XCOM 2 character pools.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser(
        "inspect", help="List characters in one or more .bin pools"
    )
    inspect.add_argument("pools", nargs="+", help="Input pool files")
    inspect.set_defaults(handler=_cmd_inspect)

    inspect_character = commands.add_parser(
        "inspect-character", help="Show all properties for a character by index"
    )
    inspect_character.add_argument("pool", help="Input .bin pool")
    inspect_character.add_argument(
        "--index", type=int, required=True, help="Zero-based character index"
    )
    inspect_character.set_defaults(handler=_cmd_inspect_character)

    merge = commands.add_parser(
        "merge", help="Merge pools and skip duplicate characters"
    )
    merge.add_argument("pools", nargs="+", help="Input pool files")
    merge.add_argument("-o", "--output", required=True, help="Output .bin path")
    merge.set_defaults(handler=_cmd_merge)

    new = commands.add_parser(
        "new", help="Create a new pool, with a starter soldier by default"
    )
    new.add_argument("output", help="Output .bin path")
    new.add_argument("--first-name", default="New")
    new.add_argument("--last-name", default="Character")
    new.add_argument("--nickname", default="")
    new.add_argument("--empty", action="store_true", help="Create an empty pool")
    new.set_defaults(handler=_cmd_new)

    export = commands.add_parser("export-json", help="Export a pool to editable JSON")
    export.add_argument("pool")
    export.add_argument(
        "-o", "--output", default="-", help="JSON file, or - for stdout"
    )
    export.set_defaults(handler=_cmd_export_json)

    imp = commands.add_parser(
        "import-json", help="Build a .bin pool from exported JSON"
    )
    imp.add_argument("json_file")
    imp.add_argument("-o", "--output", required=True)
    imp.set_defaults(handler=_cmd_import_json)

    add = commands.add_parser("add", help="Append a starter soldier to a pool")
    add.add_argument("pool")
    add.add_argument("-o", "--output", required=True)
    add.add_argument("--first-name", required=True)
    add.add_argument("--last-name", required=True)
    add.add_argument("--nickname", default="")
    add.set_defaults(handler=_cmd_add)

    delete = commands.add_parser("delete", help="Remove characters by zero-based index")
    delete.add_argument("pool")
    delete.add_argument("-o", "--output", required=True)
    delete.add_argument("--index", type=int, action="append", required=True)
    delete.set_defaults(handler=_cmd_delete)

    set_cmd = commands.add_parser("set", help="Set one or more character properties")
    set_cmd.add_argument("pool")
    set_cmd.add_argument("-o", "--output", required=True)
    set_cmd.add_argument(
        "--index", type=int, required=True, help="Zero-based character index"
    )
    set_cmd.add_argument(
        "--property",
        action="append",
        required=True,
        help="PROPERTY=VALUE; appearance properties may use their property name directly",
    )
    set_cmd.set_defaults(handler=_cmd_set)

    templates = commands.add_parser(
        "templates", help="Search bundled customization templates"
    )
    templates.add_argument("--search")
    templates.add_argument("--part-type")
    templates.add_argument("--origin")
    templates.add_argument("--limit", type=int, default=50)
    templates.set_defaults(handler=_cmd_templates)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (PoolFormatError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
