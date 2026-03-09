"""Smoke tests for the Flask web UI."""

import json
import pytest
from web_app import create_app, build_workspace


@pytest.fixture(scope="module")
def ws():
    return build_workspace()


@pytest.fixture(scope="module")
def client(ws):
    app = create_app(workspace=ws)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --- Page load ---

def test_home_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"SAFI Workspace" in r.data


# --- Overview APIs ---

def test_baseline_summary(client):
    r = client.get("/api/baseline-summary")
    data = r.get_json()
    assert data["error"] is None
    assert len(data["text"]) > 0


def test_scenario_summary_no_name(client):
    r = client.get("/api/scenario-summary")
    data = r.get_json()
    # Without a scenario name it should still work (baseline)
    assert data["error"] is None


# --- Template APIs ---

def test_list_templates(client):
    r = client.get("/api/templates")
    data = r.get_json()
    assert data["error"] is None
    assert "total_upside" in data["text"]


def test_inspect_template(client):
    r = client.get("/api/template/inspect?name=total_upside")
    data = r.get_json()
    assert data["error"] is None
    assert "total_upside" in data["text"].lower()


def test_create_scenario_from_template(client):
    r = client.post("/api/template/create", json={
        "template_name": "freight_stress",
        "scenario_name": "web_test_freight",
    })
    data = r.get_json()
    assert data["error"] is None


# --- Scenario APIs ---

def test_list_scenarios(client):
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["error"] is None


def test_compare_named_scenarios(client):
    r = client.get("/api/scenario/compare-named?scenario_a=baseline&scenario_b=web_test_freight")
    data = r.get_json()
    assert data["error"] is None
    assert len(data["text"]) > 0


# --- Analysis APIs ---

def test_explain_shipment(client):
    r = client.get("/api/explain-shipment?shipment_id=1")
    data = r.get_json()
    assert data["error"] is None


def test_explain_line_item(client):
    r = client.get("/api/explain-line-item?shipment_id=1&cost_type=Freight")
    data = r.get_json()
    assert data["error"] is None


def test_working_capital(client):
    r = client.get("/api/working-capital?shipment_id=1")
    data = r.get_json()
    assert data["error"] is None


def test_funding_comparison(client):
    r = client.get("/api/funding-comparison")
    data = r.get_json()
    assert data["error"] is None


def test_most_affected(client):
    r = client.get("/api/most-affected?scenario_name=web_test_freight&top_n=3")
    data = r.get_json()
    assert data["error"] is None


# --- Report APIs ---

def test_save_and_list_report(client):
    r = client.post("/api/report/save", json={
        "query_type": "explain_shipment",
        "report_name": "web_test_report",
        "shipment_id": "1",
    })
    data = r.get_json()
    assert data["error"] is None

    r = client.get("/api/reports")
    data = r.get_json()
    assert data["error"] is None

    r = client.get("/api/report/get?name=web_test_report")
    data = r.get_json()
    assert data["error"] is None


# --- Cleanup ---

def test_cleanup_scenario(client):
    r = client.post("/api/scenario/delete", json={"name": "web_test_freight"})
    data = r.get_json()
    assert data["error"] is None


def test_cleanup_report(client):
    r = client.post("/api/report/delete", json={"name": "web_test_report"})
    data = r.get_json()
    assert data["error"] is None
