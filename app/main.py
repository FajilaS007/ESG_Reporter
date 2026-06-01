"""FastAPI application entry point for the ESG Auditor."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.models import AuditReport, AuditRequest, LocationsRequest, CompanyAuditsBySociety
from app.orchestrator import run_audit, _get_all_audits_for_company, _group_audits_by_state_country
from app.tools.location_lookup import get_company_locations

app = FastAPI(title="ESG Auditor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve frontend path absolutely
FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@app.get("/")
async def serve_frontend() -> HTMLResponse:
    try:
        content = FRONTEND_INDEX.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=200)
    except Exception as e:
        return HTMLResponse(
            content=f"<h2>ESG Auditor</h2><p>Error loading frontend: {e}</p><p>Path: {FRONTEND_INDEX}</p>",
            status_code=200,
        )


@app.post("/locations")
async def locations(request: LocationsRequest) -> JSONResponse:
    if not request.company or not request.company.strip():
        return JSONResponse(status_code=400, content={"error": "company name is required"})
    try:
        locs = await get_company_locations(request.company.strip())
        return JSONResponse(status_code=200, content={"company": request.company, "locations": locs})
    except RuntimeError as e:
        return JSONResponse(status_code=500, content={"error": str(e), "locations": []})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Internal server error: {e}", "locations": []})


@app.post("/audit")
async def audit(request: AuditRequest) -> JSONResponse:
    if not request.company or not request.company.strip():
        return JSONResponse(status_code=400, content={"error": "company name is required"})
    try:
        location = request.location.strip() if request.location else None
        result = await run_audit(request.company.strip(), location=location)
        report = AuditReport.model_validate(result)
        return JSONResponse(status_code=200, content=report.model_dump())
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/company/{company}/audits")
async def company_audits_by_state_country(company: str) -> JSONResponse:
    """Get all audits for a company, grouped by country and state."""
    if not company or not company.strip():
        return JSONResponse(status_code=400, content={"error": "company name is required"})
    
    try:
        company = company.strip()
        # Load all cached audits for this company
        all_audits = _get_all_audits_for_company(company)
        
        if not all_audits:
            return JSONResponse(
                status_code=200,
                content={
                    "company": company,
                    "total_locations": 0,
                    "audits_by_country": {},
                    "average_score": None,
                    "worst_performing_location": None,
                    "best_performing_location": None,
                }
            )
        
        # Group by country and state
        grouped = _group_audits_by_state_country(all_audits)
        
        # Calculate statistics
        scores = [a.get("true_green_score") for audits_list in [locs for locs in grouped.values() for locs in locs.values()] for a in audits_list if a.get("true_green_score") is not None]
        average_score = sum(scores) / len(scores) if scores else None
        
        worst_audit = None
        best_audit = None
        if scores:
            worst_audit = min([a for audits_list in [locs for locs in grouped.values() for locs in locs.values()] for a in audits_list], key=lambda x: x.get("true_green_score") or 100)
            best_audit = max([a for audits_list in [locs for locs in grouped.values() for locs in locs.values()] for a in audits_list], key=lambda x: x.get("true_green_score") or 0)
        
        summary = CompanyAuditsBySociety(
            company=company,
            total_locations=len(all_audits),
            audits_by_country=grouped,
            average_score=average_score,
            worst_performing_location=worst_audit,
            best_performing_location=best_audit,
        )
        
        return JSONResponse(status_code=200, content=summary.model_dump())
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

