import json
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
        restored.declared_size += 20
        pool = Pool([], [Character([restored])])
        json_restored = Pool.from_json(pool.to_json())
        self.assertEqual(json_restored.to_bytes(), pool.to_bytes())

        restored.value[0].value = "Grace"
        rewritten = restored.to_bytes()
        reparsed, offset = Property.read(rewritten, 0)
        self.assertEqual(offset, len(rewritten))
        self.assertEqual(reparsed.value[0].value, "Grace")
        self.assertEqual(reparsed.struct_layout, "tag-first")

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
