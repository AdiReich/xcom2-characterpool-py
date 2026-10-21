from __future__ import annotations

import struct
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


class PoolFormatError(ValueError):
    """Raised when a character-pool binary cannot be parsed safely."""


def _read_i32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise PoolFormatError("Unexpected end of file while reading an integer.")
    value = struct.unpack_from("<i", data, offset)[0]
    if value == -1:
        value = 0
    return value, offset + 4


def _write_i32(value: int) -> bytes:
    return struct.pack("<i", value)


def _decode_string(data: bytes) -> str:
    return data.replace(b"\0", b"").decode("cp1252").replace("\r", "\n")


def _encode_string(value: str | None) -> bytes:
    return (value or "").replace("\r\n", "\r").replace("\n", "\r").encode(
        "cp1252", errors="replace"
    ) + b"\0"


def _pad_string(data: bytes) -> bytes:
    return data + bytes(4)


@dataclass
class Property:
    name: str
    type_name: str
    value: Any = None
    raw_body: bytes | None = field(default=None, repr=False)
    original_value: Any = field(default=None, repr=False)
    struct_tag: str = field(default="TAppearance", repr=False)
    declared_size: int | None = field(default=None, repr=False)
    struct_layout: str = field(default="legacy", repr=False)

    @classmethod
    def read(cls, data: bytes, offset: int) -> tuple[Property | None, int]:
        name_length, offset = _read_i32(data, offset)
        if name_length < 1 or name_length > len(data) - offset:
            raise PoolFormatError("Invalid property name length.")
        name_raw = data[offset : offset + name_length]
        offset += name_length + 4
        if offset > len(data):
            raise PoolFormatError("Unexpected end of file after property name.")
        name = _decode_string(name_raw)
        if name == "None":
            return None, offset

        type_length, offset = _read_i32(data, offset)
        if type_length < 1 or type_length > len(data) - offset:
            raise PoolFormatError(f"Invalid type name length for {name!r}.")
        type_name = _decode_string(data[offset : offset + type_length])
        offset += type_length + 4
        data_length, offset = _read_i32(data, offset)
        offset += 4
        if offset > len(data):
            raise PoolFormatError(f"Unexpected end of file before {name!r} data.")

        if type_name in ("IntProperty", "ArrayProperty"):
            if offset + 4 > len(data):
                raise PoolFormatError(f"Unexpected end of file in {name!r}.")
            raw_body = data[offset : offset + 4]
            value = struct.unpack("<i", raw_body)[0]
            offset += 4
        elif type_name == "BoolProperty":
            legacy_bool = data[offset : offset + 4] == bytes(4)
            body_length = 5 if legacy_bool else 1
            if offset + body_length > len(data):
                raise PoolFormatError(f"Unexpected end of file in {name!r}.")
            raw_body = data[offset : offset + body_length]
            value = raw_body[-1:] != b"\0"
            offset += body_length
        elif type_name in ("StrProperty", "NameProperty"):
            body_length = data_length
            if body_length < 4 or offset + body_length > len(data):
                raise PoolFormatError(f"Invalid string data length for {name!r}.")
            raw_body = data[offset : offset + body_length]
            string_length = struct.unpack_from("<i", raw_body)[0]
            if string_length < 0:
                string_byte_length = -string_length * 2
                if string_byte_length > len(raw_body) - 4:
                    raise PoolFormatError(f"Invalid string length for {name!r}.")
                value = (
                    raw_body[4 : 4 + string_byte_length]
                    .decode("utf-16-le")
                    .rstrip("\0")
                    .replace("\r", "\n")
                )
            elif string_length > len(raw_body) - 4:
                raise PoolFormatError(f"Invalid string length for {name!r}.")
            else:
                value = _decode_string(raw_body[4 : 4 + string_length])
            offset += body_length
        elif type_name == "StructProperty":
            start = offset
            if offset + 8 > len(data):
                raise PoolFormatError(f"Unexpected end of file in {name!r}.")
            tag_first = data[offset + 4 : offset + 8] != bytes(4)
            if tag_first:
                tag_length, offset = _read_i32(data, offset)
                children_length = data_length
                struct_layout = "tag-first"
            else:
                children_length, offset = _read_i32(data, offset)
                offset += 4
                tag_length, offset = _read_i32(data, offset)
                struct_layout = "legacy"
            if tag_length < 1 or tag_length > len(data) - offset:
                raise PoolFormatError(f"Invalid struct tag length for {name!r}.")
            tag = _decode_string(data[offset : offset + tag_length])
            offset += tag_length + 4
            children: list[Property] = []
            while True:
                child, offset = cls.read(data, offset)
                if child is None:
                    break
                children.append(child)
            raw_body = data[start:offset]
            return cls(
                name,
                type_name,
                children,
                raw_body,
                deepcopy(children),
                tag,
                children_length,
                struct_layout,
            ), offset
        else:
            if data_length < 0 or offset + data_length > len(data):
                raise PoolFormatError(
                    f"Unsupported property type {type_name!r} has invalid size."
                )
            raw_body = data[offset : offset + data_length]
            value = raw_body.hex()
            offset += data_length

        result = cls(name, type_name, value, raw_body, value)
        return result, offset

    def to_bytes(self) -> bytes:
        name_bytes = _encode_string(self.name)
        result = bytearray(_write_i32(len(name_bytes)))
        result.extend(_pad_string(name_bytes))

        type_bytes = _encode_string(self.type_name)
        result.extend(_write_i32(len(type_bytes)))
        result.extend(_pad_string(type_bytes))

        if self.type_name in ("IntProperty", "ArrayProperty"):
            body = _write_i32(int(self.value))
            data_length = 4
        elif self.type_name == "BoolProperty":
            if self.raw_body is not None and self.value == self.original_value:
                body = self.raw_body
            elif self.raw_body is not None and len(self.raw_body) == 1:
                body = b"\1" if self.value else b"\0"
            else:
                body = bytes(4) + (b"\1" if self.value else b"\0")
            data_length = 0
        elif self.type_name in ("StrProperty", "NameProperty"):
            if self.raw_body is not None and self.value == self.original_value:
                body = self.raw_body
            else:
                text = _encode_string(self.value)
                body = _write_i32(len(text)) + text
                if self.type_name == "NameProperty":
                    body += bytes(4)
            data_length = len(body)
        elif self.type_name == "StructProperty":
            if self.raw_body is not None and self.value == self.original_value:
                body = self.raw_body
                children_length = self.declared_size
            else:
                children = b"".join(child.to_bytes() for child in self.value)
                children += _none_property()
                tag = _encode_string(self.struct_tag)
                if self.struct_layout == "tag-first":
                    body = _write_i32(len(tag)) + tag + bytes(4) + children
                    children_length = (
                        self.declared_size
                        if self.value == self.original_value
                        and self.declared_size is not None
                        else len(body)
                    )
                else:
                    children_length = (
                        self.declared_size
                        if self.value == self.original_value
                        and self.declared_size is not None
                        else len(children)
                    )
                    body = (
                        _write_i32(children_length)
                        + bytes(4)
                        + _write_i32(len(tag))
                        + tag
                        + bytes(4)
                        + children
                    )
            data_length = children_length
        else:
            body = (
                bytes.fromhex(self.value)
                if isinstance(self.value, str)
                else bytes(self.value)
            )
            data_length = len(body)

        result.extend(_write_i32(data_length))
        result.extend(bytes(4))
        result.extend(body)
        return bytes(result)

    def to_dict(self) -> dict[str, Any]:
        value = (
            [item.to_dict() for item in self.value]
            if self.type_name == "StructProperty"
            else self.value
        )
        result = {"name": self.name, "type": self.type_name, "value": value}
        if self.type_name == "StructProperty":
            result["struct_tag"] = self.struct_tag
            result["struct_layout"] = self.struct_layout
            result["declared_size"] = self.declared_size
        elif self.raw_body is not None:
            result["raw_body"] = self.raw_body.hex()
            result["raw_value"] = deepcopy(self.original_value)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Property:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("name"), str)
            or not isinstance(value.get("type"), str)
        ):
            raise PoolFormatError(
                "Each property must have string 'name' and 'type' fields."
            )
        prop_value = value.get("value")
        if value["type"] == "StructProperty":
            if not isinstance(prop_value, list):
                raise PoolFormatError(
                    f"Struct property {value['name']!r} must contain a property list."
                )
            prop_value = [cls.from_dict(item) for item in prop_value]
        try:
            raw_body = bytes.fromhex(value["raw_body"]) if "raw_body" in value else None
        except (TypeError, ValueError) as exc:
            raise PoolFormatError(
                f"Property {value['name']!r} has invalid raw_body data."
            ) from exc
        declared_size = value.get("declared_size")
        if declared_size is not None and (
            not isinstance(declared_size, int) or isinstance(declared_size, bool)
        ):
            raise PoolFormatError(
                f"Property {value['name']!r} has an invalid declared_size."
            )
        return cls(
            value["name"],
            value["type"],
            prop_value,
            raw_body=raw_body,
            original_value=deepcopy(value.get("raw_value", prop_value)),
            struct_tag=value.get("struct_tag", "TAppearance"),
            declared_size=declared_size,
            struct_layout=value.get("struct_layout", "legacy"),
        )


def _none_property() -> bytes:
    name = _encode_string("None")
    return _write_i32(len(name)) + _pad_string(name)


def read_properties(data: bytes, offset: int) -> tuple[list[Property], int]:
    properties: list[Property] = []
    while True:
        prop, offset = Property.read(data, offset)
        if prop is None:
            return properties, offset
        properties.append(prop)


def write_properties(properties: list[Property]) -> bytes:
    return b"".join(prop.to_bytes() for prop in properties) + _none_property()
