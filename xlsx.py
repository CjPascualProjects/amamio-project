"""Minimal, dependency-free .xlsx reader for the sales-platform importer.

An .xlsx file is a zip of XML parts, so the standard library is enough: no
pandas, no openpyxl, nothing to install on the client's machine.

Public API
----------
``sheet_names(path)``        -> ["Orders", "Summary", ...] in workbook order
``read_sheet(path, index)``  -> list of rows, each row a list of cell strings
``read_rows(path, index, header_row)`` -> (headers, [dict, ...])

Values come back as strings, already formatted: numbers keep their value,
date-formatted cells are converted from Excel serials to ``YYYY-MM-DD`` (or
``YYYY-MM-DD HH:MM`` when the cell carries a time).  Platform exports mix text
dates, serial dates and inline strings, so every variant is handled here rather
than in the import code.
"""
import datetime
import re
import zipfile
from xml.etree import ElementTree as ET

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Built-in number-format ids that represent dates/times (ECMA-376 §18.8.30).
_BUILTIN_DATE_FMTS = set(range(14, 23)) | {27, 30, 36, 45, 46, 47, 50, 57}
_EXCEL_EPOCH = datetime.datetime(1899, 12, 30)

MAX_ROWS = 50000     # safety ceiling for a single import


class XlsxError(Exception):
    """Raised when a file cannot be read as a workbook."""


def _col_index(ref):
    """'BC12' -> 54 (zero-based column index)."""
    m = re.match(r"([A-Za-z]+)", ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1).upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text_of(node):
    """Concatenate every <t> under a node, skipping phonetic <rPh> runs."""
    if node is None:
        return ""
    parts = []
    for child in node.iter():
        if child.tag == MAIN_NS + "t":
            parts.append(child.text or "")
    return "".join(parts)


def _serial_to_text(value, with_time):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    # Excel wrongly treats 1900 as a leap year; serials below 60 need +1 day.
    if number < 60:
        number += 1
    try:
        dt = _EXCEL_EPOCH + datetime.timedelta(days=number)
    except OverflowError:
        return str(value)
    if with_time or dt.hour or dt.minute or dt.second:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.strftime("%Y-%m-%d")


def _clean_number(text):
    """Trim the float noise Excel stores ('487.00000000000006' -> '487')."""
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return ("%.6f" % number).rstrip("0").rstrip(".")


class _Workbook:
    """Parsed workbook parts shared across sheet reads."""

    def __init__(self, path):
        try:
            self.zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as exc:
            raise XlsxError("Not a readable .xlsx workbook (%s)." % exc)
        self.names = self.zf.namelist()
        self.shared = self._read_shared_strings()
        self.date_styles = self._read_date_styles()
        self.sheets = self._read_sheet_index()

    def close(self):
        try:
            self.zf.close()
        except Exception:
            pass

    def _read(self, name):
        try:
            return self.zf.read(name)
        except KeyError:
            return None

    def _read_shared_strings(self):
        raw = self._read("xl/sharedStrings.xml")
        if not raw:
            return []
        root = ET.fromstring(raw)
        return [_text_of(si) for si in root.findall(MAIN_NS + "si")]

    def _read_date_styles(self):
        """Return the set of cell-style indexes whose format is a date."""
        raw = self._read("xl/styles.xml")
        if not raw:
            return set()
        root = ET.fromstring(raw)
        custom = {}
        numfmts = root.find(MAIN_NS + "numFmts")
        if numfmts is not None:
            for fmt in numfmts.findall(MAIN_NS + "numFmt"):
                code = (fmt.get("formatCode") or "")
                # Strip quoted literals and colour/condition blocks before
                # looking for date tokens, so "0.00\"kg\"" is not a date.
                bare = re.sub(r'"[^"]*"|\[[^\]]*\]', "", code)
                is_date = bool(re.search(r"[dDmMyYhHsS]", bare)) and \
                    not re.fullmatch(r"[^a-zA-Z]*", bare)
                try:
                    custom[int(fmt.get("numFmtId"))] = is_date
                except (TypeError, ValueError):
                    continue
        styles = set()
        cell_xfs = root.find(MAIN_NS + "cellXfs")
        if cell_xfs is None:
            return styles
        for idx, xf in enumerate(cell_xfs.findall(MAIN_NS + "xf")):
            try:
                fmt_id = int(xf.get("numFmtId") or 0)
            except ValueError:
                continue
            if fmt_id in _BUILTIN_DATE_FMTS or custom.get(fmt_id):
                styles.add(idx)
        return styles

    def _read_sheet_index(self):
        """[(name, zip_part), ...] in the order the workbook declares."""
        wb_raw = self._read("xl/workbook.xml")
        rels_raw = self._read("xl/_rels/workbook.xml.rels")
        targets = {}
        if rels_raw:
            for rel in ET.fromstring(rels_raw):
                target = rel.get("Target") or ""
                target = target.lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                targets[rel.get("Id")] = target
        sheets = []
        if wb_raw:
            root = ET.fromstring(wb_raw)
            holder = root.find(MAIN_NS + "sheets")
            for sheet in (holder if holder is not None else []):
                part = targets.get(sheet.get(REL_NS + "id"))
                if part and part in self.names:
                    sheets.append((sheet.get("name") or part, part))
        if not sheets:
            # Fall back to natural sheetN ordering when rels are unusable.
            parts = sorted(n for n in self.names
                           if n.startswith("xl/worksheets/sheet"))
            sheets = [("Sheet%d" % (i + 1), p) for i, p in enumerate(parts)]
        return sheets

    def rows(self, part, max_rows=MAX_ROWS):
        """Yield each row of a worksheet part as a list of cell strings."""
        raw = self._read(part)
        if raw is None:
            return
        root = ET.fromstring(raw)
        data = root.find(MAIN_NS + "sheetData")
        if data is None:
            return
        for count, row in enumerate(data.findall(MAIN_NS + "row")):
            if count >= max_rows:
                return
            cells = {}
            for cell in row.findall(MAIN_NS + "c"):
                cells[_col_index(cell.get("r"))] = self._cell_value(cell)
            if not cells:
                yield []
                continue
            width = max(cells) + 1
            yield [cells.get(i, "") for i in range(width)]

    def _cell_value(self, cell):
        ctype = cell.get("t")
        if ctype == "inlineStr":
            return _text_of(cell.find(MAIN_NS + "is")).strip()
        value_node = cell.find(MAIN_NS + "v")
        if value_node is None or value_node.text is None:
            return ""
        raw = value_node.text
        if ctype == "s":
            try:
                return self.shared[int(raw)].strip()
            except (ValueError, IndexError):
                return ""
        if ctype in ("str", "e"):
            return raw.strip()
        if ctype == "b":
            return "TRUE" if raw.strip() in ("1", "true", "TRUE") else "FALSE"
        # Numeric: a date format turns the serial into a readable timestamp.
        try:
            style = int(cell.get("s") or -1)
        except ValueError:
            style = -1
        if style in self.date_styles:
            return _serial_to_text(raw, with_time=("." in raw))
        return _clean_number(raw)


# --- Public helpers --------------------------------------------------------
def sheet_names(path):
    wb = _Workbook(path)
    try:
        return [name for name, _ in wb.sheets]
    finally:
        wb.close()


def read_sheet(path, sheet_index=0, max_rows=MAX_ROWS):
    """Return every row of one sheet as a list of lists of strings."""
    wb = _Workbook(path)
    try:
        if not wb.sheets:
            raise XlsxError("The workbook contains no worksheets.")
        if sheet_index < 0 or sheet_index >= len(wb.sheets):
            sheet_index = 0
        return list(wb.rows(wb.sheets[sheet_index][1], max_rows=max_rows))
    finally:
        wb.close()


def detect_header_row(rows, scan=12):
    """Guess which row holds the column headers.

    Platform exports often start with a title/metadata block, so the header is
    the first row within ``scan`` rows that has the most non-empty text cells."""
    best_index, best_score = 0, -1
    for i, row in enumerate(rows[:scan]):
        filled = [c for c in row if str(c).strip()]
        if len(filled) < 2:
            continue
        # Headers are text, not numbers — weight text cells higher.
        textual = sum(1 for c in filled
                      if not re.fullmatch(r"-?\d+(\.\d+)?", str(c).strip()))
        score = len(filled) + textual
        if score > best_score:
            best_index, best_score = i, score
    return best_index


def read_rows(path, sheet_index=0, header_row=None, max_rows=MAX_ROWS):
    """Return ``(headers, records)`` where each record is a header->value dict.

    ``header_row`` is zero-based; pass None to auto-detect it."""
    rows = read_sheet(path, sheet_index, max_rows=max_rows)
    if not rows:
        return [], []
    if header_row is None:
        header_row = detect_header_row(rows)
    header_row = max(0, min(header_row, len(rows) - 1))

    headers = []
    seen = {}
    for i, cell in enumerate(rows[header_row]):
        name = str(cell).strip() or ("Column %d" % (i + 1))
        if name in seen:
            seen[name] += 1
            name = "%s (%d)" % (name, seen[name])
        else:
            seen[name] = 1
        headers.append(name)

    records = []
    for row in rows[header_row + 1:]:
        if not any(str(c).strip() for c in row):
            continue
        record = {}
        for i, name in enumerate(headers):
            record[name] = row[i] if i < len(row) else ""
        records.append(record)
    return headers, records
