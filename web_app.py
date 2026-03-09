"""
Minimal Flask web interface for the SAFI Meat Export analytical workspace.

Run:
    python web_app.py

Then open http://127.0.0.1:5000 in your browser.
"""

from __future__ import annotations

import traceback
from dataclasses import asdict

from flask import Flask, render_template, request, jsonify

from safi_engine.query_model import (
    CompareNamedScenariosQuery,
    CompareScenarioQuery,
    CreateScenarioFromTemplateQuery,
    DeleteReportQuery,
    DeleteScenarioQuery,
    ExplainLineItemQuery,
    ExplainShipmentQuery,
    FundingComparisonQuery,
    GetReportQuery,
    InspectScenarioTemplateQuery,
    ListReportsQuery,
    ListScenariosQuery,
    ListScenarioTemplatesQuery,
    MostAffectedShipmentsQuery,
    RunScenarioQuery,
    SaveReportQuery,
    SaveScenarioQuery,
    ScenarioSummaryQuery,
    WorkingCapitalQuery,
)
from safi_engine.query_runner import QueryContext
from safi_engine.workspace import AnalyticalWorkspace
from validate_all_shipments import (
    load_cycle_details,
    load_outflow_config,
    load_strategy_config,
)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_workspace() -> AnalyticalWorkspace:
    """Construct workspace exactly like the CLI does."""
    ctx = QueryContext(
        cycles=load_cycle_details(),
        config=load_strategy_config(),
        outflow_config=load_outflow_config(),
    )
    return AnalyticalWorkspace(ctx)


def create_app(workspace: AnalyticalWorkspace | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    ws = workspace or build_workspace()

    # Shipment count (static for lifetime of the app)
    total_shipments = len(ws.ctx.cycles)
    shipment_ids = list(range(1, total_shipments + 1))

    COST_TYPES = [
        "Slaughter", "Animal_Trimming", "Freight", "Clearance",
        "Stickers_Wrap", "AWB", "AQD", "PSW", "Halal",
        "Dry_Ice_Box", "TPT_Slaughter", "Data_Logger", "Chilling",
        "Polysheet", "Partha", "SALE",
    ]

    # ------------------------------------------------------------------
    # Helper: run a query and return (formatted_text, error)
    # ------------------------------------------------------------------
    def _run(query):
        try:
            _result, text = ws.execute(query)
            return text, None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    @app.route("/")
    def home():
        # Pre-load baseline data so the page renders without JS fetch
        baseline_text, baseline_err = _run(RunScenarioQuery())
        scenarios_text, _ = _run(ListScenariosQuery())
        reports_text, _ = _run(ListReportsQuery())
        return render_template(
            "index.html",
            page="home",
            total_shipments=total_shipments,
            shipment_ids=shipment_ids,
            cost_types=COST_TYPES,
            baseline_text=baseline_text or "",
            baseline_err=baseline_err or "",
            scenarios_text=scenarios_text or "",
            reports_text=reports_text or "",
        )

    # ------------------------------------------------------------------
    # API endpoints  (all return JSON with {text, error})
    # ------------------------------------------------------------------

    # --- Overview -------------------------------------------------------

    @app.route("/api/baseline-summary")
    def api_baseline_summary():
        text, err = _run(RunScenarioQuery())
        return jsonify(text=text, error=err)

    @app.route("/api/scenario-summary")
    def api_scenario_summary():
        name = request.args.get("scenario_name")
        text, err = _run(ScenarioSummaryQuery(scenario_name=name or None))
        return jsonify(text=text, error=err)

    # --- Templates ------------------------------------------------------

    @app.route("/api/templates")
    def api_templates():
        text, err = _run(ListScenarioTemplatesQuery())
        return jsonify(text=text, error=err)

    @app.route("/api/template/inspect")
    def api_template_inspect():
        name = request.args.get("name", "")
        text, err = _run(InspectScenarioTemplateQuery(name=name))
        return jsonify(text=text, error=err)

    @app.route("/api/template/create", methods=["POST"])
    def api_template_create():
        data = request.get_json(force=True)
        text, err = _run(CreateScenarioFromTemplateQuery(
            template_name=data.get("template_name", ""),
            scenario_name=data.get("scenario_name", ""),
            description=data.get("description", ""),
            notes=data.get("notes", ""),
        ))
        return jsonify(text=text, error=err)

    # --- Scenarios ------------------------------------------------------

    @app.route("/api/scenarios")
    def api_scenarios():
        text, err = _run(ListScenariosQuery())
        return jsonify(text=text, error=err)

    @app.route("/api/scenario/compare")
    def api_scenario_compare():
        name = request.args.get("scenario_name")
        text, err = _run(CompareScenarioQuery(scenario_name=name or None))
        return jsonify(text=text, error=err)

    @app.route("/api/scenario/compare-named")
    def api_scenario_compare_named():
        a = request.args.get("scenario_a", "baseline")
        b = request.args.get("scenario_b", "")
        mode = request.args.get("mode", "cashflow")
        sid = request.args.get("shipment_id")
        text, err = _run(CompareNamedScenariosQuery(
            scenario_a=a,
            scenario_b=b,
            mode=mode,
            shipment_id=int(sid) if sid else None,
        ))
        return jsonify(text=text, error=err)

    @app.route("/api/scenario/delete", methods=["POST"])
    def api_scenario_delete():
        data = request.get_json(force=True)
        text, err = _run(DeleteScenarioQuery(name=data.get("name", "")))
        return jsonify(text=text, error=err)

    # --- Analysis -------------------------------------------------------

    @app.route("/api/explain-shipment")
    def api_explain_shipment():
        sid = request.args.get("shipment_id", "1")
        name = request.args.get("scenario_name")
        text, err = _run(ExplainShipmentQuery(
            shipment_id=int(sid),
            scenario_name=name or None,
        ))
        return jsonify(text=text, error=err)

    @app.route("/api/explain-line-item")
    def api_explain_line_item():
        sid = request.args.get("shipment_id", "1")
        cost = request.args.get("cost_type", "")
        name = request.args.get("scenario_name")
        text, err = _run(ExplainLineItemQuery(
            shipment_id=int(sid),
            cost_type=cost,
            scenario_name=name or None,
        ))
        return jsonify(text=text, error=err)

    @app.route("/api/working-capital")
    def api_working_capital():
        sid = request.args.get("shipment_id")
        name = request.args.get("scenario_name")
        text, err = _run(WorkingCapitalQuery(
            shipment_id=int(sid) if sid else None,
            scenario_name=name or None,
        ))
        return jsonify(text=text, error=err)

    @app.route("/api/funding-comparison")
    def api_funding_comparison():
        name = request.args.get("scenario_name")
        text, err = _run(FundingComparisonQuery(scenario_name=name or None))
        return jsonify(text=text, error=err)

    @app.route("/api/most-affected")
    def api_most_affected():
        name = request.args.get("scenario_name")
        top_n = request.args.get("top_n", "5")
        text, err = _run(MostAffectedShipmentsQuery(
            scenario_name=name or None,
            top_n=int(top_n),
        ))
        return jsonify(text=text, error=err)

    # --- Reports --------------------------------------------------------

    @app.route("/api/reports")
    def api_reports():
        text, err = _run(ListReportsQuery())
        return jsonify(text=text, error=err)

    @app.route("/api/report/get")
    def api_report_get():
        name = request.args.get("name", "")
        text, err = _run(GetReportQuery(name=name))
        return jsonify(text=text, error=err)

    @app.route("/api/report/save", methods=["POST"])
    def api_report_save():
        data = request.get_json(force=True)
        # Execute the source query first, then save
        query_type = data.get("query_type", "")
        report_name = data.get("report_name", "")
        description = data.get("description", "")

        source_query = _build_source_query(query_type, data)
        if source_query is None:
            return jsonify(text=None, error=f"Unknown query type: {query_type}")

        try:
            result, formatted = ws.execute(source_query)
            save_q = SaveReportQuery(
                name=report_name,
                source_query=source_query,
                result=result,
                formatted_text=formatted,
                description=description,
            )
            _, save_text = ws.execute(save_q)
            return jsonify(text=save_text, error=None)
        except Exception as exc:
            return jsonify(text=None, error=f"{type(exc).__name__}: {exc}")

    @app.route("/api/report/delete", methods=["POST"])
    def api_report_delete():
        data = request.get_json(force=True)
        text, err = _run(DeleteReportQuery(name=data.get("name", "")))
        return jsonify(text=text, error=err)

    def _build_source_query(query_type: str, data: dict):
        """Build a query object from form data for report saving."""
        name = data.get("scenario_name") or None
        sid = data.get("shipment_id")
        sid_int = int(sid) if sid else None

        builders = {
            "scenario_summary": lambda: ScenarioSummaryQuery(scenario_name=name),
            "compare_scenario": lambda: CompareScenarioQuery(scenario_name=name),
            "explain_shipment": lambda: ExplainShipmentQuery(
                shipment_id=sid_int or 1, scenario_name=name),
            "explain_line_item": lambda: ExplainLineItemQuery(
                shipment_id=sid_int or 1,
                cost_type=data.get("cost_type", ""),
                scenario_name=name),
            "working_capital": lambda: WorkingCapitalQuery(
                shipment_id=sid_int, scenario_name=name),
            "funding_comparison": lambda: FundingComparisonQuery(
                scenario_name=name),
            "most_affected": lambda: MostAffectedShipmentsQuery(
                scenario_name=name),
        }
        builder = builders.get(query_type)
        return builder() if builder else None

    return app


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, webbrowser, threading

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    app = create_app()

    def open_browser():
        webbrowser.open(f"http://127.0.0.1:{args.port}")

    threading.Timer(1.0, open_browser).start()
    print(f"\n  SAFI Workspace UI → http://127.0.0.1:{args.port}\n")
    app.run(debug=False, host="0.0.0.0", port=args.port)
