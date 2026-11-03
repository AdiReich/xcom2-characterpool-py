# XCOM2 CharacterPool for Python

A Python command-line utility for inspecting, creating, editing, and merging XCOM 2 character pools. The original template, palette, and localization data is bundled with the package.

## Requirements

Python 3.10 or later. The application has no third-party runtime dependencies.

Run from the repository root:

```powershell
python -m xcom2_characterpool_py --help
```

Or install the command locally:

```powershell
python -m pip install .
xcom2-characterpool --help
```

## Commands

```powershell
# Show pool contents
python -m xcom2_characterpool_py inspect .\soldiers.bin

# Show every property for character index 0
python -m xcom2_characterpool_py inspect-character .\soldiers.bin --index 0

# Create a pool with a starter soldier (use --empty for an empty pool)
python -m xcom2_characterpool_py new .\new-pool.bin --first-name Jane --last-name Doe --nickname Viper

# Add a randomized soldier or edit fields by zero-based index
python -m xcom2_characterpool_py add .\new-pool.bin -o .\updated.bin --first-name Alex --last-name Kim
python -m xcom2_characterpool_py set .\updated.bin -o .\edited.bin --index 0 --property strFirstName=Jane --property nmHaircut=Hair_Template

# Remove one or more zero-based character indexes
python -m xcom2_characterpool_py delete .\edited.bin -o .\trimmed.bin --index 1 --index 3

# Merge pools; duplicate characters are skipped
python -m xcom2_characterpool_py merge .\pool-a.bin .\pool-b.bin -o .\merged.bin

# Export all known and unknown properties for complete manual editing
python -m xcom2_characterpool_py export-json .\merged.bin -o .\pool.json
python -m xcom2_characterpool_py import-json .\pool.json -o .\edited-pool.bin

# Browse bundled templates
python -m xcom2_characterpool_py templates --search Kevlar --part-type Torso
```

`set` accepts any character property name; appearance fields are found recursively by property name. Integer and boolean properties are converted to the correct binary value type. The JSON format preserves nested and currently unknown properties. Edit the exported JSON without removing the `format`, `header_properties`, or `characters` fields.

Binary pools and JSON imports larger than 64 MiB are rejected. Strict mode is enabled by default for pool reads, writes, JSON imports, and character generation. Binary and JSON data use the same validation rules, configured in `xcom2_characterpool_py/data/Files/Templates/Character Pool Strict Rules.json`. The allowlist is based on properties observed in the local WotC Importable pools. Strict mode limits struct nesting to 2 levels, `IntProperty` values to -1 through 200, and string properties to the following rules:

- Most `StrProperty` and `NameProperty` values are limited to 50 characters and ASCII letters, digits, or underscores.
- First name, last name, nickname, and timestamp values may contain printable characters and are limited to 50 characters.
- `BackgroundText` may contain printable characters and line breaks and is limited to 2,000 characters.
- `PoolFileName` is limited to 100 characters and must be a relative path or filename ending in `.bin`, or the exact placeholder `Unsaved Pool`.

Strict mode also checks property types, boolean values and encodings, struct layouts, and property names. Existing pools with mod-specific properties or values outside these rules may fail strict validation. Pass `--no-strict` to a pool command, or `strict=False` to the Python read/write/generation APIs, to use permissive behavior.

`add` generates a Soldier with a random country and background from the extracted generation data, applies the requested name, and omits appearance data so the game can generate it. Rules are stored in `data/Files/Templates/Character Generation Rules.json`; country and background pools are in `data/Files/Templates/Character Generation Data.json`.

## Character Order

When writing a pool, the utility places characters without a `kAppearance` property at the beginning. XCOM 2 needs these characters first in the pool to generate their appearances randomly; otherwise, their appearance may remain static. This ordering also applies to merged pools. The relative order within the appearance-less and appearance-defined groups is preserved, so the written order may differ from the input order.

Python applications can generate the same randomized soldier directly:

```python
from xcom2_characterpool_py import generate_character

soldier = generate_character("Jane", "Doe", nickname="Viper")
```

Pass `biography` or `background_text` to set the soldier's background text; if omitted, a background is randomly selected from the extracted data. Optional `character_template_name`, `soldier_class_template_name`, and `country` arguments are checked against the bundled generation rules. Names and background text longer than XCOM's supported limits are truncated. `existing_characters` remains accepted for compatibility; generated records omit appearances for the game to create.

For batches, use `generate_characters()` with an iterable of request mappings. Each mapping requires `first_name` and `last_name`, and may include `nickname`, `character_template_name`, `soldier_class_template_name`, `country`, and `background_text` (or `biography`):

```python
from xcom2_characterpool_py import generate_characters

soldiers = generate_characters(
    [
        {"first_name": "Jane", "last_name": "Doe", "nickname": "Viper"},
        {
            "first_name": "Alex",
            "last_name": "Kim",
            "character_template_name": "ReaperSoldier",
            "soldier_class_template_name": "Reaper",
        },
    ],
    existing_characters=saved_characters,
)
```

For XCOM 2 to load a pool, place the resulting `.bin` file in the game's `CharacterPool/Importable` directory. Common locations are:

- `Documents\My Games\XCOM2\XComGame\CharacterPool\Importable`
- `Documents\My Games\XCOM2 War of the Chosen\XComGame\CharacterPool\Importable`

## Development

Run the test suite with:

```powershell
python -m unittest discover -s tests -v
```

## Credits / Acknowledgments

This project is a complete Python rewrite of the original [XCOM2CharacterPoolUtility](https://github.com/Shaosil/XCOM2CharacterPoolUtility) created by [@Shaosil](https://github.com/Shaosil). 
The entire codebase has been translated and reconstructed in Python with the assistance of AI (GitHub Copilot) to optimize code structure and implementation.