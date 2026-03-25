"""
build_features.py  (v2 — Maakbaarheidstool)
=============================================
Loaders for all 6 data sources, ProjectID normalisation, peer-matching,
and KPI computation for TVP / Klanteis / Budget feasibility.

Usage:
    python build_features.py          # writes data/project_profiles.csv
    python build_features.py --dry    # prints head, does not write
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from utils.io_utils import safe_read_excel, safe_write_csv

DATA_DIR = Path(__file__).resolve().parent / "data"

# ---------------------------------------------------------------------------
# ProjectID normalisation  (M003976 -> M-003976)
# ---------------------------------------------------------------------------

_PID_RE = re.compile(r"^([A-Z]+)(\d.*)$")


def normalize_pid(pid: str) -> str:
    """Insert a dash between the letter prefix and digits if missing."""
    if not isinstance(pid, str):
        return str(pid)
    pid = pid.strip()
    if "-" in pid:
        return pid
    m = _PID_RE.match(pid)
    return f"{m.group(1)}-{m.group(2)}" if m else pid


# ---------------------------------------------------------------------------
# Ordertaken.csv custom parser (dot-delimited, ""-quoted strings)
# ---------------------------------------------------------------------------

ORDERTAKEN_COLS = [
    "Geo", "Afdeling", "Werkorder", "Operatie", "Gebied_code", "Station",
    "Equipmentnummer", "Equipment_omschrijving", "Taak_omschrijving",
    "TESI_code", "Kostensoort", "ProjectID", "Projectomschrijving",
    "Uitvoeringsjaar", "Deelreeks", "Alle_jaren", "Alle_voorgaande_jaren",
    "Y2025", "Np1", "Np2", "Np3", "Np4", "Np5", "Np6", "Np7", "Np8",
    "Np9", "Np10", "Np11", "Np12", "Np13", "Np14", "Np15",
    "Taak_in_PMF", "Taak_in_PMF1", "Budget_MT_AM", "Gebruikersstatus",
]

DQ = '""'


def _parse_ordertaken_line(line: str) -> list[str]:
    line = line.strip()
    if line.startswith('"') and ";;;" in line:
        line = line[1:]
        idx = line.rfind(";;;")
        line = line[:idx]
        if line.endswith('"'):
            line = line[:-1]

    parts: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i : i + 2] == DQ:
            close = line.find(DQ, i + 2)
            if close == -1:
                parts.append(line[i + 2 :])
                break
            parts.append(line[i + 2 : close])
            i = close + 2
            if i < n and line[i] == ".":
                i += 1
        else:
            dot = line.find(".", i)
            if dot == -1:
                parts.append(line[i:])
                break
            parts.append(line[i:dot])
            i = dot + 1
    return parts


def load_ordertaken(path: Path | None = None) -> pd.DataFrame:
    path = path or DATA_DIR / "Ordertaken.csv"
    rows: list[list[str]] = []
    ncols = len(ORDERTAKEN_COLS)
    with open(str(path), "r", encoding="utf-8-sig") as f:
        f.readline()  # skip header
        for line in f:
            parts = _parse_ordertaken_line(line)
            if len(parts) >= ncols:
                rows.append(parts[:ncols])

    df = pd.DataFrame(rows, columns=ORDERTAKEN_COLS)
    df = df[df["ProjectID"] != ""].copy()
    df["ProjectID"] = df["ProjectID"].apply(normalize_pid)

    df["Alle_jaren"] = (
        df["Alle_jaren"].str.replace(",", ".", regex=False)
    )
    df["Alle_jaren"] = pd.to_numeric(df["Alle_jaren"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Other loaders
# ---------------------------------------------------------------------------

INFRA_COLS = [
    "ProjectID", "Complexiteit", "Marktsegment", "Gebied",
    "Projectomschrijving", "Projectmanager", "Portfolio",
]


def load_infra(path: Path | None = None) -> pd.DataFrame:
    path = path or DATA_DIR / "Diminfraprojecten.xlsx"
    df = safe_read_excel(path)
    return df[INFRA_COLS].copy()


RISICO_COL_MAP: dict[int, str] = {
    0: "RisicoID", 1: "ProjectID", 2: "Onzekere_gebeurtenis",
    4: "Oorzaak", 6: "Gevolg", 7: "Status",
    8: "Endogeen_Exogeen", 9: "Allocatie", 10: "Eigenaar",
    11: "Kans", 12: "Tijd_min", 13: "Tijd_most", 14: "Tijd_max",
    15: "EV_tijd", 16: "Geld_min", 17: "Geld_most", 18: "Geld_max",
    19: "EV_geld", 20: "Beheersmaatregel", 21: "BM_Status",
    22: "Actiehouder", 23: "Einddatum",
}
NUMERIC_RISK_COLS = [
    "Kans", "Tijd_min", "Tijd_most", "Tijd_max", "EV_tijd",
    "Geld_min", "Geld_most", "Geld_max", "EV_geld",
]


def load_risico(path: Path | None = None) -> pd.DataFrame:
    path = path or DATA_DIR / "Risicodossier.xlsx"
    chunks: list[pd.DataFrame] = []
    for sheet in pd.ExcelFile(path, engine="openpyxl").sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, engine="openpyxl")
        header_indices = raw.index[raw[0] == "ID"].tolist()
        if not header_indices:
            continue
        for i, hdr in enumerate(header_indices):
            end = header_indices[i + 1] if i + 1 < len(header_indices) else len(raw)
            block = raw.iloc[hdr + 1 : end].copy()
            block = block[block[1].notna()]
            chunks.append(block)
    if not chunks:
        raise ValueError("Geen risico-data gevonden in Risicodossier")
    risks = pd.concat(chunks, ignore_index=True)
    col_rename = {idx: name for idx, name in RISICO_COL_MAP.items() if idx < len(risks.columns)}
    drop_cols = [c for c in risks.columns if c not in col_rename]
    risks = risks.drop(columns=drop_cols).rename(columns=col_rename)
    for col in NUMERIC_RISK_COLS:
        if col in risks.columns:
            risks[col] = pd.to_numeric(risks[col], errors="coerce")
    return risks


def load_geld(path: Path | None = None) -> pd.DataFrame:
    path = path or DATA_DIR / "DimGeld.xlsx"
    df = safe_read_excel(path)
    df["besteed"] = (
        df["Realisatie voorgaande jaren"]
        + df["Realisatie huidig jaar"]
        + df["Obligo"]
    )
    df["budget_ratio"] = df["besteed"] / df["Prognose eindstand"].replace(0, np.nan)
    return df[["ProjectID", "Prognose eindstand", "besteed", "budget_ratio"]].copy()


def load_planning(path: Path | None = None) -> pd.DataFrame:
    path = path or DATA_DIR / "DimPlanning.xlsx"
    df = safe_read_excel(path)
    df["slack_days"] = (df["Klanteis"] - df["Plandatum"]).dt.days
    return df


def load_bds(path: Path | None = None) -> pd.DataFrame:
    """Load FactBuitendienststellingen (pipe-delimited, QUOTE_NONE)."""
    path = path or DATA_DIR / "FactBuitendienststellingen.csv"
    df = pd.read_csv(str(path), sep="|", encoding="utf-8-sig",
                     low_memory=False, quoting=3)
    df["duur_hours"] = df["Duur"].apply(_duur_to_hours)
    return df


def _duur_to_hours(val) -> float | None:
    try:
        parts = str(val).split(":")
        return int(parts[0]) + int(parts[1]) / 60
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------

def aggregate_ordertaken(ot: pd.DataFrame) -> pd.DataFrame:
    """Per-project aggregates from Ordertaken: Geo set, TESI set, total budget."""
    grp = ot.groupby("ProjectID").agg(
        geo_codes=("Geo", lambda s: sorted(set(s))),
        tesi_codes=("TESI_code", lambda s: sorted(set(c for c in s if c))),
        n_taken=("ProjectID", "size"),
        budget_alle_jaren=("Alle_jaren", "sum"),
    ).reset_index()
    grp["primary_geo"] = grp["geo_codes"].apply(lambda gs: gs[0] if gs else None)
    grp["primary_tesi"] = grp["tesi_codes"].apply(
        lambda ts: ts[0] if ts else None
    )
    return grp


def aggregate_risks(risks: pd.DataFrame) -> pd.DataFrame:
    return (
        risks.groupby("ProjectID")
        .agg(
            risico_count=("ProjectID", "size"),
            sum_ev_geld=("EV_geld", "sum"),
            avg_kans=("Kans", "mean"),
        )
        .reset_index()
    )


def aggregate_tvp(bds: pd.DataFrame) -> pd.DataFrame:
    """Per-project TVP aggregates."""
    valid = bds[bds["ProjectID"].notna()].copy()
    return (
        valid.groupby("ProjectID")
        .agg(
            n_tvps=("ProjectID", "size"),
            total_tvp_hours=("duur_hours", "sum"),
            avg_tvp_hours=("duur_hours", "mean"),
        )
        .reset_index()
    )


# ---------------------------------------------------------------------------
# Master profile builder
# ---------------------------------------------------------------------------

def build_project_profiles() -> pd.DataFrame:
    """Build a master table joining all sources on ProjectID."""
    infra = load_infra()
    geld = load_geld()
    planning = load_planning()
    risk_agg = aggregate_risks(load_risico())
    tvp_agg = aggregate_tvp(load_bds())
    ot_agg = aggregate_ordertaken(load_ordertaken())

    df = infra.copy()
    df = df.merge(geld, on="ProjectID", how="left")
    df = df.merge(
        planning[["ProjectID", "Plandatum", "Klanteis",
                   "HaalbaarheidBoolean", "slack_days"]],
        on="ProjectID", how="left",
    )
    df = df.merge(risk_agg, on="ProjectID", how="left")
    df = df.merge(tvp_agg, on="ProjectID", how="left")
    df = df.merge(
        ot_agg[["ProjectID", "primary_geo", "primary_tesi",
                 "n_taken", "budget_alle_jaren", "geo_codes", "tesi_codes"]],
        on="ProjectID", how="left",
    )

    for col in ["risico_count", "n_tvps", "n_taken"]:
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)
    for col in ["sum_ev_geld", "avg_kans", "total_tvp_hours", "budget_alle_jaren"]:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    return df


# ---------------------------------------------------------------------------
# Peer matching  (weighted multi-dimensional similarity)
# ---------------------------------------------------------------------------

PEER_WEIGHTS = {
    "geo": 0.30,
    "tesi": 0.30,
    "complexiteit": 0.20,
    "marktsegment": 0.10,
    "budget": 0.10,
}
PEER_MIN_SCORE = 0.20
PEER_TOP_K = 100


def _budget_proximity(a: float, b: float) -> float:
    """0–1 similarity based on budget size (log-scale)."""
    if pd.isna(a) or pd.isna(b) or a <= 0 or b <= 0:
        return 0.0
    log_a, log_b = np.log1p(a), np.log1p(b)
    max_log = max(log_a, log_b, 1.0)
    return max(0, 1 - abs(log_a - log_b) / max_log)


def compute_peer_scores(
    project: pd.Series,
    profiles: pd.DataFrame,
    *,
    weights: dict | None = None,
    top_k: int = PEER_TOP_K,
    min_score: float = PEER_MIN_SCORE,
) -> pd.DataFrame:
    """Score every project in *profiles* against *project* and return top peers.

    Returns a copy of profiles with an added ``peer_score`` column,
    filtered to score >= min_score, sorted descending, limited to top_k.
    The project itself is excluded.
    """
    w = weights or PEER_WEIGHTS
    pid = project.get("ProjectID", "")

    others = profiles[profiles["ProjectID"] != pid].copy()
    if others.empty:
        return others

    score = pd.Series(0.0, index=others.index)

    proj_geo = project.get("primary_geo")
    if pd.notna(proj_geo) and proj_geo:
        score += w["geo"] * (others["primary_geo"] == proj_geo).astype(float)

    proj_tesi = project.get("primary_tesi")
    if pd.notna(proj_tesi) and proj_tesi:
        score += w["tesi"] * (others["primary_tesi"] == proj_tesi).astype(float)

    proj_cx = project.get("Complexiteit")
    if pd.notna(proj_cx) and proj_cx:
        score += w["complexiteit"] * (others["Complexiteit"] == proj_cx).astype(float)

    proj_ms = project.get("Marktsegment")
    if pd.notna(proj_ms) and proj_ms:
        score += w["marktsegment"] * (others["Marktsegment"] == proj_ms).astype(float)

    proj_budget = project.get("Prognose eindstand")
    if pd.notna(proj_budget) and proj_budget > 0 and "Prognose eindstand" in others.columns:
        score += w["budget"] * others["Prognose eindstand"].apply(
            lambda b: _budget_proximity(proj_budget, b)
        )

    others["peer_score"] = score
    others = others[others["peer_score"] >= min_score]
    others = others.sort_values("peer_score", ascending=False).head(top_k)
    return others


def find_peers_geo(profiles: pd.DataFrame, geo: str) -> pd.DataFrame:
    """Find projects sharing the same primary Geo code (legacy helper)."""
    if not geo:
        return pd.DataFrame()
    return profiles[profiles["primary_geo"] == geo]


def find_peers_tesi(profiles: pd.DataFrame, tesi: str) -> pd.DataFrame:
    """Find projects sharing the same primary TESI code (legacy helper)."""
    if not tesi:
        return pd.DataFrame()
    return profiles[profiles["primary_tesi"] == tesi]


def find_peers_complexiteit(profiles: pd.DataFrame, cx: str) -> pd.DataFrame:
    """Legacy helper kept for backward compatibility."""
    if not cx or pd.isna(cx):
        return pd.DataFrame()
    return profiles[profiles["Complexiteit"] == cx]


# ---------------------------------------------------------------------------
# KPI calculations
# ---------------------------------------------------------------------------

def _within_iqr(value: float, p25: float, p75: float) -> bool:
    """True when *value* falls within the P25–P75 range."""
    return p25 <= value <= p75


def kpi_tvp(project: pd.Series, peers: pd.DataFrame) -> dict:
    """KPI 1: Is the TVP allocation realistic compared to peers (P25–P75)?"""
    proj_tvp = project.get("total_tvp_hours", 0) or 0

    if "total_tvp_hours" not in peers.columns:
        peer_tvp = pd.Series(dtype=float)
    else:
        peer_tvp = peers["total_tvp_hours"].dropna()
        peer_tvp = peer_tvp[peer_tvp > 0]

    if peer_tvp.empty:
        return {"signal": "grey", "label": "Onbekend",
                "detail": "Geen peer-data beschikbaar",
                "project_value": proj_tvp, "peer_median": None,
                "peer_p25": None, "peer_p75": None,
                "peer_values": peer_tvp.tolist()}

    p25, p50, p75 = float(peer_tvp.quantile(0.25)), float(peer_tvp.median()), float(peer_tvp.quantile(0.75))
    realistic = _within_iqr(proj_tvp, p25, p75)
    signal = "green" if realistic else "red"
    label = "Realistisch" if realistic else "Onrealistisch"

    return {
        "signal": signal,
        "label": label,
        "detail": f"Project: {proj_tvp:.0f}h | Mediaan peers: {p50:.0f}h | P25–P75: {p25:.0f}–{p75:.0f}h",
        "project_value": proj_tvp,
        "peer_median": p50,
        "peer_p25": p25,
        "peer_p75": p75,
        "peer_values": peer_tvp.tolist(),
    }


def kpi_klanteis(project: pd.Series, peers: pd.DataFrame) -> dict:
    """KPI 2: Is the slack realistic compared to peers (P25–P75)?"""
    slack = project.get("slack_days")

    peer_slack = peers["slack_days"].dropna() if "slack_days" in peers.columns else pd.Series(dtype=float)

    if pd.isna(slack):
        return {"signal": "grey", "label": "Onbekend",
                "detail": "Geen planning-data beschikbaar",
                "project_value": None, "peer_median": None,
                "peer_p25": None, "peer_p75": None,
                "peer_values": peer_slack.tolist()}

    if peer_slack.empty:
        return {"signal": "grey", "label": "Onbekend",
                "detail": f"Slack: {slack:.0f} dagen | Geen peer-data",
                "project_value": slack, "peer_median": None,
                "peer_p25": None, "peer_p75": None,
                "peer_values": []}

    p25, p50, p75 = float(peer_slack.quantile(0.25)), float(peer_slack.median()), float(peer_slack.quantile(0.75))
    realistic = _within_iqr(slack, p25, p75)
    signal = "green" if realistic else "red"
    label = "Realistisch" if realistic else "Onrealistisch"

    return {
        "signal": signal,
        "label": label,
        "detail": f"Slack: {slack:.0f} dagen | Mediaan peers: {p50:.0f} dagen | P25–P75: {p25:.0f}–{p75:.0f} dagen",
        "project_value": slack,
        "peer_median": p50,
        "peer_p25": p25,
        "peer_p75": p75,
        "peer_values": peer_slack.tolist(),
    }


def kpi_budget(project: pd.Series, peers: pd.DataFrame) -> dict:
    """KPI 3: Is the budget realistic compared to peers (P25–P75)?"""
    proj_budget = project.get("Prognose eindstand")

    col = "Prognose eindstand"
    if col not in peers.columns:
        peer_budgets = pd.Series(dtype=float)
    else:
        peer_budgets = peers[col].dropna()
        peer_budgets = peer_budgets[peer_budgets > 0]

    if pd.isna(proj_budget) or proj_budget is None:
        return {"signal": "grey", "label": "Onbekend",
                "detail": "Geen budget-data beschikbaar",
                "project_value": None, "peer_median": None,
                "peer_p25": None, "peer_p75": None,
                "peer_values": peer_budgets.tolist()}

    if peer_budgets.empty:
        return {"signal": "grey", "label": "Onbekend",
                "detail": f"Prognose: \u20ac{proj_budget:,.0f} | Geen peer-data",
                "project_value": proj_budget, "peer_median": None,
                "peer_p25": None, "peer_p75": None,
                "peer_values": []}

    p25, p50, p75 = float(peer_budgets.quantile(0.25)), float(peer_budgets.median()), float(peer_budgets.quantile(0.75))
    realistic = _within_iqr(proj_budget, p25, p75)
    signal = "green" if realistic else "red"
    label = "Realistisch" if realistic else "Onrealistisch"

    fmt = lambda v: f"\u20ac{v:,.0f}".replace(",", ".")
    return {
        "signal": signal,
        "label": label,
        "detail": f"Project: {fmt(proj_budget)} | Mediaan peers: {fmt(p50)} | P25–P75: {fmt(p25)}–{fmt(p75)}",
        "project_value": proj_budget,
        "peer_median": p50,
        "peer_p25": p25,
        "peer_p75": p75,
        "peer_values": peer_budgets.tolist(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(*, dry: bool = False) -> pd.DataFrame:
    profiles = build_project_profiles()
    if not dry:
        out_path = DATA_DIR / "project_profiles.csv"
        export = profiles.drop(columns=["geo_codes", "tesi_codes"], errors="ignore")
        safe_write_csv(export, out_path)
        print(f"Profielen geschreven naar {out_path}  ({len(profiles)} rijen)")
    return profiles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build project profiles (v2)")
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    df = run(dry=args.dry)
    print(df.head(10).to_string())
    print(f"\nTotaal: {len(df)} projecten")
    print(f"Met TVP data: {(df['n_tvps'] > 0).sum()}")
    print(f"Met planning: {df['Plandatum'].notna().sum()}")
    print(f"Met risico's: {(df['risico_count'] > 0).sum()}")
