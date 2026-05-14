"""
Load tabular uploads into DataFrames and build Plotly figures for finance dashboards.
"""

from __future__ import annotations

import io
import re
from typing import Any, Optional

import pandas as pd


def file_to_dataframe(uploaded_f) -> tuple[Optional[pd.DataFrame], str]:
    """
    Read a Streamlit UploadedFile into a DataFrame.
    Returns (df, error_message). error_message is empty on success.
    """
    name = (getattr(uploaded_f, "name", None) or "").lower()
    try:
        uploaded_f.seek(0)
    except Exception:
        pass
    try:
        raw = uploaded_f.read()
    except Exception as e:
        return None, str(e)

    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw))
            return df, ""
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw)), ""
        if name.endswith(".txt"):
            # Try comma / tab / semicolon sniffing
            for sep in (",", "\t", ";", "|"):
                try:
                    df = pd.read_csv(io.BytesIO(raw), sep=sep, engine="python")
                    if df.shape[1] > 1 or (df.shape[1] == 1 and sep == ","):
                        return df, ""
                except Exception:
                    continue
            lines = raw.decode("utf-8", errors="replace").splitlines()
            rows = [re.split(r"\s{2,}|\t", ln.strip()) for ln in lines if ln.strip()]
            if not rows:
                return None, "No rows found in text file."
            maxc = max(len(r) for r in rows)
            rows = [r + [""] * (maxc - len(r)) for r in rows]
            return pd.DataFrame(rows[1:], columns=rows[0] if rows else None), ""
        return None, f"Unsupported extension for tabular dashboard: {name or 'unknown'}"
    except Exception as e:
        return None, str(e)


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Best-effort: convert object columns that look numeric."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            s = out[c].astype(str).str.replace(",", "", regex=False).str.strip()
            conv = pd.to_numeric(s, errors="coerce")
            if conv.notna().sum() >= max(1, int(0.5 * len(out))):
                out[c] = conv
    return out


def guess_category_value_columns(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """Pick a reasonable category column and numeric value column."""
    df = coerce_numeric_columns(df)
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().any()]
    non_num = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    cat: Optional[str] = None
    if non_num:
        cat = str(non_num[0])
    elif df.columns.size:
        # all numeric: use lowest-cardinality column as grouping label
        best = None
        best_n = 10**9
        for c in df.columns:
            n = int(df[c].nunique(dropna=True))
            if 1 < n < best_n:
                best_n = n
                best = str(c)
        cat = best or str(df.columns[0])
    val = None
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]) and str(c) != cat:
            val = str(c)
            break
    if val is None and num:
        val = str(num[0])
    return cat, val


def dataframe_profile(df: pd.DataFrame) -> dict[str, Any]:
    """Summary stats for dashboard cards (lightweight; use df.describe() in UI for detail)."""
    df = coerce_numeric_columns(df)
    nulls = df.isnull().sum().to_dict()
    dtypes = {str(k): str(v) for k, v in df.dtypes.items()}
    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "column_names": [str(c) for c in df.columns],
        "dtypes": dtypes,
        "null_counts": {str(k): int(v) for k, v in nulls.items()},
        "numeric_columns": [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])],
    }


def aggregated_series(df: pd.DataFrame, category_col: str, value_col: str, agg: str = "sum") -> pd.DataFrame:
    if category_col == value_col:
        return pd.DataFrame()
    d = df[[category_col, value_col]].copy()
    d[value_col] = pd.to_numeric(d[value_col], errors="coerce")
    d = d.dropna(subset=[value_col])
    if agg == "mean":
        g = d.groupby(category_col, dropna=False)[value_col].mean().reset_index()
    elif agg == "count":
        g = d.groupby(category_col, dropna=False)[value_col].count().reset_index()
    else:
        g = d.groupby(category_col, dropna=False)[value_col].sum().reset_index()
    return g.sort_values(value_col, ascending=False)


def build_chart_figure(
    chart_type: str,
    df: pd.DataFrame,
    *,
    category_col: str,
    value_col: str,
    x_col: str,
    y_col: str,
    agg: str = "sum",
):
    """
    Return a Plotly figure for chart_type in:
    bar | line | area | pie | scatter
    """
    import plotly.express as px

    ct = (chart_type or "").lower().strip()
    df = coerce_numeric_columns(df)

    if ct == "scatter":
        if x_col not in df.columns or y_col not in df.columns:
            return None
        sub = df[[x_col, y_col]].copy()
        sub[x_col] = pd.to_numeric(sub[x_col], errors="coerce")
        sub[y_col] = pd.to_numeric(sub[y_col], errors="coerce")
        sub = sub.dropna()
        if sub.empty:
            return None
        return px.scatter(sub, x=x_col, y=y_col, title=f"Scatter: {x_col} vs {y_col}")

    if category_col not in df.columns or value_col not in df.columns:
        return None
    g = aggregated_series(df, category_col, value_col, agg=agg)
    if g.empty:
        return None

    title_base = f"{value_col} by {category_col} ({agg})"
    if ct == "bar":
        return px.bar(g, x=category_col, y=value_col, title=title_base)
    if ct == "line":
        return px.line(g, x=category_col, y=value_col, title=title_base, markers=True)
    if ct == "area":
        return px.area(g, x=category_col, y=value_col, title=title_base)
    if ct == "pie":
        return px.pie(g, values=value_col, names=category_col, title=title_base)
    return None
