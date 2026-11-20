"""HTTP API routers."""

from fastapi import APIRouter

from app.api import (
    routes_demo,
    routes_policy,
    routes_reference,
    routes_review,
    routes_runs,
    routes_stats,
)

ROUTERS: tuple[APIRouter, ...] = (
    routes_runs.router,
    routes_review.router,
    routes_demo.router,
    routes_reference.router,
    routes_policy.router,
    routes_stats.router,
)
