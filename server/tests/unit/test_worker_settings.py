"""arq reads WorkerSettings attributes without calling them.

A method left here does not raise at import: it fails when the worker boots, in a
container, which is exactly where nobody is watching. These assertions are cheap
insurance for that.
"""
import inspect

from arq.connections import RedisSettings

from graft.ingestion.worker import WorkerSettings, dispatch_pending, ingest_job


def test_redis_settings_is_a_value_not_a_callable():
    assert isinstance(WorkerSettings.redis_settings, RedisSettings)


def test_lifecycle_hooks_are_coroutine_functions():
    assert inspect.iscoroutinefunction(WorkerSettings.on_startup)
    assert inspect.iscoroutinefunction(WorkerSettings.on_shutdown)


def test_the_job_and_the_sweep_are_registered():
    assert ingest_job in WorkerSettings.functions
    assert WorkerSettings.cron_jobs[0].coroutine is dispatch_pending


def test_limits_match_the_documented_policy():
    assert WorkerSettings.max_jobs == 1
    assert WorkerSettings.job_timeout == 600
    assert WorkerSettings.keep_result == 0
    assert WorkerSettings.max_tries == 3
