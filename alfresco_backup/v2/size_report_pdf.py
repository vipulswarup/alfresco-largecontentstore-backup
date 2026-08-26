"""Render the backup size report as a simple multi-page PDF."""

from typing import List

_PAGE_WIDTH = 595
_PAGE_HEIGHT = 842
_MARGIN = 50
_FONT_SIZE = 9
_LINE_HEIGHT = 11
_CHARS_PER_LINE = 90
_LINES_PER_PAGE = int((_PAGE_HEIGHT - 2 * _MARGIN) / _LINE_HEIGHT)


def build_size_report_pdf(report_text: str) -> bytes:
    lines = _wrap_lines((report_text or '').splitlines())
    if not lines:
        lines = ['']
    pages = [
        lines[index:index + _LINES_PER_PAGE]
        for index in range(0, len(lines), _LINES_PER_PAGE)
    ]
    return _assemble_pdf(pages)


def _wrap_lines(lines: List[str]) -> List[str]:
    wrapped = []
    for line in lines:
        text = line.encode('latin-1', 'replace').decode('latin-1')
        if text == '':
            wrapped.append('')
            continue
        while len(text) > _CHARS_PER_LINE:
            wrapped.append(text[:_CHARS_PER_LINE])
            text = text[_CHARS_PER_LINE:]
        wrapped.append(text)
    return wrapped


def _escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _content_stream(lines: List[str]) -> bytes:
    start_y = _PAGE_HEIGHT - _MARGIN
    parts = [
        'BT',
        f'/F1 {_FONT_SIZE} Tf',
        f'{_LINE_HEIGHT} TL',
        f'{_MARGIN} {start_y} Td',
    ]
    for index, line in enumerate(lines):
        if index:
            parts.append('T*')
        parts.append(f'({_escape(line)}) Tj')
    parts.append('ET')
    return '\n'.join(parts).encode('latin-1')


def _assemble_pdf(pages: List[List[str]]) -> bytes:
    page_ids = [4 + 2 * index for index in range(len(pages))]
    content_ids = [5 + 2 * index for index in range(len(pages))]
    objects = [''] * (3 + 2 * len(pages) + 1)
    kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    objects[1] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[2] = f'<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>'.encode('ascii')
    objects[3] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>'
    for page_id, content_id, lines in zip(page_ids, content_ids, pages):
        objects[page_id] = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] '
            f'/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>'
        ).encode('ascii')
        stream = _content_stream(lines)
        objects[content_id] = (
            f'<< /Length {len(stream)} >>\nstream\n'.encode('ascii')
            + stream
            + b'\nendstream'
        )
    return _write_pdf(objects)


def _write_pdf(objects: List[bytes]) -> bytes:
    output = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index in range(1, len(objects)):
        offsets.append(len(output))
        output += f'{index} 0 obj\n'.encode('ascii')
        output += objects[index]
        if not objects[index].endswith(b'\n'):
            output += b'\n'
        output += b'endobj\n'
    xref_at = len(output)
    count = len(objects)
    output += f'xref\n0 {count}\n'.encode('ascii')
    output += b'0000000000 65535 f \n'
    for index in range(1, count):
        output += f'{offsets[index]:010d} 00000 n \n'.encode('ascii')
    output += (
        f'trailer\n<< /Size {count} /Root 1 0 R >>\n'
        f'startxref\n{xref_at}\n%%EOF\n'
    ).encode('ascii')
    return bytes(output)
