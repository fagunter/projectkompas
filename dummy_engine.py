from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd


DEMO_N_PEERS = 100
DEMO_N_RISKS = 25
DEMO_SEED_SALT = "projectkompas_demo_v1"


def _hash_seed(payload: dict[str, Any]) -> int:
    raw = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256((DEMO_SEED_SALT + raw).encode("utf-8")).hexdigest()
    # 32-bit seed range is enough and makes results stable across runs
    return int(digest[:8], 16)


def _parse_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    try:
        return float(x)
    except Exception:
        return None


def generate_demo_backend(
    *,
    project: pd.Series,
    profiles: pd.DataFrame,
    risks_all: pd.DataFrame,
    n_peers: int = DEMO_N_PEERS,
    n_risks: int = DEMO_N_RISKS,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """
    Build deterministic "dummy" peers and risks that look data-driven.

    Strategy:
    - Select peer candidates by matching Geo/TESI/Complexiteit (exact match, with relaxations).
    - Sample peer rows (bootstrap with replacement) using a deterministic seed derived from inputs.
    - Sample risk rows from the risk pool of sampled peer projects.
    """
    geo = project.get("primary_geo")
    tesi = project.get("primary_tesi")
    cx = project.get("Complexiteit")

    proj_budget = _parse_float(project.get("Prognose eindstand"))
    proj_tvp_hours = _parse_float(project.get("total_tvp_hours"))
    proj_slack = _parse_float(project.get("slack_days"))

    seed_payload = {
        "geo": geo,
        "tesi": tesi,
        "cx": cx,
        "budget": proj_budget,
        "tvp_hours": proj_tvp_hours,
        "slack_days": proj_slack,
    }
    seed = _hash_seed(seed_payload)
    rng = np.random.default_rng(seed)

    candidates = profiles.copy()
    if pd.notna(geo):
        candidates = candidates[candidates["primary_geo"] == geo]
    if pd.notna(tesi) and tesi != "":
        candidates = candidates[candidates["primary_tesi"] == tesi]
    if pd.notna(cx) and cx != "":
        candidates = candidates[candidates["Complexiteit"] == cx]

    # Relaxations if the candidate pool gets too small
    if len(candidates) < max(10, n_peers // 4):
        candidates = profiles.copy()
        if pd.notna(geo):
            candidates = candidates[candidates["primary_geo"] == geo]
        if pd.notna(tesi) and tesi != "":
            candidates = candidates[candidates["primary_tesi"] == tesi]
        if len(candidates) < max(10, n_peers // 4):
            candidates = profiles.copy()

    if candidates.empty:
        peers = pd.DataFrame(columns=profiles.columns)
        demo_risks = pd.DataFrame(columns=risks_all.columns)
        return peers, project, demo_risks

    # Bootstrap sample peers (with replacement) for a stable distribution
    replace = len(candidates) > 1
    sample_idx = rng.choice(candidates.index.to_numpy(), size=n_peers, replace=True)
    peers = candidates.loc[sample_idx].copy()

    # Risk pool from peer projects (optional: in Demo we may not load Risicodossier)
    if risks_all is None or risks_all.empty or "ProjectID" not in risks_all.columns:
        demo_risks = pd.DataFrame(columns=[] if risks_all is None else risks_all.columns)
    else:
        peer_pids = (
            peers.get("ProjectID", pd.Series([], dtype=object))
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        risk_pool = risks_all[risks_all["ProjectID"].astype(str).isin(peer_pids)].copy()
        if risk_pool.empty:
            demo_risks = pd.DataFrame(columns=risks_all.columns)
        else:
            # Sample risk rows deterministically; if pool is small, allow replacement
            replace_r = len(risk_pool) < n_risks
            demo_risks = risk_pool.sample(
                n=min(n_risks, len(risk_pool)) if not replace_r else n_risks,
                replace=replace_r,
                random_state=seed + 1,
            )

    # Keep project as-is; KPI functions will compare to sampled peers
    demo_project = project.copy()

    return peers.reset_index(drop=True), demo_project, demo_risks.reset_index(drop=True)

