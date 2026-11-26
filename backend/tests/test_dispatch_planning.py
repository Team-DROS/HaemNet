"""Donor matching runs once per request, with blood groups looked up concurrently."""

from __future__ import annotations

import asyncio

import pytest

from backend.orchestration import graph
from backend.schemas.models import DispatchRequest
from backend.services import dispatching as planning
from backend.tests.conftest import HOSPITAL, matched_donor


def _request(blood_group="O-"):
    return DispatchRequest(
        hospital_id=HOSPITAL,
        blood_group=blood_group,
        urgency="critical",
        coordinates={"lat": 13.06, "lng": 80.25},
        units=1,
    )


@pytest.mark.asyncio
async def test_plan_hands_the_matched_donors_to_the_pipeline(monkeypatch):
    asha = matched_donor(13.07, 80.26, name="Asha")

    async def fake_find(**kwargs):
        return [asha]

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    plan = await planning.plan_dispatch(_request(), HOSPITAL)

    assert plan.donors_matched == 1
    (roster_entry,) = plan.state["donors"].values()
    assert roster_entry["donor_id"] == str(asha.id)
    assert roster_entry["status"] == "ringing" and roster_entry["distance_km"] > 0


@pytest.mark.asyncio
async def test_pipeline_does_not_query_donors_again(monkeypatch):
    async def must_not_query(**kwargs):
        raise AssertionError("donors were matched a second time")

    monkeypatch.setattr(graph, "find_eligible_donors", must_not_query)
    state = {"dispatch_id": "dp-1", "blood_group": "O-", "lat": 13.0, "lng": 80.2, "donors": {"d1": {}}}
    assert await graph.query_donors_node(state) is state


@pytest.mark.asyncio
async def test_pipeline_still_queries_when_run_on_its_own(monkeypatch):
    async def fake_find(**kwargs):
        return [matched_donor()]

    monkeypatch.setattr(graph, "find_eligible_donors", fake_find)
    state = await graph.query_donors_node({"dispatch_id": "dp-1", "blood_group": "O-", "lat": 13.0, "lng": 80.2})
    assert len(state["donors"]) == 1


@pytest.mark.asyncio
async def test_all_positive_groups_are_looked_up_concurrently(monkeypatch):
    in_flight, peak, asked = 0, 0, []

    async def slow_find(blood_group, lat, lng):
        nonlocal in_flight, peak
        asked.append(blood_group)
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return [matched_donor(blood_group=blood_group)]

    monkeypatch.setattr(planning, "find_eligible_donors", slow_find)
    plan = await planning.plan_dispatch(_request("All positive"), HOSPITAL)

    assert sorted(asked) == ["A+", "AB+", "B+", "O+"]
    assert peak == 4  # all four lookups were in flight together
    assert plan.donors_matched == 4
