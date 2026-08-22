"""Shim for the home-stack loop_logger (ili release): no-op run bookkeeping.

The home stack records every automat run in loop_runs.db; the release container has no
such database. Keep the call surface so worker.py/scheduler.py stay unchanged.
"""
import logging

log = logging.getLogger("automat.loop_logger")


def start_run(loop_name: str, kind: str, **kwargs) -> None:
    log.debug("loop_logger shim: start_run(%s, %s) ignored", loop_name, kind)
    return None


def finish_run(run_id, outcome: str, **kwargs) -> None:
    log.debug("loop_logger shim: finish_run(%s, %s) ignored", run_id, outcome)
