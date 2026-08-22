"""Shim for the home-stack config_env helper (ili release): values come from the
process environment only (docker compose injects config.env)."""
import os


def get(key: str, default: str = "") -> str:
    return os.getenv(key, default)
