"""Write the self-test PDF fixture as a minimal hand-built PDF.

The file carries one page of text and all four document properties so
that the lint's PDF reader is exercised on both. Re-run this script only
if the fixture must change; the output is committed.
"""
import sys

TEXT = "We leverage the workshops."
INFO = {
    "Title": "Key findings",
    "Subject": "Leverage for growth",
    "Author": "Housestyle Fixtures",
    "Keywords": "workshops, sessions",
}


def build() -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({TEXT}) Tj ET".encode("latin-1")
    info = " ".join(f"/{k} ({v})" for k, v in INFO.items())
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< " + info.encode("latin-1") + b" >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


if __name__ == "__main__":
    target = sys.argv[1]
    with open(target, "wb") as fh:
        fh.write(build())
