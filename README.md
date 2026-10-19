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

`add` randomly selects a Soldier template from the bundled `Templates/New Character.txt` records, based on the supplied character pools. It applies the requested name and always sets the character type and Soldier/VIP/Dark VIP eligibility flags.

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