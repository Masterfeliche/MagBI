from datetime import UTC, datetime, timedelta

from magbi.api.refresh import _duration
from magbi.refresh.worker import refresh_dataset


def test_history_duration_and_the_celery_task_name() -> None:
    start = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    assert _duration(None, start) is None
    assert _duration(start, start + timedelta(seconds=2.5)) == 2.5
    assert refresh_dataset.name == "magbi.refresh_dataset"
