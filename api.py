"""
Product Forge API — FastAPI wrapper around the multi-agent pipeline.

Usage:
    uvicorn api:app --host 0.0.0.0 --port 8100

Endpoints:
    POST /forge          — Run full pipeline (blocking, returns results)
    POST /forge/async    — Start pipeline run, returns job_id
    GET  /forge/{job_id} — Check status / get results
    GET  /forge/jobs     — List all jobs
"""

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pipeline import run_pipeline

app = FastAPI(title="Product Forge API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store
_jobs: dict[str, dict] = {}


class ForgeRequest(BaseModel):
    prompt: str = Field(..., description="Product brief or description")
    image_path: Optional[str] = Field(None, description="Path to a UI screenshot")
    quick: bool = Field(False, description="Quick mode: Phase 1 only (skip review + synthesis)")
    no_synthesis: bool = Field(False, description="Skip synthesis phase")
    no_review: bool = Field(False, description="Skip cross-review phase")
    brand_path: Optional[str] = Field(None, description="Path to brand JSON file")
    competitors_dir: Optional[str] = Field(None, description="Path to competitors directory")
    community_path: Optional[str] = Field(None, description="Path to community voice JSON file")


class ForgeResponse(BaseModel):
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    output_dir: Optional[str] = None
    results: Optional[dict] = None
    error: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None


@app.post("/forge", response_model=ForgeResponse)
async def forge_sync(req: ForgeRequest):
    """Run the pipeline synchronously (blocks until complete)."""
    job_id = str(uuid.uuid4())[:8]
    started = datetime.now().isoformat()

    try:
        results = await run_pipeline(
            prompt=req.prompt,
            image_path=req.image_path,
            skip_review=req.quick or req.no_review,
            skip_synthesis=req.quick or req.no_synthesis,
            brand_path=req.brand_path,
            competitors_dir=req.competitors_dir,
            community_path=req.community_path,
        )

        # Read the COMPLETE.md output
        out_dir = results.get("output_dir", "")
        complete_path = Path(out_dir) / "COMPLETE.md"
        complete_text = complete_path.read_text() if complete_path.exists() else None

        return ForgeResponse(
            job_id=job_id,
            status="completed",
            output_dir=out_dir,
            results={**results, "complete_md": complete_text},
            started_at=started,
            completed_at=datetime.now().isoformat(),
        )
    except Exception as e:
        return ForgeResponse(
            job_id=job_id,
            status="failed",
            error=str(e),
            started_at=started,
            completed_at=datetime.now().isoformat(),
        )


@app.post("/forge/async", response_model=ForgeResponse)
async def forge_async(req: ForgeRequest, background_tasks: BackgroundTasks):
    """Start the pipeline asynchronously. Poll GET /forge/{job_id} for results."""
    job_id = str(uuid.uuid4())[:8]
    started = datetime.now().isoformat()

    _jobs[job_id] = {
        "status": "running",
        "started_at": started,
        "prompt": req.prompt[:200],
    }

    async def _run():
        try:
            results = await run_pipeline(
                prompt=req.prompt,
                image_path=req.image_path,
                skip_review=req.quick or req.no_review,
                skip_synthesis=req.quick or req.no_synthesis,
                brand_path=req.brand_path,
                competitors_dir=req.competitors_dir,
                community_path=req.community_path,
            )
            out_dir = results.get("output_dir", "")
            complete_path = Path(out_dir) / "COMPLETE.md"
            complete_text = complete_path.read_text() if complete_path.exists() else None

            _jobs[job_id].update({
                "status": "completed",
                "output_dir": out_dir,
                "results": {**results, "complete_md": complete_text},
                "completed_at": datetime.now().isoformat(),
            })
        except Exception as e:
            _jobs[job_id].update({
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now().isoformat(),
            })

    # Run in background
    background_tasks.add_task(lambda: asyncio.run(_run()))

    return ForgeResponse(
        job_id=job_id,
        status="running",
        started_at=started,
    )


@app.get("/forge/{job_id}", response_model=ForgeResponse)
async def get_job(job_id: str):
    """Check status of an async pipeline run."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return ForgeResponse(
        job_id=job_id,
        status=job["status"],
        output_dir=job.get("output_dir"),
        results=job.get("results"),
        error=job.get("error"),
        started_at=job["started_at"],
        completed_at=job.get("completed_at"),
    )


@app.get("/forge/jobs")
async def list_jobs():
    """List all jobs."""
    return {
        job_id: {
            "status": job["status"],
            "prompt": job.get("prompt", ""),
            "started_at": job["started_at"],
            "completed_at": job.get("completed_at"),
        }
        for job_id, job in _jobs.items()
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "product-forge"}
