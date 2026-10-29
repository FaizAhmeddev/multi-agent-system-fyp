"""Spreadsheets: Google Sheets (Sheets API v4) and Excel files on this computer (openpyxl).

A sheet is addressed by (source, location, tab):
  google  location = the spreadsheet link or its id; tab = the sheet (tab) title
  excel   location = a .xlsx file inside one of the folders in HR_EXCEL_DIRS (or a name
          relative to the first of them, data/hr_sheets by default); tab = worksheet name
The first non-empty row is the header row. Rows come back as dicts keyed by header, plus
the spreadsheet row number, so an update can target the exact row.

Cell text written by other people is untrusted content.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPES_SHEETS = ["https://www.googleapis.com/auth/spreadsheets"]
MAX_ROWS = 5000
_excel_lock = threading.Lock()


class SheetError(Exception):
    """A message that is safe to show the user."""


def spreadsheet_id(location: str) -> str:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_\-]{20,})", location)
    sid = m.group(1) if m else location.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,}", sid):
        raise SheetError("That does not look like a Google Sheets link or id.")
    return sid


def _a1_tab(tab: str) -> str:
    return "'" + tab.replace("'", "''") + "'"


def _table(values: list[list[Any]], max_rows: int) -> dict[str, Any]:
    rows = [list(r) for r in values]
    start = next((i for i, r in enumerate(rows) if any(str(c).strip() for c in r)), None)
    if start is None:
        return {"headers": [], "rows": [], "header_row": 1, "total_rows": 0, "truncated": False}
    raw_headers = [str(c).strip() for c in rows[start]]
    headers = [h or f"Column {i + 1}" for i, h in enumerate(raw_headers)]
    out = []
    for i, r in enumerate(rows[start + 1:], start=start + 2):
        if not any(str(c).strip() for c in r):
            continue
        cells = [("" if c is None else c) for c in r] + [""] * (len(headers) - len(r))
        rec = {h: (v.isoformat() if hasattr(v, "isoformat") else v) for h, v in zip(headers, cells, strict=False)}
        rec["_row"] = i
        out.append(rec)
    return {"headers": headers, "rows": out[:max_rows], "header_row": start + 1, "total_rows": len(out),
            "truncated": len(out) > max_rows}


# ---------------------------------------------------------------------------- Google Sheets

class GoogleSheets:
    source = "google"

    def __init__(self, creds):
        from .backends import _build

        self.svc = _build("sheets", "v4", creds)

    def _exec(self, req, *, read: bool, what: str = "Google Sheets"):
        from googleapiclient.errors import HttpError

        try:
            return req.execute(num_retries=2 if read else 0)
        except HttpError as exc:
            code = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
            detail = ""
            try:
                import json

                detail = json.loads(exc.content.decode()).get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001 - no JSON body
                detail = ""
            if code == 403 and ("has not been used" in detail or "disabled" in detail):
                raise SheetError("The Google Sheets API is not enabled for your Google Cloud project. Enable it at "
                                 "https://console.cloud.google.com/apis/library/sheets.googleapis.com and try again."
                                 ) from exc
            if code in (401, 403):
                raise SheetError(f"Google refused access to that sheet ({detail or code}). Share it with the "
                                 "signed-in account, or sign in to Google again from AgentsMind.") from exc
            if code == 404:
                raise SheetError("That spreadsheet or tab was not found.") from exc
            raise SheetError(f"{what} returned HTTP {code}: {detail}") from exc
        except (TimeoutError, OSError) as exc:
            raise SheetError(f"{what} did not answer ({type(exc).__name__}).") from exc

    def tabs(self, location: str) -> dict[str, Any]:
        sid = spreadsheet_id(location)
        d = self._exec(self.svc.spreadsheets().get(spreadsheetId=sid, fields="properties.title,sheets.properties"),
                       read=True)
        return {"title": d.get("properties", {}).get("title", ""),
                "tabs": [s["properties"]["title"] for s in d.get("sheets", [])],
                "link": f"https://docs.google.com/spreadsheets/d/{sid}/edit"}

    def _first_tab(self, sid: str) -> str:
        return self.tabs(sid)["tabs"][0]

    def read(self, location: str, tab: str | None, max_rows: int) -> dict[str, Any]:
        sid = spreadsheet_id(location)
        tab = tab or self._first_tab(sid)
        d = self._exec(self.svc.spreadsheets().values().get(spreadsheetId=sid, range=_a1_tab(tab),
                                                            valueRenderOption="FORMATTED_VALUE"), read=True)
        t = _table(d.get("values", []), max_rows)
        t.update(tab=tab, link=f"https://docs.google.com/spreadsheets/d/{sid}/edit")
        return t

    def append(self, location: str, tab: str | None, rows: list[list[Any]]) -> dict[str, Any]:
        sid = spreadsheet_id(location)
        tab = tab or self._first_tab(sid)
        d = self._exec(self.svc.spreadsheets().values().append(
            spreadsheetId=sid, range=_a1_tab(tab), valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
            body={"values": rows}), read=False)
        upd = d.get("updates", {})
        return {"appended": int(upd.get("updatedRows", len(rows))), "range": upd.get("updatedRange", ""), "tab": tab}

    def update_row(self, location: str, tab: str | None, row: int, values: dict[str, Any]) -> dict[str, Any]:
        sid = spreadsheet_id(location)
        tab = tab or self._first_tab(sid)
        cur = self.read(sid, tab, MAX_ROWS)
        headers = cur["headers"]
        target = next((r for r in cur["rows"] if r["_row"] == row), None)
        if target is None:
            raise SheetError(f"Row {row} is empty or outside the table.")
        merged = [values.get(h, target.get(h, "")) for h in headers]
        rng = f"{_a1_tab(tab)}!A{row}"
        self._exec(self.svc.spreadsheets().values().update(spreadsheetId=sid, range=rng, valueInputOption="USER_ENTERED",
                                                           body={"values": [merged]}), read=False)
        return {"updated_row": row, "tab": tab}


# ---------------------------------------------------------------------------- Excel

def excel_dirs() -> list[Path]:
    raw = os.environ.get("HR_EXCEL_DIRS") or ""
    dirs = [Path(p.strip()).expanduser() for p in raw.split(";") if p.strip()]
    data = Path(os.environ.get("WORKSPACE_DATA_DIR") or REPO_ROOT / "data")
    dirs.insert(0, data / "hr_sheets")
    (data / "hr_sheets").mkdir(parents=True, exist_ok=True)
    out = []
    for d in dirs:
        if d.is_dir():
            out.append(d.resolve())
    return out


def excel_path(location: str, *, must_exist: bool = True) -> Path:
    roots = excel_dirs()
    p = Path(location).expanduser()
    if not p.is_absolute():
        p = roots[0] / p
    p = p.resolve()
    if not any(p.is_relative_to(r) for r in roots):
        raise SheetError("That Excel file is outside the folders AgentsMind may open. Add its folder to "
                         "HR_EXCEL_DIRS in .env, or upload the file in HR > Sheets.")
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise SheetError("Only .xlsx and .xlsm Excel files are supported.")
    if must_exist and not p.is_file():
        raise SheetError(f"Excel file not found: {p.name}")
    return p


class ExcelSheets:
    source = "excel"

    @staticmethod
    def _wb(path: Path, read_only: bool):
        from openpyxl import load_workbook

        try:
            return load_workbook(path, read_only=read_only, data_only=True, keep_vba=path.suffix == ".xlsm")
        except PermissionError as exc:
            raise SheetError(f"{path.name} is open in Excel or locked. Close it and try again.") from exc
        except Exception as exc:  # noqa: BLE001 - corrupt file
            raise SheetError(f"Could not open {path.name} ({type(exc).__name__}).") from exc

    def tabs(self, location: str) -> dict[str, Any]:
        p = excel_path(location)
        wb = self._wb(p, True)
        try:
            return {"title": p.name, "tabs": list(wb.sheetnames), "link": str(p)}
        finally:
            wb.close()

    def read(self, location: str, tab: str | None, max_rows: int) -> dict[str, Any]:
        p = excel_path(location)
        wb = self._wb(p, True)
        try:
            ws = wb[tab] if tab else wb.worksheets[0]
            values = [list(r) for r in ws.iter_rows(values_only=True)]
            t = _table(values, max_rows)
            t.update(tab=ws.title, link=str(p))
            return t
        except KeyError as exc:
            raise SheetError(f"{p.name} has no tab named '{tab}'.") from exc
        finally:
            wb.close()

    def append(self, location: str, tab: str | None, rows: list[list[Any]]) -> dict[str, Any]:
        p = excel_path(location)
        with _excel_lock:
            from openpyxl import load_workbook

            try:
                wb = load_workbook(p, keep_vba=p.suffix == ".xlsm")
            except PermissionError as exc:
                raise SheetError(f"{p.name} is open in Excel. Close it so AgentsMind can add the row.") from exc
            ws = wb[tab] if tab else wb.worksheets[0]
            for r in rows:
                ws.append(r)
            try:
                wb.save(p)
            except PermissionError as exc:
                raise SheetError(f"{p.name} is open in Excel. Close it so AgentsMind can save.") from exc
        return {"appended": len(rows), "range": f"{ws.title}!{ws.max_row - len(rows) + 1}:{ws.max_row}", "tab": ws.title}

    def update_row(self, location: str, tab: str | None, row: int, values: dict[str, Any]) -> dict[str, Any]:
        p = excel_path(location)
        cur = self.read(location, tab, MAX_ROWS)
        headers = cur["headers"]
        with _excel_lock:
            from openpyxl import load_workbook

            wb = load_workbook(p, keep_vba=p.suffix == ".xlsm")
            ws = wb[cur["tab"]]
            for i, h in enumerate(headers, start=1):
                if h in values:
                    ws.cell(row=row, column=i, value=values[h])
            try:
                wb.save(p)
            except PermissionError as exc:
                raise SheetError(f"{p.name} is open in Excel. Close it so AgentsMind can save.") from exc
        return {"updated_row": row, "tab": cur["tab"]}

    def create(self, name: str, headers: list[str], tab: str = "Sheet1") -> dict[str, Any]:
        from openpyxl import Workbook

        safe = re.sub(r"[^A-Za-z0-9 _\-]", "", name).strip() or "sheet"
        p = excel_path(f"{safe}.xlsx", must_exist=False)
        if p.exists():
            raise SheetError(f"{p.name} already exists.")
        wb = Workbook()
        ws = wb.active
        ws.title = tab[:31]
        ws.append(headers)
        wb.save(p)
        return {"location": str(p), "tab": ws.title}
