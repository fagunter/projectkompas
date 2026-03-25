"""Tests for the ProjectKompas v2 feature pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build_features import (
    normalize_pid,
    load_infra,
    load_risico,
    load_geld,
    load_planning,
    load_bds,
    load_ordertaken,
    aggregate_risks,
    aggregate_ordertaken,
    aggregate_tvp,
    build_project_profiles,
    compute_peer_scores,
    find_peers_geo,
    find_peers_tesi,
    find_peers_complexiteit,
    _budget_proximity,
    kpi_tvp,
    kpi_klanteis,
    kpi_budget,
)
from utils.text_features import extract_keywords, keyword_flag_count


# ---------------------------------------------------------------------------
# ProjectID normalisation
# ---------------------------------------------------------------------------

class TestNormalizePID:
    def test_add_dash(self):
        assert normalize_pid("M003976") == "M-003976"
        assert normalize_pid("L005577") == "L-005577"

    def test_already_has_dash(self):
        assert normalize_pid("M-003976") == "M-003976"

    def test_non_matching(self):
        assert normalize_pid("123456") == "123456"
        assert normalize_pid("") == ""

    def test_strips_whitespace(self):
        assert normalize_pid("  M003976  ") == "M-003976"


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------

class TestLoaders:
    def test_infra_has_required_columns(self):
        df = load_infra()
        for col in ["ProjectID", "Complexiteit", "Marktsegment", "Gebied"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_infra_no_null_project_ids(self):
        df = load_infra()
        assert df["ProjectID"].notna().all()

    def test_risico_has_required_columns(self):
        df = load_risico()
        for col in ["ProjectID", "Kans", "EV_geld", "Status"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_risico_row_count(self):
        df = load_risico()
        assert len(df) > 100, f"Expected >100 risk rows, got {len(df)}"

    def test_risico_numeric_columns(self):
        df = load_risico()
        for col in ["Kans", "EV_geld"]:
            assert pd.api.types.is_numeric_dtype(df[col]), f"{col} should be numeric"

    def test_geld_has_required_columns(self):
        df = load_geld()
        for col in ["ProjectID", "Prognose eindstand", "besteed", "budget_ratio"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_geld_prognose_is_numeric(self):
        df = load_geld()
        assert pd.api.types.is_numeric_dtype(df["Prognose eindstand"])

    def test_planning_has_required_columns(self):
        df = load_planning()
        for col in ["ProjectID", "Plandatum", "Klanteis", "slack_days"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_bds_has_required_columns(self):
        df = load_bds()
        for col in ["ProjectID", "Duur", "duur_hours"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_bds_duur_hours_numeric(self):
        df = load_bds()
        valid = df["duur_hours"].dropna()
        assert len(valid) > 0, "No valid duur_hours parsed"
        assert (valid >= 0).all(), "duur_hours should be non-negative"

    def test_ordertaken_loads(self):
        df = load_ordertaken()
        assert len(df) > 1000, f"Expected >1000 ordertaken rows, got {len(df)}"
        for col in ["ProjectID", "Geo", "TESI_code", "Alle_jaren"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_ordertaken_pid_normalized(self):
        df = load_ordertaken()
        sample = df["ProjectID"].dropna().head(100)
        for pid in sample:
            if pid and len(pid) > 2:
                assert "-" in pid, f"PID should have dash: {pid}"


# ---------------------------------------------------------------------------
# Aggregation tests
# ---------------------------------------------------------------------------

class TestAggregations:
    def test_aggregate_risks(self):
        risks = load_risico()
        agg = aggregate_risks(risks)
        assert "risico_count" in agg.columns
        assert (agg["risico_count"] > 0).all()

    def test_aggregate_ordertaken(self):
        ot = load_ordertaken()
        agg = aggregate_ordertaken(ot)
        for col in ["geo_codes", "tesi_codes", "n_taken", "primary_geo"]:
            assert col in agg.columns, f"Missing column: {col}"

    def test_aggregate_tvp(self):
        bds = load_bds()
        agg = aggregate_tvp(bds)
        for col in ["n_tvps", "total_tvp_hours", "avg_tvp_hours"]:
            assert col in agg.columns, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Profiles & peer matching
# ---------------------------------------------------------------------------

class TestProfiles:
    @pytest.fixture(scope="class")
    def profiles(self):
        return build_project_profiles()

    def test_profiles_has_all_columns(self, profiles):
        expected = [
            "ProjectID", "Complexiteit", "primary_geo", "primary_tesi",
            "budget_ratio", "slack_days", "total_tvp_hours", "risico_count",
        ]
        for col in expected:
            assert col in profiles.columns, f"Missing column: {col}"

    def test_profiles_count(self, profiles):
        assert len(profiles) > 2000

    def test_peer_geo(self, profiles):
        geo = profiles["primary_geo"].dropna().iloc[0]
        peers = find_peers_geo(profiles, geo)
        assert len(peers) >= 1
        assert (peers["primary_geo"] == geo).all()

    def test_peer_tesi(self, profiles):
        tesi = profiles["primary_tesi"].dropna().iloc[0]
        peers = find_peers_tesi(profiles, tesi)
        assert len(peers) >= 1
        assert (peers["primary_tesi"] == tesi).all()

    def test_peer_complexiteit(self, profiles):
        cx = profiles["Complexiteit"].dropna().iloc[0]
        peers = find_peers_complexiteit(profiles, cx)
        assert len(peers) >= 1

    def test_weighted_peer_scores(self, profiles):
        rich = profiles[
            profiles["primary_geo"].notna()
            & profiles["primary_tesi"].notna()
            & profiles["Complexiteit"].notna()
        ]
        proj = rich.iloc[0]
        peers = compute_peer_scores(proj, profiles)
        assert "peer_score" in peers.columns
        assert len(peers) > 0
        assert (peers["peer_score"] >= 0.20).all()
        assert proj["ProjectID"] not in peers["ProjectID"].values

    def test_weighted_peer_score_ordering(self, profiles):
        rich = profiles[profiles["primary_geo"].notna() & profiles["Complexiteit"].notna()]
        proj = rich.iloc[0]
        peers = compute_peer_scores(proj, profiles)
        if len(peers) > 1:
            scores = peers["peer_score"].values
            assert scores[0] >= scores[-1]

    def test_weighted_peer_empty_project(self, profiles):
        empty_proj = pd.Series({
            "ProjectID": "FAKE-99999",
            "primary_geo": None, "primary_tesi": None,
            "Complexiteit": None, "Marktsegment": None,
            "Prognose eindstand": None,
        })
        peers = compute_peer_scores(empty_proj, profiles)
        assert len(peers) == 0

    def test_budget_proximity(self):
        assert _budget_proximity(1_000_000, 1_000_000) == pytest.approx(1.0)
        assert _budget_proximity(1_000_000, 500_000) > 0.5
        assert _budget_proximity(100, 10_000_000) < 0.3
        assert _budget_proximity(0, 1_000_000) == 0.0
        assert _budget_proximity(np.nan, 1_000_000) == 0.0


# ---------------------------------------------------------------------------
# KPI tests
# ---------------------------------------------------------------------------

class TestKPIs:
    @pytest.fixture(scope="class")
    def profiles(self):
        return build_project_profiles()

    def _project_with_data(self, profiles, col):
        candidates = profiles[profiles[col].notna() & (profiles[col] > 0)]
        return candidates.iloc[0] if not candidates.empty else None

    def test_kpi_tvp_signals(self, profiles):
        proj = self._project_with_data(profiles, "total_tvp_hours")
        if proj is None:
            pytest.skip("No project with TVP data")
        geo = proj.get("primary_geo")
        peers = find_peers_geo(profiles, geo) if pd.notna(geo) else profiles
        result = kpi_tvp(proj, peers)
        assert result["signal"] in ("green", "orange", "red", "grey")
        assert "label" in result
        assert "detail" in result

    def test_kpi_klanteis_signals(self, profiles):
        proj = self._project_with_data(profiles, "slack_days")
        if proj is None:
            pytest.skip("No project with planning data")
        cx = proj.get("Complexiteit")
        peers = find_peers_complexiteit(profiles, cx) if pd.notna(cx) else profiles
        result = kpi_klanteis(proj, peers)
        assert result["signal"] in ("green", "orange", "red", "grey")

    def test_kpi_budget_signals(self, profiles):
        proj = self._project_with_data(profiles, "Prognose eindstand")
        if proj is None:
            pytest.skip("No project with budget data")
        cx = proj.get("Complexiteit")
        peers = find_peers_complexiteit(profiles, cx) if pd.notna(cx) else profiles
        result = kpi_budget(proj, peers)
        assert result["signal"] in ("green", "orange", "red", "grey")

    def test_kpi_tvp_no_peers(self):
        proj = pd.Series({"total_tvp_hours": 10})
        result = kpi_tvp(proj, pd.DataFrame({"total_tvp_hours": []}))
        assert result["signal"] == "grey"

    def test_kpi_klanteis_no_data(self):
        proj = pd.Series({"slack_days": None, "HaalbaarheidBoolean": None})
        result = kpi_klanteis(proj, pd.DataFrame({"slack_days": [], "HaalbaarheidBoolean": []}))
        assert result["signal"] == "grey"

    def test_kpi_budget_no_data(self):
        proj = pd.Series({"Prognose eindstand": None})
        result = kpi_budget(proj, pd.DataFrame({"Prognose eindstand": []}))
        assert result["signal"] == "grey"


# ---------------------------------------------------------------------------
# Text feature tests (kept from v1)
# ---------------------------------------------------------------------------

class TestTextFeatures:
    def test_extract_known_keywords(self):
        text = "Er is vertraging door afhankelijkheid en scope creep"
        kws = extract_keywords(text)
        assert "vertraging" in kws
        assert "afhankelijkheid" in kws
        assert "scope creep" in kws

    def test_extract_empty_string(self):
        assert extract_keywords("") == []
        assert extract_keywords(None) == []

    def test_case_insensitive(self):
        kws = extract_keywords("VERTRAGING en Rework")
        assert "vertraging" in kws
        assert "rework" in kws

    def test_keyword_flag_count(self):
        assert keyword_flag_count("vertraging en rework") == 2
        assert keyword_flag_count("geen risico hier") == 0
        assert keyword_flag_count(None) == 0

    def test_no_duplicates(self):
        kws = extract_keywords("vertraging vertraging vertraging")
        assert len(kws) == 1
