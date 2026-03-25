"""Safe I/O wrappers for reading/writing Excel and CSV files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


def safe_read_excel(
    path: str | Path, *, sheet_name: str | int = 0, **kwargs
) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Bestand niet gevonden: {path}")
    kwargs.setdefault("engine", "openpyxl")
    return pd.read_excel(path, sheet_name=sheet_name, **kwargs)


def safe_read_csv(path: str | Path, **kwargs) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Bestand niet gevonden: {path}")
    kwargs.setdefault("encoding", "utf-8-sig")
    return pd.read_csv(path, **kwargs)


def safe_write_csv(df: pd.DataFrame, path: str | Path) -> Path:
    """Atomically write a DataFrame to CSV (write to tmp, then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        suffix=".csv", dir=str(path.parent), prefix=".tmp_"
    )
    try:
        os.close(fd)
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, str(path))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    """Read a Streamlit UploadedFile (XLSX or CSV) into a DataFrame."""
    name = uploaded_file.name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file, engine="openpyxl")
    elif name.endswith(".csv"):
        return pd.read_csv(uploaded_file, encoding="utf-8-sig")
    else:
        raise ValueError(f"Onbekend bestandstype: {uploaded_file.name}")
