import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from xcom2_characterpool_py import generate_character, generate_characters
from xcom2_characterpool_py.cli import main
from xcom2_characterpool_py.format import PoolFormatError, Property
from xcom2_characterpool_py.pool import Character, Pool, load_json, read_pool


def _generation_data() -> dict[str, dict[str, list[str]]]:
    return {
        "countries_by_template": {
            "Soldier": {
                "Country_USA": "United States",
                "Country_Poland": "Poland",
            },
            "SkirmisherSoldier": {"Country_Skirmisher": "Skirmisher"},
            "ReaperSoldier": {"Country_Reaper": "Reaper"},
            "TemplarSoldier": {"Country_Templar": "Templar"},
            "SparkSoldier": {"Country_Spark": "Spark"},
        },
        "Soldier": {
            "background_texts": ["Template biography", "Available biography"],
        },
    }


def _character(first_name: str, last_name: str, nickname: str = "") -> Character:
    return Character(
        [
            Property("strFirstName", "StrProperty", first_name),
            Property("strLastName", "StrProperty", last_name),
            Property("strNickName", "StrProperty", f"'{nickname}'" if nickname else ""),
            Property("CharacterTemplateName", "NameProperty", "Soldier"),
            Property("m_SoldierClassTemplateName", "NameProperty", "Rookie"),
            Property("Country", "NameProperty", "Country_USA"),
            Property(
                "kAppearance",
                "StructProperty",
                [Property("nmHaircut", "NameProperty", "")],
            ),
            Property("AllowedTypeSoldier", "BoolProperty", True),
            Property("AllowedTypeVIP", "BoolProperty", False),
            Property("AllowedTypeDarkVIP", "BoolProperty", False),
            Property("PoolTimestamp", "StrProperty", "20200101_000000"),
            Property("BackgroundText", "StrProperty", ""),
        ]
    )


class PoolTests(unittest.TestCase):
    def make_pool(self) -> Pool:
        return Pool(
            [Property("PoolFileName", "StrProperty", "fixture.bin")],
            [_character("Ada", "Test", "Viper")],
        )

    def test_unchanged_binary_round_trip_is_identical(self) -> None:
        pool = self.make_pool()
        original = pool.to_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(original)
            self.assertEqual(read_pool(path).to_bytes(), original)

    def test_read_pool_accepts_bytes(self) -> None:
        pool = self.make_pool()

        self.assertEqual(read_pool(pool.to_bytes()).to_bytes(), pool.to_bytes())

    def test_read_pool_rejects_input_over_size_limit(self) -> None:
        with (
            patch("xcom2_characterpool_py.pool._MAX_POOL_INPUT_BYTES", 4),
            self.assertRaisesRegex(PoolFormatError, "64 MiB size limit"),
        ):
            read_pool(b"12345")

    def test_load_json_rejects_input_over_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b"12345")
            with (
                patch("xcom2_characterpool_py.pool._MAX_POOL_INPUT_BYTES", 4),
                self.assertRaisesRegex(PoolFormatError, "64 MiB size limit"),
            ):
                load_json(path)

    def test_strict_read_rejects_unknown_property_and_permissive_read_accepts_it(
        self,
    ) -> None:
        pool = Pool([], [Character([Property("ModdedField", "IntProperty", 7)])])
        data = pool.to_bytes(strict=False)

        with self.assertRaisesRegex(PoolFormatError, "Unknown property 'ModdedField'"):
            read_pool(data)

        restored = read_pool(data, strict=False)
        self.assertEqual(restored.characters[0].get("ModdedField"), 7)

    def test_strict_json_import_rejects_unknown_property(self) -> None:
        pool = Pool([], [Character([Property("ModdedField", "IntProperty", 7)])])
        document = pool.to_json()

        with self.assertRaisesRegex(PoolFormatError, "Unknown property 'ModdedField'"):
            Pool.from_json(document)

        restored = Pool.from_json(document, strict=False)
        self.assertEqual(restored.characters[0].get("ModdedField"), 7)

    def test_cli_no_strict_allows_unknown_properties(self) -> None:
        pool = Pool([], [Character([Property("ModdedField", "IntProperty", 7)])])
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "modded.bin"
            source.write_bytes(pool.to_bytes(strict=False))

            with redirect_stderr(StringIO()):
                self.assertEqual(main(["inspect", str(source)]), 2)
            with redirect_stdout(StringIO()):
                self.assertEqual(main(["inspect", str(source), "--no-strict"]), 0)

    def test_strict_serialization_requires_exact_integer_and_boolean_types(
        self,
    ) -> None:
        integer_pool = Pool([], [Character([Property("iRace", "IntProperty", True)])])
        boolean_pool = Pool(
            [], [Character([Property("AllowedTypeVIP", "BoolProperty", 1)])]
        )

        with self.assertRaisesRegex(PoolFormatError, "must have an integer value"):
            integer_pool.to_bytes()
        with self.assertRaisesRegex(PoolFormatError, "must be true or false"):
            boolean_pool.to_bytes()

        for value in (-1, 0, 200):
            Pool([], [Character([Property("iRace", "IntProperty", value)])]).to_bytes()
        for value in (-2, 201):
            with self.subTest(value=value):
                pool = Pool([], [Character([Property("iRace", "IntProperty", value)])])
                with self.assertRaisesRegex(PoolFormatError, "between -1 and 200"):
                    pool.to_bytes()

        Pool([], [Character([]) for _ in range(101)]).to_bytes()

    def test_strict_binary_read_rejects_noncanonical_boolean_byte(self) -> None:
        character = Character(
            [Property("AllowedTypeVIP", "BoolProperty", True, b"\2", True)]
        )
        data = Pool([], [character]).to_bytes(strict=False)

        with self.assertRaisesRegex(PoolFormatError, "invalid boolean encoding"):
            read_pool(data)

    def test_strict_pool_file_name_requires_bin_filename(self) -> None:
        for value in (
            "fixture.bin",
            "CharacterPool\\Importable\\15 soldiers.bin",
            "Unsaved Pool",
        ):
            with self.subTest(value=value):
                Pool([Property("PoolFileName", "StrProperty", value)], []).to_bytes()

        for value in (
            "CharacterPool\\Importable\\soldier.txt",
            "CharacterPool\\..\\soldier.bin",
            "CharacterPool\\Importable\\bad:name.bin",
        ):
            with self.subTest(value=value):
                pool = Pool([Property("PoolFileName", "StrProperty", value)], [])
                with self.assertRaisesRegex(
                    PoolFormatError, "relative path or filename"
                ):
                    pool.to_bytes()

        default_pool = read_pool(Pool([], []).to_bytes())
        self.assertEqual(
            default_pool.file_name, "CharacterPool\\Importable\\Unsaved Pool.bin"
        )

    def test_strict_strings_allow_names_and_background_but_reject_other_punctuation(
        self,
    ) -> None:
        allowed = Pool(
            [],
            [
                Character(
                    [
                        Property("strFirstName", "StrProperty", "Ana María"),
                        Property(
                            "BackgroundText",
                            "StrProperty",
                            "Text,\nwith punctuation! " * 5,
                        ),
                        Property(
                            "PoolTimestamp",
                            "StrProperty",
                            "January 22, 2016 - 10:55 AM",
                        ),
                    ]
                )
            ],
        )
        allowed.to_bytes()

        invalid = Pool(
            [], [Character([Property("Country", "NameProperty", "United-States")])]
        )
        with self.assertRaisesRegex(PoolFormatError, r"outside \[A-Za-z0-9_\]"):
            invalid.to_bytes()

        invalid_text = Pool(
            [],
            [Character([Property("PoolTimestamp", "StrProperty", "Oct 21, 2026\x00")])],
        )
        with self.assertRaisesRegex(PoolFormatError, "printable characters"):
            invalid_text.to_bytes()

        for prop in (
            Property("strFirstName", "StrProperty", "A" * 51),
            Property("nmBeard", "NameProperty", "A" * 51),
        ):
            with self.subTest(property_name=prop.name):
                with self.assertRaisesRegex(PoolFormatError, "50 characters"):
                    Pool([], [Character([prop])]).to_bytes()

        valid_long_path = "CharacterPool\\Importable\\" + "A" * 71 + ".bin"
        Pool([Property("PoolFileName", "StrProperty", valid_long_path)], []).to_bytes()

        invalid_long_path = "CharacterPool\\Importable\\" + "A" * 72 + ".bin"
        with self.assertRaisesRegex(PoolFormatError, "100 characters"):
            Pool(
                [Property("PoolFileName", "StrProperty", invalid_long_path)], []
            ).to_bytes()

    def test_strict_background_text_has_2000_character_limit(self) -> None:
        at_limit = Pool(
            [], [Character([Property("BackgroundText", "StrProperty", "A" * 2000)])]
        )
        at_limit.to_bytes()

        over_limit = Pool(
            [], [Character([Property("BackgroundText", "StrProperty", "A" * 2001)])]
        )
        with self.assertRaisesRegex(PoolFormatError, "2000 characters"):
            over_limit.to_bytes()

    def test_strict_mode_allows_two_struct_levels_only(self) -> None:
        appearance = Property(
            "kAppearance",
            "StructProperty",
            [Property("bGhostPawn", "BoolProperty", False)],
        )
        helper = Property(
            "CharacterPoolSerializeHelper",
            "StructProperty",
            [appearance],
            struct_tag="CharacterPoolDataElement",
        )
        Pool([helper], []).to_bytes()

        appearance.value.append(
            Property(
                "kAppearance",
                "StructProperty",
                [Property("bGhostPawn", "BoolProperty", False)],
            )
        )
        with self.assertRaisesRegex(PoolFormatError, "strict limit of 2 levels"):
            Pool([helper], []).to_bytes()

    def test_property_parser_rejects_invalid_encoded_name(self) -> None:
        malformed = struct.pack("<i", 2) + b"\x81\0" + bytes(4)

        with self.assertRaisesRegex(PoolFormatError, "Invalid encoded property string"):
            Property.read(malformed, 0)

    def test_json_property_parser_rejects_excessive_nesting(self) -> None:
        nested_property = {"name": "leaf", "type": "StrProperty", "value": ""}
        for _ in range(5):
            nested_property = {
                "name": "nested",
                "type": "StructProperty",
                "value": [nested_property],
            }
        Property.from_dict(nested_property)

        for _ in range(6):
            nested_property = {
                "name": "nested",
                "type": "StructProperty",
                "value": [nested_property],
            }

        with self.assertRaisesRegex(PoolFormatError, "nesting exceeds"):
            Property.from_dict(nested_property)

    def test_binary_property_parser_rejects_excessive_nesting(self) -> None:
        nested_property = Property("leaf", "StrProperty", "")
        for _ in range(5):
            nested_property = Property("nested", "StructProperty", [nested_property])
        serialized = nested_property.to_bytes()
        parsed, offset = Property.read(serialized, 0)
        self.assertEqual(offset, len(serialized))
        self.assertIsNotNone(parsed)

        for _ in range(6):
            nested_property = Property("nested", "StructProperty", [nested_property])

        with self.assertRaisesRegex(PoolFormatError, "nesting exceeds"):
            Property.read(nested_property.to_bytes(), 0)

    def test_characters_without_appearance_are_serialized_first(self) -> None:
        appearance_character = _character("Ada", "Test")
        generated_character = Character(
            [Property("strFirstName", "StrProperty", "Grace")]
        )
        pool = Pool([], [appearance_character, generated_character])

        serialized_characters = read_pool(pool.to_bytes()).characters

        self.assertEqual(
            [character.full_name for character in serialized_characters],
            ["Grace", "Ada Test"],
        )

    def test_pool_header_property_order_is_preserved(self) -> None:
        pool = Pool(
            [
                Property("CharacterPool", "ArrayProperty", 0),
                Property("PoolFileName", "StrProperty", "fixture.bin"),
                Property("CharacterPoolSerializeHelper", "IntProperty", 2),
                Property("GenderHelper", "IntProperty", 1),
            ],
            [],
        )
        expected_names = [prop.name for prop in pool.header_properties]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(pool.to_bytes(strict=False))
            restored = read_pool(path, strict=False)
            self.assertEqual(restored.to_bytes(strict=False), path.read_bytes())

        self.assertEqual(
            [prop.name for prop in restored.header_properties], expected_names
        )

    def test_json_round_trip_preserves_struct_and_data(self) -> None:
        pool = self.make_pool()
        restored = Pool.from_json(pool.to_json())
        self.assertEqual(restored.to_bytes(), pool.to_bytes())

    def test_json_round_trip_preserves_original_property_encodings(self) -> None:
        appearance = Property(
            "kAppearance",
            "StructProperty",
            [
                Property("AllowedTypeVIP", "BoolProperty", True, b"\1", True),
                Property("BackgroundText", "StrProperty", "", bytes(4), ""),
            ],
        )
        pool = Pool([], [Character([appearance])])

        restored = Pool.from_json(pool.to_json(), strict=False)

        self.assertEqual(restored.to_bytes(strict=False), pool.to_bytes(strict=False))
        restored.characters[0].properties[0].value[0].value = False
        self.assertNotEqual(
            restored.to_bytes(strict=False), pool.to_bytes(strict=False)
        )

    def test_empty_raw_data_is_regenerated_from_property_values(self) -> None:
        pool = Pool(
            [],
            [
                _character("Ada", "Test", "Viper"),
                _character("Grace", "Hopper"),
            ],
        )
        document = read_pool(pool.to_bytes()).to_json()

        def clear_raw_data(value: object) -> None:
            if isinstance(value, dict):
                for key in ("raw_body", "raw_value"):
                    if key in value:
                        value[key] = ""
                for child in value.values():
                    clear_raw_data(child)
            elif isinstance(value, list):
                for child in value:
                    clear_raw_data(child)

        clear_raw_data(document)
        restored = Pool.from_json(document)
        parsed = read_pool(restored.to_bytes())

        self.assertEqual(len(parsed.characters), 2)
        self.assertEqual(
            [character.full_name for character in parsed.characters],
            ["Ada Viper Test", "Grace Hopper"],
        )

    def test_stripped_json_preserves_name_numbers_and_string_encodings(self) -> None:
        background = "Ne ne ya ZOЖ"
        background_utf16 = background.encode("utf-16-le") + bytes(2)
        properties = [
            Property(
                "nmEye",
                "NameProperty",
                "DefaultEyes",
                struct.pack("<i", 12) + b"DefaultEyes\0" + struct.pack("<i", 3),
                "DefaultEyes",
                name_number=3,
            ),
            Property(
                "nmTeeth",
                "NameProperty",
                "DefaultTeeth",
                struct.pack("<i", 13) + b"DefaultTeeth\0" + bytes(4),
                "DefaultTeeth",
            ),
            Property(
                "BackgroundText",
                "StrProperty",
                background,
                struct.pack("<i", -(len(background) + 1)) + background_utf16,
                background,
            ),
            Property(
                "EmptyBackground",
                "StrProperty",
                "",
                bytes(4),
                "",
            ),
            Property(
                "LineBackground",
                "StrProperty",
                "First line\nSecond line",
                struct.pack("<i", 23) + b"First line\nSecond line\0",
                "First line\nSecond line",
            ),
        ]
        parsed_eye, offset = Property.read(properties[0].to_bytes(), 0)
        self.assertEqual(offset, len(properties[0].to_bytes()))
        self.assertEqual(parsed_eye.name_number, 3)
        original = b"".join(prop.to_bytes() for prop in properties)
        document = [prop.to_dict() for prop in properties]
        self.assertEqual(document[0]["name_number"], 3)
        self.assertEqual(document[0]["raw_body"], properties[0].raw_body.hex())
        self.assertEqual(document[0]["raw_value"], "DefaultEyes")
        for prop in document:
            prop.pop("raw_body", None)
            prop.pop("raw_value", None)

        rebuilt = b"".join(Property.from_dict(prop).to_bytes() for prop in document)

        self.assertEqual(rebuilt, original)

    def test_json_rebuild_preserves_tag_first_struct_boundaries(self) -> None:
        pool = Pool(
            [],
            [
                Character(
                    [
                        Property("strFirstName", "StrProperty", "Ada"),
                        Property(
                            "kAppearance",
                            "StructProperty",
                            [
                                Property(
                                    "bGhostPawn", "BoolProperty", False, b"\0", False
                                )
                            ],
                            struct_layout="tag-first",
                        ),
                    ]
                ),
                Character(
                    [
                        Property("strFirstName", "StrProperty", "Grace"),
                        Property(
                            "kAppearance",
                            "StructProperty",
                            [Property("bGhostPawn", "BoolProperty", True, b"\1", True)],
                            struct_layout="tag-first",
                        ),
                    ]
                ),
            ],
        )
        document = pool.to_json()

        def clear_raw_data(value: object) -> None:
            if isinstance(value, dict):
                for key in ("raw_body", "raw_value"):
                    if key in value:
                        value[key] = ""
                for child in value.values():
                    clear_raw_data(child)
            elif isinstance(value, list):
                for child in value:
                    clear_raw_data(child)

        clear_raw_data(document)
        restored = Pool.from_json(document)
        parsed = read_pool(restored.to_bytes())

        self.assertEqual(
            [character.full_name for character in parsed.characters],
            ["Ada", "Grace"],
        )
        for character in parsed.characters:
            appearance = next(
                prop for prop in character.properties if prop.name == "kAppearance"
            )
            self.assertEqual(appearance.declared_size, len(appearance.raw_body) - 20)

    def test_unicode_string_property_round_trip(self) -> None:
        text = "背景"
        encoded = text.encode("utf-16-le") + bytes(2)
        raw_body = (-3).to_bytes(4, "little", signed=True) + encoded
        prop = Property(
            "BackgroundText",
            "StrProperty",
            text,
            raw_body=raw_body,
            original_value=text,
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            target = Path(directory) / "export.json"
            source.write_bytes(Pool([], [Character([prop])]).to_bytes())

            result = main(["export-json", str(source), "-o", str(target)])

            self.assertEqual(result, 0)
            document = json.loads(target.read_text(encoding="utf-8"))

        exported = document["characters"][0]["properties"][0]
        self.assertEqual(exported["value"], text)
        self.assertEqual(bytes.fromhex(exported["raw_body"]), raw_body)

    def test_tag_first_struct_round_trip_preserves_layout(self) -> None:
        prop = Property(
            "CharacterPoolSerializeHelper",
            "StructProperty",
            [Property("strFirstName", "StrProperty", "Ada")],
            struct_tag="CharacterPoolDataElement",
            struct_layout="tag-first",
        )
        data = prop.to_bytes()

        restored, offset = Property.read(data, 0)

        self.assertEqual(offset, len(data))
        self.assertEqual(restored.struct_tag, "CharacterPoolDataElement")
        self.assertEqual(restored.struct_layout, "tag-first")
        pool = Pool([], [Character([restored])])
        json_restored = Pool.from_json(pool.to_json(), strict=False)
        self.assertEqual(
            json_restored.to_bytes(strict=False), pool.to_bytes(strict=False)
        )

        restored.value[0].value = "Grace"
        rewritten = restored.to_bytes()
        reparsed, offset = Property.read(rewritten, 0)
        self.assertEqual(offset, len(rewritten))
        self.assertEqual(reparsed.value[0].value, "Grace")
        self.assertEqual(reparsed.struct_layout, "tag-first")
        self.assertEqual(
            reparsed.declared_size,
            len(reparsed.raw_body) - len(reparsed.struct_tag.encode("cp1252")) - 9,
        )

    def test_compact_bool_round_trip_preserves_layout_when_edited(self) -> None:
        prop = Property("AllowedTypeVIP", "BoolProperty", True, b"\1", True)

        restored, offset = Property.read(prop.to_bytes(), 0)

        self.assertEqual(restored.value, True)
        self.assertEqual(restored.raw_body, b"\1")
        restored.value = False
        rewritten = restored.to_bytes()
        reparsed, offset = Property.read(rewritten, 0)
        self.assertEqual(reparsed.value, False)
        self.assertEqual(reparsed.raw_body, b"\0")

    def test_set_edits_nested_appearance_property(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            target = Path(directory) / "target.bin"
            source.write_bytes(self.make_pool().to_bytes())
            result = main(
                [
                    "set",
                    str(source),
                    "-o",
                    str(target),
                    "--index",
                    "0",
                    "--property",
                    "nmHaircut=Hair_Template",
                ]
            )
            self.assertEqual(result, 0)
            character = read_pool(target).characters[0]
            appearance = next(
                prop for prop in character.properties if prop.name == "kAppearance"
            )
            haircut = next(
                prop for prop in appearance.value if prop.name == "nmHaircut"
            )
            self.assertEqual(haircut.value, "Hair_Template")

    def test_inspect_character_outputs_properties_by_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            source.write_bytes(self.make_pool().to_bytes())
            output = StringIO()

            with redirect_stdout(output):
                result = main(["inspect-character", str(source), "--index", "0"])

            self.assertEqual(result, 0)
            inspected = json.loads(output.getvalue())
            self.assertEqual(inspected["index"], 0)
            self.assertEqual(inspected["name"], "Ada Viper Test")
            self.assertEqual(inspected["properties"][0]["name"], "strFirstName")

    def test_inspect_character_rejects_out_of_range_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            source.write_bytes(self.make_pool().to_bytes())
            error = StringIO()

            with redirect_stderr(error):
                result = main(["inspect-character", str(source), "--index", "1"])

            self.assertEqual(result, 2)
            self.assertIn("Character index out of range: 1", error.getvalue())

    def test_merge_skips_duplicate_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            target = Path(directory) / "merged.bin"
            source.write_bytes(self.make_pool().to_bytes())
            result = main(["merge", str(source), str(source), "-o", str(target)])
            self.assertEqual(result, 0)
            self.assertEqual(len(read_pool(target).characters), 1)

    def test_new_generates_starter_with_allowed_soldier_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "new-pool.bin"
            with patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda values: values[0],
            ):
                result = main(
                    [
                        "new",
                        str(target),
                        "--first-name",
                        "Alex",
                        "--last-name",
                        "Kim",
                        "--nickname",
                        "Viper",
                    ]
                )

            self.assertEqual(result, 0)
            character = read_pool(target).characters[0]
            self.assertEqual(character.get("strFirstName"), "Alex")
            self.assertEqual(character.get("strLastName"), "Kim")
            self.assertEqual(character.get("strNickName"), "'Viper'")
            self.assertEqual(character.get("CharacterTemplateName"), "Soldier")
            self.assertIn(
                character.get("m_SoldierClassTemplateName"),
                {"Ranger", "Sharpshooter", "Grenadier", "Specialist", "PsiOperative"},
            )

    def test_add_generates_required_fields_and_soldier_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            target = Path(directory) / "target.bin"
            source_pool = self.make_pool()
            source.write_bytes(source_pool.to_bytes())

            with (
                patch(
                    "xcom2_characterpool_py.pool._load_character_generation_data",
                    return_value=_generation_data(),
                ),
                patch(
                    "xcom2_characterpool_py.pool.random.choice",
                    side_effect=lambda values: values[0],
                ),
            ):
                result = main(
                    [
                        "add",
                        str(source),
                        "-o",
                        str(target),
                        "--first-name",
                        "Alex",
                        "--last-name",
                        "Kim",
                        "--nickname",
                        "Viper",
                    ]
                )

            self.assertEqual(result, 0)
            updated_pool = read_pool(target)
            added = updated_pool.characters[0]
            self.assertEqual(added.get("strFirstName"), "Alex")
            self.assertEqual(added.get("strLastName"), "Kim")
            self.assertEqual(added.get("strNickName"), "'Viper'")
            self.assertTrue(added.get("PoolTimestamp"))
            self.assertEqual(added.get("CharacterTemplateName"), "Soldier")
            self.assertTrue(added.get("AllowedTypeSoldier"))
            self.assertTrue(added.get("AllowedTypeVIP"))
            self.assertTrue(added.get("AllowedTypeDarkVIP"))
            self.assertEqual(added.get("Country"), "Country_USA")
            background_text = added.get("BackgroundText")
            self.assertTrue(
                background_text.startswith(
                    "Country of Origin: United States\nDate of Birth: "
                )
            )
            self.assertTrue(background_text.endswith("\n\nTemplate biography"))
            self.assertIsNone(added.get("kAppearance"))
            for name in (
                "AllowedTypeSoldier",
                "AllowedTypeVIP",
                "AllowedTypeDarkVIP",
            ):
                prop = next(prop for prop in added.properties if prop.name == name)
                self.assertEqual(prop.raw_body, b"\1")
            self.assertEqual(
                updated_pool.characters[1].to_bytes(),
                source_pool.characters[0].to_bytes(),
            )

    def test_generate_character_uses_extracted_country_and_background_data(
        self,
    ) -> None:
        with (
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda items: items[0],
            ),
            patch("xcom2_characterpool_py.pool.datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = datetime(2016, 1, 22, 10, 55)
            generated = generate_character("Alex", "Kim", "Viper")

        data_path = (
            Path(__file__).resolve().parents[1]
            / "xcom2_characterpool_py"
            / "data"
            / "Files"
            / "Templates"
            / "Character Generation Data.json"
        )
        generation_data = json.loads(data_path.read_text(encoding="utf-8"))
        soldier_data = generation_data["Soldier"]
        country_label = generation_data["countries_by_template"]["Soldier"][
            generated.get("Country")
        ]
        self.assertEqual(generated.get("strFirstName"), "Alex")
        self.assertEqual(generated.get("strLastName"), "Kim")
        self.assertEqual(generated.get("strNickName"), "'Viper'")
        self.assertEqual(generated.get("PoolTimestamp"), "January 22, 2016 - 10:55 AM")
        Pool([], [generated]).to_bytes()
        self.assertEqual(generated.get("CharacterTemplateName"), "Soldier")
        self.assertIn(
            generated.get("m_SoldierClassTemplateName"),
            {"Ranger", "Sharpshooter", "Grenadier", "Specialist", "PsiOperative"},
        )
        self.assertIn(
            generated.get("Country"),
            generation_data["countries_by_template"]["Soldier"],
        )
        self.assertTrue(generated.get("AllowedTypeSoldier"))
        self.assertTrue(generated.get("AllowedTypeVIP"))
        self.assertTrue(generated.get("AllowedTypeDarkVIP"))
        background_text = generated.get("BackgroundText")
        self.assertTrue(
            background_text.startswith(
                f"Country of Origin: {country_label}\nDate of Birth: "
            )
        )
        self.assertTrue(
            any(
                background_text.endswith(template)
                for template in soldier_data["background_texts"]
            )
        )
        self.assertIsNone(generated.get("kAppearance"))

    def test_generate_skirmisher_uses_template_background_data(self) -> None:
        data_path = (
            Path(__file__).resolve().parents[1]
            / "xcom2_characterpool_py"
            / "data"
            / "Files"
            / "Templates"
            / "Character Generation Data.json"
        )
        generation_data = json.loads(data_path.read_text(encoding="utf-8"))
        backgrounds = generation_data["SkirmisherSoldier"]["background_texts"]

        with patch(
            "xcom2_characterpool_py.pool.random.choice",
            side_effect=lambda items: items[0],
        ):
            generated = generate_character(
                "Alex",
                "Kim",
                character_template_name="SkirmisherSoldier",
                soldier_class_template_name="Skirmisher",
                country="Country_Skirmisher",
            )

        self.assertEqual(len(backgrounds), 200)
        self.assertTrue(
            any(
                generated.get("BackgroundText", "").endswith(text)
                for text in backgrounds
            )
        )

    def test_generated_background_headers_follow_character_type(self) -> None:
        data_path = (
            Path(__file__).resolve().parents[1]
            / "xcom2_characterpool_py"
            / "data"
            / "Files"
            / "Templates"
            / "Character Generation Data.json"
        )
        generation_data = json.loads(data_path.read_text(encoding="utf-8"))
        cases = (
            (
                "Soldier",
                "Ranger",
                "Country_USA",
                "Country of Origin: United States\nDate of Birth: December 31, 2010",
            ),
            (
                "ReaperSoldier",
                "Reaper",
                "Country_Reaper",
                "Date of Birth: December 31, 2005",
            ),
            (
                "SkirmisherSoldier",
                "Skirmisher",
                "Country_Skirmisher",
                "Date of Birth: December 31, 2034",
            ),
            (
                "TemplarSoldier",
                "Templar",
                "Country_Templar",
                "Date of Birth: December 31, 2010",
            ),
            (
                "SparkSoldier",
                "Spark",
                "Country_Spark",
                "",
            ),
        )
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=generation_data,
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda values: values[0],
            ),
            patch(
                "xcom2_characterpool_py.pool.random.randrange",
                side_effect=lambda stop: stop - 1,
            ),
        ):
            for template_name, soldier_class, country, expected_header in cases:
                with self.subTest(template_name=template_name):
                    generated = generate_character(
                        "Alex",
                        "Kim",
                        character_template_name=template_name,
                        soldier_class_template_name=soldier_class,
                        country=country,
                    )
                    background = generation_data[template_name]["background_texts"][0]
                    expected = (
                        f"{expected_header}\n\n{background}"
                        if expected_header
                        else background
                    )[:2000]
                    self.assertEqual(generated.get("BackgroundText"), expected)

    def test_generate_character_overrides_biography_and_omits_appearance(
        self,
    ) -> None:
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda items: items[0],
            ),
        ):
            generated = generate_character(
                "Alex",
                "Kim",
                biography="Custom biography",
                existing_characters=[_character("Existing", "Soldier")],
            )

        self.assertEqual(generated.get("BackgroundText"), "Custom biography")
        self.assertIsNone(generated.get("kAppearance"))

    def test_generate_characters_empty_input_does_not_load_data(self) -> None:
        with patch(
            "xcom2_characterpool_py.pool._load_character_generation_data",
        ) as load_data:
            self.assertEqual(generate_characters([]), [])

        load_data.assert_not_called()

    def test_generate_characters_preserves_request_order_and_names(self) -> None:
        requests = [
            {"first_name": "Ada", "last_name": "Lovelace", "nickname": "Ace"},
            {"first_name": "Grace", "last_name": "Hopper"},
        ]
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ) as load_data,
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda items: items[0],
            ),
        ):
            generated = generate_characters(requests)

        self.assertEqual(
            [
                (character.get("strFirstName"), character.get("strLastName"))
                for character in generated
            ],
            [("Ada", "Lovelace"), ("Grace", "Hopper")],
        )
        self.assertEqual(generated[0].get("strNickName"), "'Ace'")
        self.assertEqual(generated[1].get("strNickName"), "")
        load_data.assert_called_once_with()

    def test_generate_characters_accepts_optional_generation_fields(self) -> None:
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda values: values[0],
            ),
        ):
            generated = generate_characters(
                [
                    {
                        "first_name": "Mara",
                        "last_name": "Venn",
                        "character_template_name": "TemplarSoldier",
                        "soldier_class_template_name": "Templar",
                        "country": "Country_Templar",
                        "background_text": "Custom background",
                    }
                ]
            )[0]

        self.assertEqual(generated.get("CharacterTemplateName"), "TemplarSoldier")
        self.assertEqual(generated.get("m_SoldierClassTemplateName"), "Templar")
        self.assertEqual(generated.get("Country"), "Country_Templar")
        self.assertFalse(generated.get("AllowedTypeVIP"))
        self.assertTrue(generated.get("AllowedTypeDarkVIP"))
        self.assertEqual(generated.get("BackgroundText"), "Custom background")

    def test_faction_countries_are_loaded_from_generation_data(self) -> None:
        faction_types = (
            ("SkirmisherSoldier", "Skirmisher", "Country_Skirmisher"),
            ("ReaperSoldier", "Reaper", "Country_Reaper"),
            ("TemplarSoldier", "Templar", "Country_Templar"),
            ("SparkSoldier", "Spark", "Country_Spark"),
        )
        with patch(
            "xcom2_characterpool_py.pool.random.choice",
            side_effect=lambda values: values[0],
        ):
            generated = [
                generate_character(
                    "Test",
                    "Soldier",
                    character_template_name=template_name,
                    soldier_class_template_name=soldier_class,
                    country=country,
                )
                for template_name, soldier_class, country in faction_types
            ]

        self.assertEqual(
            [character.get("Country") for character in generated],
            [country for _, _, country in faction_types],
        )

    def test_generate_characters_omit_appearance_with_existing_characters(
        self,
    ) -> None:
        existing = _character("Existing", "Soldier")

        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda items: items[0],
            ),
        ):
            generated = generate_characters(
                [
                    {"first_name": "One", "last_name": "Name"},
                    {"first_name": "Two", "last_name": "Name"},
                ],
                existing_characters=[existing],
            )

        self.assertTrue(
            all(character.get("kAppearance") is None for character in generated)
        )

    def test_generate_characters_omit_appearance_for_batch(
        self,
    ) -> None:
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda items: items[0],
            ),
        ):
            generated = generate_characters(
                [
                    {"first_name": "One", "last_name": "Name"},
                    {"first_name": "Two", "last_name": "Name"},
                    {"first_name": "Three", "last_name": "Name"},
                ]
            )

        self.assertTrue(
            all(character.get("kAppearance") is None for character in generated)
        )

    def test_generate_character_applies_template_rules_and_limits(self) -> None:
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda values: values[0],
            ),
        ):
            generated = generate_character(
                "A" * 12,
                "L" * 16,
                "N" * 12,
                character_template_name="SparkSoldier",
                soldier_class_template_name="Spark",
                country="Country_Spark",
                background_text="B" * 2001,
            )

        self.assertEqual(generated.get("strFirstName"), "A" * 11)
        self.assertEqual(generated.get("strLastName"), "L" * 15)
        self.assertEqual(generated.get("strNickName"), "'" + "N" * 11 + "'")
        self.assertEqual(generated.get("CharacterTemplateName"), "SparkSoldier")
        self.assertEqual(generated.get("m_SoldierClassTemplateName"), "Spark")
        self.assertEqual(generated.get("Country"), "Country_Spark")
        self.assertTrue(generated.get("AllowedTypeSoldier"))
        self.assertFalse(generated.get("AllowedTypeVIP"))
        self.assertFalse(generated.get("AllowedTypeDarkVIP"))
        self.assertEqual(generated.get("BackgroundText"), "B" * 2000)
        self.assertIsNone(generated.get("kAppearance"))

    def test_generate_character_rejects_class_for_wrong_template_type(self) -> None:
        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            self.assertRaisesRegex(
                ValueError, "Unsupported soldier_class_template_name"
            ),
        ):
            generate_character(
                "Alex",
                "Kim",
                character_template_name="ReaperSoldier",
                soldier_class_template_name="Ranger",
            )

    def test_generate_characters_does_not_mutate_existing_characters(
        self,
    ) -> None:
        existing = _character("Existing", "Soldier")
        original_existing = existing.to_bytes()

        with (
            patch(
                "xcom2_characterpool_py.pool._load_character_generation_data",
                return_value=_generation_data(),
            ),
            patch(
                "xcom2_characterpool_py.pool.random.choice",
                side_effect=lambda items: items[0],
            ),
        ):
            generated = generate_characters(
                [{"first_name": "New", "last_name": "Person"}],
                existing_characters=[existing],
            )[0]

        self.assertEqual(existing.to_bytes(), original_existing)
        self.assertIsNot(generated, existing)
        self.assertIsNone(generated.get("kAppearance"))


if __name__ == "__main__":
    unittest.main()
