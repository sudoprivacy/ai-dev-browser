"""Typed consumer results survive pool shutdown and pending-job recovery."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from ai_dev_browser.pool import BrowserPool, load_state


class SavedPost(BaseModel):
    id: UUID
    created_at: datetime
    cost: Decimal
    optional: str | None = None


async def test_typed_results_checkpoint_and_recover_without_repeating_completed(
    tmp_path,
):
    timestamp = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    post_id = UUID("25e2989e-d26c-4aaf-b762-32b899604d89")
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def read_posts(self, label):
            calls.append(label)
            return [SavedPost(id=post_id, created_at=timestamp, cost=Decimal("1.25"))]

    checkpoint = tmp_path / "pool.json"
    options = dict(
        workers=1, profile="temp", close_browsers=False, state_file=checkpoint
    )
    async with BrowserPool(Client, **options) as pool:
        completed_id = await pool.run("read_posts", "completed")
        completed = await pool.wait_for(completed_id, timeout=5)
        assert completed.success
        record = completed.data[0]
        assert record["id"] == str(post_id)
        assert (
            datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
            == timestamp
        )
        assert record["cost"] == "1.25"
        assert "optional" not in record
        pending_id = await pool.run("read_posts", "recovered", _hold=True)

    saved = load_state(checkpoint)
    assert saved.completed[completed_id].data == completed.data
    assert [job.job_id for job in saved.pending] == [pending_id]

    async with BrowserPool(Client, **options) as restored:
        results = await restored.wait([completed_id, pending_id], timeout=5)
        assert all(result.success for result in results.values())
        assert results[completed_id].data == completed.data == results[pending_id].data

    assert calls == ["completed", "recovered"]
    saved = load_state(checkpoint)
    assert set(saved.completed) == {completed_id, pending_id}
    assert not saved.pending and not saved.in_progress
