import json
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from xcom2_characterpool_py.cli import _character, main
from xcom2_characterpool_py.format import Property
from xcom2_characterpool_py.pool import Character, Pool, read_pool


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
            path.write_bytes(pool.to_bytes())
            restored = read_pool(path)
            self.assertEqual(restored.to_bytes(), path.read_bytes())

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

        restored = Pool.from_json(pool.to_json())

        self.assertEqual(restored.to_bytes(), pool.to_bytes())
        restored.characters[0].properties[0].value[0].value = False
        self.assertNotEqual(restored.to_bytes(), pool.to_bytes())

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
        json_restored = Pool.from_json(pool.to_json())
        self.assertEqual(json_restored.to_bytes(), pool.to_bytes())

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

    def test_add_uses_random_template_and_forces_soldier_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            target = Path(directory) / "target.bin"
            source_pool = self.make_pool()
            source.write_bytes(source_pool.to_bytes())
            template = _character("", "")
            template.get("kAppearance")[1].value = 0
            for name in (
                "AllowedTypeSoldier",
                "AllowedTypeVIP",
                "AllowedTypeDarkVIP",
            ):
                prop = next(prop for prop in template.properties if prop.name == name)
                prop.value = False
                prop.raw_body = b"\0"
                prop.original_value = False
            next(
                prop
                for prop in template.properties
                if prop.name == "CharacterTemplateName"
            ).value = "ReaperSoldier"
            unused_template = _character("", "")
            unused_template.get("kAppearance")[1].value = 1

            with patch(
                "xcom2_characterpool_py.cli._load_character_templates",
                return_value=[template, unused_template],
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
            added = updated_pool.characters[-1]
            self.assertEqual(added.get("strFirstName"), "Alex")
            self.assertEqual(added.get("strLastName"), "Kim")
            self.assertEqual(added.get("strNickName"), "'Viper'")
            self.assertTrue(added.get("PoolTimestamp"))
            self.assertEqual(added.get("CharacterTemplateName"), "Soldier")
            self.assertTrue(added.get("AllowedTypeSoldier"))
            self.assertTrue(added.get("AllowedTypeVIP"))
            self.assertTrue(added.get("AllowedTypeDarkVIP"))
            self.assertEqual(added.get("kAppearance")[1].value, 0)
            for name in (
                "AllowedTypeSoldier",
                "AllowedTypeVIP",
                "AllowedTypeDarkVIP",
            ):
                prop = next(prop for prop in added.properties if prop.name == name)
                self.assertEqual(prop.raw_body, b"\1")
            self.assertEqual(
                updated_pool.characters[0].to_bytes(),
                source_pool.characters[0].to_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
