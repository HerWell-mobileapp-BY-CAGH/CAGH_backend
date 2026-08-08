import struct

def compile_po_to_mo(po_filepath, mo_filepath):
    """Simple pure-Python PO to MO compiler for Django gettext catalogs."""
    messages = {}
    with open(po_filepath, 'r', encoding='utf-8') as f:
        msgid = None
        msgstr = None
        for line in f:
            line = line.strip()
            if line.startswith('msgid "'):
                msgid = line[7:-1]
            elif line.startswith('msgstr "') and msgid is not None:
                msgstr = line[8:-1]
                if msgid and msgstr:
                    messages[msgid] = msgstr
                msgid = None

    # Sort keys
    keys = sorted(messages.keys())
    # Header entry
    keys.insert(0, "")
    messages[""] = "Project-Id-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n"

    offsets = []
    ids = b""
    strs = b""

    for k in keys:
        id_bytes = k.encode('utf-8')
        str_bytes = messages[k].encode('utf-8')
        offsets.append((len(ids), len(id_bytes), len(strs), len(str_bytes)))
        ids += id_bytes + b"\x00"
        strs += str_bytes + b"\x00"

    keystart = 7 * 4 + 16 * len(keys)
    valstart = keystart + len(ids)

    koffsets = []
    voffsets = []

    for o1, l1, o2, l2 in offsets:
        koffsets.append((l1, keystart + o1))
        voffsets.append((l2, valstart + o2))

    header = struct.pack(
        "IIIIIII",
        0x950412de,  # Magic
        0,           # Revision
        len(keys),   # Count
        7 * 4,       # Offset of msgids
        7 * 4 + 8 * len(keys),  # Offset of msgstrs
        0,           # Hash table size
        0,           # Hash table offset
    )

    id_table = b"".join(struct.pack("II", l, o) for l, o in koffsets)
    str_table = b"".join(struct.pack("II", l, o) for l, o in voffsets)

    with open(mo_filepath, 'wb') as f:
        f.write(header + id_table + str_table + ids + strs)

    print(f"Successfully compiled {po_filepath} -> {mo_filepath}")


if __name__ == '__main__':
    compile_po_to_mo(
        'c:/Users/hp/Desktop/CAGH_backend/locale/am/LC_MESSAGES/django.po',
        'c:/Users/hp/Desktop/CAGH_backend/locale/am/LC_MESSAGES/django.mo'
    )
