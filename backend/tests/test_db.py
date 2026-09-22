import pytest
from unittest.mock import AsyncMock, patch
from backend.dispatch_store import dispatch_store

@pytest.mark.asyncio
@patch("backend.dispatch_store.db_create_dispatch", new_callable=AsyncMock)
async def test_register_dispatch(mock_db_create):
    donors = {
        "donor_1": {"name": "Alice", "phone": "12345"},
        "donor_2": {"name": "Bob", "phone": "67890"}
    }
    await dispatch_store.register_dispatch("dispatch_123", donors, "HOSP-1", "O+", 0.0, 0.0)
    mock_db_create.assert_called_once_with(
        "dispatch_123",
        "HOSP-1",
        "O+",
        0.0,
        0.0,
        [
            {"id": "donor_1", "distance_km": None},
            {"id": "donor_2", "distance_km": None},
        ],
        units=1,
        urgency="urgent",
        address="",
    )

@pytest.mark.asyncio
@patch("backend.dispatch_store.db_register_call_sid", new_callable=AsyncMock)
async def test_register_call(mock_db_register):
    await dispatch_store.register_call("CA123", "dispatch_123", "donor_1")
    mock_db_register.assert_called_once_with("CA123", "dispatch_123", "donor_1")

@pytest.mark.asyncio
@patch("backend.dispatch_store.db_update_donor_status", new_callable=AsyncMock)
async def test_update_donor_status(mock_db_update):
    from backend.schemas.models import CallStatus
    mock_db_update.return_value = True
    success = await dispatch_store.update_donor_status("dispatch_123", "donor_1", CallStatus.ACCEPTED, 10)
    assert success is True
    mock_db_update.assert_called_once_with("dispatch_123", "donor_1", "accepted", 10)
