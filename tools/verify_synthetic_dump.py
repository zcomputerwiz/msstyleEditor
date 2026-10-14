#!/usr/bin/env python3
"""
verify_synthetic_dump.py - Verify that msstyleDump output matches the generator's input spec
"""

import json
import sys
import os

def verify(spec_path, dump_path):
    with open(spec_path, "r", encoding="utf-8-sig") as f:
        spec = json.load(f)
    with open(dump_path, "r", encoding="utf-8-sig") as f:
        dump = json.load(f)

    # 1. Image and Stream resources
    spec_images = sorted(spec["images"])
    dump_images = sorted(dump["imageResources"])
    assert spec_images == dump_images, f"Image resources mismatch: {spec_images} vs {dump_images}"

    spec_streams = sorted(spec["streams"])
    dump_streams = sorted(dump["streamResources"])
    assert spec_streams == dump_streams, f"Stream resources mismatch: {spec_streams} vs {dump_streams}"

    # 2. Atlas entries
    assert len(dump["atlasEntries"]) == 2, f"Expected 2 atlas entries, got {len(dump['atlasEntries'])}"
    ae1 = dump["atlasEntries"][0]
    assert ae1["className"] == "Window" and ae1["partId"] == 1 and ae1["stateId"] == 1
    assert ae1["rect"] == {"left": 0, "top": 0, "right": 16, "bottom": 16}
    assert ae1["atlasImageResourceId"] == 1
    assert ae1["atlasInputImage"] == "test_atlas.png"

    ae2 = dump["atlasEntries"][1]
    assert ae2["className"] == "Window" and ae2["partId"] == 1 and ae2["stateId"] == 2
    assert ae2["rect"] == {"left": 16, "top": 0, "right": 32, "bottom": 16}
    assert ae2["atlasImageResourceId"] == 1
    assert ae2["atlasInputImage"] == "test_atlas.png"

    # 3. Flatten dump properties into a lookup table by (classId, partId, stateId, nameId)
    dump_prop_map = {}
    for cls in dump["classes"]:
        cid = cls["classId"]
        for part in cls["parts"]:
            pid = part["partId"]
            for st in part["states"]:
                sid = st["stateId"]
                for p in st["properties"]:
                    nid = p["nameId"]
                    dump_prop_map[(cid, pid, sid, nid)] = p

    # 4. Compare all spec properties
    assert len(spec["properties"]) == dump["numProperties"], f"Count mismatch: spec {len(spec['properties'])} vs dump {dump['numProperties']}"

    for sp in spec["properties"]:
        key = (sp["classId"], sp["partId"], sp["stateId"], sp["nameId"])
        assert key in dump_prop_map, f"Missing property in dump: {sp}"
        dp = dump_prop_map[key]
        assert dp["nameId"] == sp["nameId"]
        assert dp["typeId"] == sp["typeId"]

        # Value comparison
        t = sp["typeId"]
        s_val = sp["value"]
        d_val = dp["value"]

        if t in (200, 241): # ENUM
            assert d_val["value"] == s_val
        elif t in (202, 207): # INT, SIZE
            assert d_val == s_val
        elif t == 203: # BOOL
            assert d_val == s_val
        elif t == 204: # COLOR
            sr, sg, sb = s_val
            assert d_val["r"] == sr and d_val["g"] == sg and d_val["b"] == sb
        elif t == 205: # MARGINS
            # In spec: (l, r, t, b) LRTB
            sl, sr, st, sb = s_val
            assert d_val["cxLeftWidth"] == sl and d_val["cxRightWidth"] == sr
            assert d_val["cyTopHeight"] == st and d_val["cyBottomHeight"] == sb
        elif t == 209: # RECT
            sl, st, sr, sb = s_val
            assert d_val["left"] == sl and d_val["top"] == st
            assert d_val["right"] == sr and d_val["bottom"] == sb
        elif t == 208: # POSITION
            scx, scy = s_val
            assert d_val["cx"] == scx and d_val["cy"] == scy
        elif t == 201: # STRING
            assert d_val == s_val
        elif t == 211: # INTLIST
            assert d_val == s_val
        elif t in (206, 213): # FILENAME, DISKSTREAM
            assert d_val["resourceId"] == s_val

    print(f"VERIFICATION SUCCESS: All {len(spec['properties'])} properties, atlas entries, and image/stream resources match perfectly!")
    return True

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    s_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(script_dir, "synthetic_spec.json")
    d_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(script_dir, "synthetic_dump.json")
    if verify(s_path, d_path):
        sys.exit(0)
    else:
        sys.exit(1)
