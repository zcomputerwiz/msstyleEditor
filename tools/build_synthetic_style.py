#!/usr/bin/env python3
"""
build_synthetic_style.py - Generate synthetic minimal Vista/11 format .msstyles PE file
using only synthetic open resources (no Microsoft files).

Generates:
- CMAP resource
- VARIANT (NORMAL) property stream testing INT, BOOL, COLOR, MARGINS, RECT, POSITION,
  STRING, ENUM, INTLIST, FILENAME, DISKSTREAM, ATLASRECT.
- IMAGE PNG resources (at 96, 120, 144 DPI)
- STREAM atlas PNG resource
"""

import os
import struct
import sys
import zlib
import json

def make_png(width, height, get_pixel_func):
    """Generate minimal valid PNG with RGBA pixels"""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter None
        for x in range(width):
            r, g, b, a = get_pixel_func(x, y)
            raw.extend((r, g, b, a))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

def make_property(name_id, type_id, class_id, part_id, state_id, val):
    """
    Format a 32-byte PropertyHeader + 8-byte aligned data payload per libmsstyle spec:
    Header: nameID(4), typeID(4), classID(4), partID(4), stateID(4), shortFlag(4), reserved(4), sizeInBytes(4)
    """
    short_flag = 0
    payload = b""

    # IDENTIFIER enum values
    # ENUM=200, STRING=201, INT=202, BOOL=203, COLOR=204, MARGINS=205, FILENAME=206,
    # SIZE=207, POSITION=208, RECT=209, FONT=210, INTLIST=211, DISKSTREAM=213, HIGHCONTRAST=241

    if type_id in (206, 213, 210): # FILENAME, DISKSTREAM, FONT
        short_flag = int(val)
        size_in_bytes = 0
    elif type_id in (200, 202, 207, 241): # ENUM, INT, SIZE, HIGHCONTRAST
        payload = struct.pack("<i", int(val))
        size_in_bytes = 4
    elif type_id == 203: # BOOL
        payload = struct.pack("<i", 1 if val else 0)
        size_in_bytes = 4
    elif type_id == 204: # COLOR: (r, g, b) -> 4 bytes [r, g, b, 0]
        r, g, b = val
        payload = struct.pack("<BBBB", r, g, b, 0)
        size_in_bytes = 4
    elif type_id == 205: # MARGINS: left, right, top, bottom (uxtheme LRTB format in stream)
        l, r, t, b = val
        payload = struct.pack("<iiii", l, r, t, b)
        size_in_bytes = 16
    elif type_id == 209: # RECT: left, top, right, bottom (LTRB format)
        l, t, r, b = val
        payload = struct.pack("<iiii", l, t, r, b)
        size_in_bytes = 16
    elif type_id == 208: # POSITION: cx, cy
        cx, cy = val
        payload = struct.pack("<ii", cx, cy)
        size_in_bytes = 8
    elif type_id == 201: # STRING: UTF-16LE + null
        encoded = (str(val) + "\0").encode("utf-16le")
        payload = encoded
        size_in_bytes = len(encoded)
    elif type_id == 211: # INTLIST: count(4) + ints
        ints = list(val)
        payload = struct.pack("<i", len(ints)) + b"".join(struct.pack("<i", x) for x in ints)
        size_in_bytes = len(payload)
    else:
        raise ValueError(f"Unsupported type_id {type_id}")

    # Pad payload to multiple of 8 bytes
    if len(payload) % 8 != 0:
        payload += b"\x00" * (8 - (len(payload) % 8))

    header = struct.pack("<iiiiiiii", name_id, type_id, class_id, part_id, state_id, short_flag, 0, size_in_bytes)
    return header + payload

class PEResourceBuilder:
    def __init__(self):
        # resources: list of (type_id_or_name, name_id_or_name, lang_id, data_bytes)
        self.resources = []

    def add_resource(self, type_val, name_val, lang_id, data):
        self.resources.append((type_val, name_val, lang_id, data))

    def build_pe_dll(self):
        """Build a valid 32-bit PE DLL containing .rsrc section"""
        # 1. Structure resource tree
        # Tree: Type -> Name -> Lang -> Data
        types = {}
        for r_type, r_name, r_lang, r_data in self.resources:
            types.setdefault(r_type, {}).setdefault(r_name, {})[r_lang] = r_data

        # We need to layout:
        # - Resource Directory Tables
        # - Resource Directory Entries
        # - Resource Directory Strings (for named types/names)
        # - Resource Data Entries
        # - Actual resource data bytes

        # Let's organize two phases: metadata and data
        rsrc_strings = bytearray()
        string_offsets = {}

        def get_string_offset(s):
            if s in string_offsets:
                return string_offsets[s]
            offset = len(rsrc_strings)
            string_offsets[s] = offset
            encoded = s.encode("utf-16le")
            rsrc_strings.extend(struct.pack("<H", len(s)) + encoded)
            return offset

        # Separate named and ID entries helper
        def split_entries(keys):
            named = [k for k in keys if isinstance(k, str)]
            ids = [k for k in keys if isinstance(k, int)]
            named.sort(key=lambda s: s.upper())
            ids.sort()
            return named, ids

        # Pass 1: compute table structures
        # Structure sizes:
        # Table header: 16 bytes (IMAGE_RESOURCE_DIRECTORY)
        # Entry: 8 bytes (IMAGE_RESOURCE_DIRECTORY_ENTRY)
        # Data entry: 16 bytes (IMAGE_RESOURCE_DATA_ENTRY)

        type_named, type_ids = split_entries(types.keys())
        root_entries_count = len(type_named) + len(type_ids)
        root_dir_size = 16 + root_entries_count * 8

        # For each type: table header (16) + entries count * 8
        type_tables = {}
        curr_offset = root_dir_size

        for t in type_named + type_ids:
            names = types[t]
            n_named, n_ids = split_entries(names.keys())
            t_size = 16 + (len(n_named) + len(n_ids)) * 8
            type_tables[t] = (curr_offset, t_size)
            curr_offset += t_size

        # For each name in each type: table header (16) + lang entries count * 8
        name_tables = {}
        for t in type_named + type_ids:
            names = types[t]
            n_named, n_ids = split_entries(names.keys())
            for n in n_named + n_ids:
                langs = names[n]
                l_named, l_ids = split_entries(langs.keys())
                n_size = 16 + (len(l_named) + len(l_ids)) * 8
                name_tables[(t, n)] = (curr_offset, n_size)
                curr_offset += n_size

        # Data entries: for each lang, 16 bytes
        data_entry_records = {}
        for t in type_named + type_ids:
            for n in types[t]:
                for l in types[t][n]:
                    data_entry_records[(t, n, l)] = curr_offset
                    curr_offset += 16

        # Strings table offset
        strings_base_offset = curr_offset
        # Precompute string offsets
        for t in type_named:
            get_string_offset(t)
        for t in types:
            for n in types[t]:
                if isinstance(n, str):
                    get_string_offset(n)

        # Pad strings to 4-byte alignment
        while (len(rsrc_strings) % 4) != 0:
            rsrc_strings.append(0)

        data_blob_base_offset = strings_base_offset + len(rsrc_strings)
        # Align data blob base to 8 bytes
        if data_blob_base_offset % 8 != 0:
            pad = 8 - (data_blob_base_offset % 8)
            rsrc_strings.extend(b"\x00" * pad)
            data_blob_base_offset += pad

        # Layout actual resource data
        res_data_blob = bytearray()
        res_data_offsets = {}
        for t in type_named + type_ids:
            for n in types[t]:
                for l in types[t][n]:
                    blob = types[t][n][l]
                    offset_in_blob = len(res_data_blob)
                    res_data_offsets[(t, n, l)] = data_blob_base_offset + offset_in_blob
                    res_data_blob.extend(blob)
                    # Align to 8 bytes
                    while len(res_data_blob) % 8 != 0:
                        res_data_blob.append(0)

        # Now build the full .rsrc byte array
        rsrc_bytes = bytearray(curr_offset)

        def write_dir(offset, named_keys, id_keys):
            struct.pack_into("<IIHHHH", rsrc_bytes, offset, 0, 0, 0, 0, len(named_keys), len(id_keys))

        # Root directory
        write_dir(0, type_named, type_ids)
        e_idx = 0
        for t in type_named + type_ids:
            entry_offset = 16 + e_idx * 8
            sub_offset = type_tables[t][0] | 0x80000000
            if isinstance(t, str):
                name_ref = (strings_base_offset + string_offsets[t]) | 0x80000000
            else:
                name_ref = t
            struct.pack_into("<II", rsrc_bytes, entry_offset, name_ref, sub_offset)
            e_idx += 1

        # Type directories
        for t in type_named + type_ids:
            t_offset, _ = type_tables[t]
            names = types[t]
            n_named, n_ids = split_entries(names.keys())
            write_dir(t_offset, n_named, n_ids)
            ne_idx = 0
            for n in n_named + n_ids:
                entry_offset = t_offset + 16 + ne_idx * 8
                sub_offset = name_tables[(t, n)][0] | 0x80000000
                if isinstance(n, str):
                    name_ref = (strings_base_offset + string_offsets[n]) | 0x80000000
                else:
                    name_ref = n
                struct.pack_into("<II", rsrc_bytes, entry_offset, name_ref, sub_offset)
                ne_idx += 1

        # Name directories
        for (t, n), (n_offset, _) in name_tables.items():
            langs = types[t][n]
            l_named, l_ids = split_entries(langs.keys())
            write_dir(n_offset, l_named, l_ids)
            le_idx = 0
            for l in l_named + l_ids:
                entry_offset = n_offset + 16 + le_idx * 8
                de_offset = data_entry_records[(t, n, l)] # High bit 0 -> data entry
                name_ref = l
                struct.pack_into("<II", rsrc_bytes, entry_offset, name_ref, de_offset)
                le_idx += 1

        # Data entries
        rsrc_rva_base = 0x1000
        for (t, n, l), de_offset in data_entry_records.items():
            data_rva = rsrc_rva_base + res_data_offsets[(t, n, l)]
            data_size = len(types[t][n][l])
            struct.pack_into("<IIII", rsrc_bytes, de_offset, data_rva, data_size, 0, 0)

        # Assemble total .rsrc content
        rsrc_total = rsrc_bytes + rsrc_strings + res_data_blob
        virtual_size = len(rsrc_total)
        raw_size = (virtual_size + 0x1FF) & ~0x1FF

        # Construct PE headers
        # DOS Header
        dos_hdr = bytearray(0x80)
        dos_hdr[0:2] = b"MZ"
        struct.pack_into("<I", dos_hdr, 0x3C, 0x80)

        # PE Signature
        pe_sig = b"PE\0\0"

        # COFF File Header (20 bytes)
        # Machine=0x14c (i386), NumberOfSections=1, TimeDateStamp=0, PtrSymbols=0, NumSymbols=0, OptHdrSize=224, Characteristics=0x2102 (DLL, 32BIT, EXEC)
        coff_hdr = struct.pack("<HHIIIHH", 0x014c, 1, 0, 0, 0, 224, 0x2102)

        # Optional Header (224 bytes)
        image_size = (0x1000 + virtual_size + 0xFFF) & ~0xFFF
        opt_hdr = struct.pack(
            "<HBBIIIIIIIIIHHHHHHIIIIHHIIIIII",
            0x010B,          # Magic (PE32)
            14, 0,           # Linker version
            0,               # SizeOfCode
            raw_size,        # SizeOfInitializedData
            0,               # SizeOfUninitializedData
            0,               # AddressOfEntryPoint
            0x1000,          # BaseOfCode
            0x1000,          # BaseOfData
            0x10000000,      # ImageBase
            0x1000,          # SectionAlignment
            0x200,           # FileAlignment
            6, 0,            # OS version
            0, 0,            # Image version
            6, 0,            # Subsystem version
            0,               # Win32VersionValue
            image_size,      # SizeOfImage
            0x200,           # SizeOfHeaders
            0,               # CheckSum
            2,               # Subsystem (Windows GUI)
            0x0140,          # DllCharacteristics (DYNAMIC_BASE | NX_COMPAT)
            0x100000,        # SizeOfStackReserve
            0x1000,          # SizeOfStackCommit
            0x100000,        # SizeOfHeapReserve
            0x1000,          # SizeOfHeapCommit
            0,               # LoaderFlags
            16               # NumberOfRvaAndSizes
        )
        # Data directories (16 entries of 8 bytes: RVA, Size)
        data_dirs = bytearray(128)
        # Entry 2: Resource Table
        struct.pack_into("<II", data_dirs, 2 * 8, 0x1000, virtual_size)

        # Section Header (.rsrc, 40 bytes)
        # Name(8), VirtualSize(4), VirtualAddress(4), SizeOfRawData(4), PointerToRawData(4), ... Characteristics(4)
        sec_hdr = struct.pack(
            "<8sIIIIIIHHI",
            b".rsrc\0\0\0",
            virtual_size,
            0x1000,
            raw_size,
            0x200,           # File offset
            0, 0, 0, 0,
            0x40000040       # IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ
        )

        headers = dos_hdr + pe_sig + coff_hdr + opt_hdr + data_dirs + sec_hdr
        assert len(headers) <= 0x200
        headers += b"\x00" * (0x200 - len(headers))

        # Pad rsrc to raw_size
        rsrc_padded = rsrc_total + b"\x00" * (raw_size - len(rsrc_total))
        return headers + rsrc_padded

def generate_synthetic_style(out_dll_path, out_json_spec_path):
    builder = PEResourceBuilder()

    # 1. CMAP resource: class names
    classes = ["Button", "Window", "Edit", "ScrollBar", "DarkMode::TaskManager"]
    cmap_str = "\0".join(classes) + "\0\0"
    cmap_bytes = cmap_str.encode("utf-16le")
    builder.add_resource("CMAP", "CMAP", 1033, cmap_bytes)

    # 2. VARIANT "NORMAL" resource: property stream
    props_data = bytearray()
    spec_props = []

    def add_prop(name_id, prop_name, type_id, type_name, class_id, part_id, state_id, val):
        p_bytes = make_property(name_id, type_id, class_id, part_id, state_id, val)
        props_data.extend(p_bytes)
        spec_props.append({
            "nameId": name_id,
            "name": prop_name,
            "typeId": type_id,
            "typeName": type_name,
            "classId": class_id,
            "className": classes[class_id],
            "partId": part_id,
            "stateId": state_id,
            "value": val
        })

    # Class 0: Button
    # Part 1: PUSHBUTTON, State 0 (Common)
    add_prop(4001, "BGTYPE", 200, "ENUM", 0, 1, 0, 0) # IMAGEFILE
    add_prop(4004, "SIZINGTYPE", 200, "ENUM", 0, 1, 0, 1) # STRETCH
    add_prop(2403, "BORDERSIZE", 202, "INT", 0, 1, 0, 2)
    add_prop(2201, "TRANSPARENT", 203, "BOOL", 0, 1, 0, True)
    add_prop(3801, "BORDERCOLOR", 204, "COLOR", 0, 1, 0, (10, 20, 30))
    add_prop(3802, "FILLCOLOR", 204, "COLOR", 0, 1, 0, (240, 240, 240))
    add_prop(3803, "TEXTCOLOR", 204, "COLOR", 0, 1, 0, (0, 0, 0))
    add_prop(3601, "SIZINGMARGINS", 205, "MARGINS", 0, 1, 0, (4, 4, 4, 4))
    add_prop(3602, "CONTENTMARGINS", 205, "MARGINS", 0, 1, 0, (2, 2, 2, 2))
    add_prop(3401, "OFFSET", 208, "POSITION", 0, 1, 0, (1, 1))
    add_prop(6000, "TRANSITIONDURATIONS", 211, "INTLIST", 0, 1, 0, [100, 200, 300])
    add_prop(3001, "IMAGEFILE", 206, "FILENAME", 0, 1, 0, 101) # IMAGE 101 (96 DPI)
    add_prop(3002, "IMAGEFILE1", 206, "FILENAME", 0, 1, 0, 104) # IMAGE 104 (120 DPI)
    add_prop(3003, "IMAGEFILE2", 206, "FILENAME", 0, 1, 0, 105) # IMAGE 105 (144 DPI)
    add_prop(4012, "IMAGESELECTTYPE", 200, "ENUM", 0, 1, 0, 2) # DPI
    add_prop(4014, "TRUESIZESCALINGTYPE", 200, "ENUM", 0, 1, 0, 1) # DPI

    # Part 1: PUSHBUTTON, State 1 (NORMAL)
    add_prop(3801, "BORDERCOLOR", 204, "COLOR", 0, 1, 1, (50, 60, 70))
    add_prop(3001, "IMAGEFILE", 206, "FILENAME", 0, 1, 1, 101)

    # Part 1: PUSHBUTTON, State 2 (HOT)
    add_prop(3801, "BORDERCOLOR", 204, "COLOR", 0, 1, 2, (255, 128, 0))
    add_prop(3001, "IMAGEFILE", 206, "FILENAME", 0, 1, 2, 102)

    # Part 1: PUSHBUTTON, State 3 (PRESSED)
    add_prop(3801, "BORDERCOLOR", 204, "COLOR", 0, 1, 3, (0, 128, 255))
    add_prop(3001, "IMAGEFILE", 206, "FILENAME", 0, 1, 3, 103)

    # Class 1: Window
    # Part 1: WP_CAPTION, State 1 (FS_ACTIVE)
    add_prop(8000, "ATLASIMAGE", 213, "DISKSTREAM", 1, 1, 1, 1) # STREAM 1
    add_prop(8001, "ATLASINPUTIMAGE", 201, "STRING", 1, 1, 1, "test_atlas.png")
    add_prop(8002, "ATLASRECT", 209, "RECT", 1, 1, 1, (0, 0, 16, 16))

    # Part 1: WP_CAPTION, State 2 (FS_INACTIVE)
    add_prop(8000, "ATLASIMAGE", 213, "DISKSTREAM", 1, 1, 2, 1) # STREAM 1
    add_prop(8001, "ATLASINPUTIMAGE", 201, "STRING", 1, 1, 2, "test_atlas.png")
    add_prop(8002, "ATLASRECT", 209, "RECT", 1, 1, 2, (16, 0, 32, 16))

    builder.add_resource("VARIANT", "NORMAL", 1033, bytes(props_data))

    # 3. IMAGE PNG resources
    # 101: 16x16 blue button
    png_101 = make_png(16, 16, lambda x, y: (30, 100, 200, 255) if (x==0 or y==0 or x==15 or y==15) else (100, 160, 240, 255))
    builder.add_resource("IMAGE", 101, 1033, png_101)

    # 102: 16x16 hot button (orange)
    png_102 = make_png(16, 16, lambda x, y: (255, 128, 0, 255) if (x==0 or y==0 or x==15 or y==15) else (255, 200, 100, 255))
    builder.add_resource("IMAGE", 102, 1033, png_102)

    # 103: 16x16 pressed button (dark blue)
    png_103 = make_png(16, 16, lambda x, y: (10, 50, 120, 255) if (x==0 or y==0 or x==15 or y==15) else (50, 90, 160, 255))
    builder.add_resource("IMAGE", 103, 1033, png_103)

    # 104: 20x20 button (120 DPI)
    png_104 = make_png(20, 20, lambda x, y: (30, 100, 200, 255) if (x==0 or y==0 or x==19 or y==19) else (120, 180, 250, 255))
    builder.add_resource("IMAGE", 104, 1033, png_104)

    # 105: 24x24 button (144 DPI)
    png_105 = make_png(24, 24, lambda x, y: (30, 100, 200, 255) if (x==0 or y==0 or x==23 or y==23) else (140, 200, 255, 255))
    builder.add_resource("IMAGE", 105, 1033, png_105)

    # 4. STREAM atlas resource: 32x16 PNG containing two 16x16 tiles
    # Left tile (0..15): Green (0, 180, 50)
    # Right tile (16..31): Gray (180, 180, 180)
    def atlas_pixel(x, y):
        if x < 16:
            border = (x == 0 or x == 15 or y == 0 or y == 15)
            return (0, 120, 30, 255) if border else (50, 200, 80, 255)
        else:
            border = (x == 16 or x == 31 or y == 0 or y == 15)
            return (100, 100, 100, 255) if border else (190, 190, 190, 255)

    stream_png = make_png(32, 16, atlas_pixel)
    builder.add_resource("STREAM", 1, 1033, stream_png)

    # 5. AMAP resource (empty animation map for Win8+)
    builder.add_resource("AMAP", "AMAP", 1033, b"")

    pe_bytes = builder.build_pe_dll()

    os.makedirs(os.path.dirname(os.path.abspath(out_dll_path)), exist_ok=True)
    with open(out_dll_path, "wb") as f:
        f.write(pe_bytes)

    # Write spec JSON
    spec = {
        "classes": classes,
        "properties": spec_props,
        "images": [101, 102, 103, 104, 105],
        "streams": [1]
    }
    with open(out_json_spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    print(f"Generated synthetic style: {out_dll_path} ({len(pe_bytes)} bytes, {len(spec_props)} properties)")
    print(f"Generated spec JSON: {out_json_spec_path}")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_dll = sys.argv[1] if len(sys.argv) > 1 else os.path.join(script_dir, "synthetic.msstyles")
    out_spec = sys.argv[2] if len(sys.argv) > 2 else os.path.join(script_dir, "synthetic_spec.json")

    generate_synthetic_style(out_dll, out_spec)

if __name__ == "__main__":
    main()
