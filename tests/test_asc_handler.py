"""Unit tests for the Function Compute maintenance handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
import pytest

from cosmos_q.function_compute.asc_handler import handler, _parse_event


def test_parse_event():
    # Test different event types
    assert _parse_event(None) == {}
    assert _parse_event(b'{"user_id": "foo"}') == {"user_id": "foo"}
    assert _parse_event('{"user_id": "bar"}') == {"user_id": "bar"}
    assert _parse_event({"user_id": "baz"}) == {"user_id": "baz"}
    assert _parse_event("some random string") == {}


@patch("cosmos_q.memory_layer.CosmosMemoryLayer")
@patch.dict("os.environ", {"COSMOS_PG_DSN": "postgresql://cosmos:pass@host:5432/cosmos_q"})
def test_handler_single_user(mock_layer_class):
    # Mock layer setup
    mock_layer = MagicMock()
    mock_layer_class.return_value = mock_layer

    user_id = uuid4()
    
    # Configure mock engines
    mock_layer.forgetting.update_interference_scores = MagicMock()
    mock_layer.forgetting.run_forgetting = MagicMock(return_value=[uuid4()])
    mock_layer.consolidation.run_consolidation = MagicMock(return_value=[])

    event = json.dumps({"user_id": str(user_id), "trigger": "manual"}).encode("utf-8")
    
    res = handler(event, None)
    
    assert res["status"] == "ok"
    assert res["trigger"] == "manual"
    assert res["users_processed"] == 1
    assert res["results"][0]["user_id"] == str(user_id)
    assert res["results"][0]["memories_archived"] == 1

    # Verify real method names were called on the mocked layer properties
    mock_layer.forgetting.update_interference_scores.assert_called_once_with(user_id)
    mock_layer.forgetting.run_forgetting.assert_called_once_with(user_id)
    mock_layer.consolidation.run_consolidation.assert_called_once_with(user_id)


@patch("cosmos_q.memory_layer.CosmosMemoryLayer")
@patch.dict("os.environ", {"COSMOS_PG_DSN": "postgresql://cosmos:pass@host:5432/cosmos_q"})
def test_handler_all_users(mock_layer_class):
    # Mock layer setup
    mock_layer = MagicMock()
    mock_layer_class.return_value = mock_layer

    uids = [uuid4(), uuid4()]
    mock_layer.store.list_user_ids.return_value = uids
    
    mock_layer.forgetting.update_interference_scores = MagicMock()
    mock_layer.forgetting.run_forgetting = MagicMock(return_value=[])
    mock_layer.consolidation.run_consolidation = MagicMock(return_value=[])

    event = b'{}'
    
    res = handler(event, None)
    
    assert res["status"] == "ok"
    assert res["trigger"] == "timer"
    assert res["users_processed"] == 2
    assert res["results"][0]["user_id"] == str(uids[0])
    assert res["results"][1]["user_id"] == str(uids[1])

    # Verify calls
    assert mock_layer.forgetting.update_interference_scores.call_count == 2
    assert mock_layer.forgetting.run_forgetting.call_count == 2
    assert mock_layer.consolidation.run_consolidation.call_count == 2


@patch.dict("os.environ", {})
def test_handler_missing_dsn():
    res = handler(b'{"user_id": "some-uid"}', None)
    assert res["status"] == "error"
    assert "COSMOS_PG_DSN not set" in res["error"]
