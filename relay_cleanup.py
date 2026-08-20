"""Run one maintenance pass for the Ubuntu relay SQLite database."""
from __future__ import annotations

import relay_server


if __name__ == "__main__":
    deleted = relay_server.cleanup_once()
    print(f"relay cleanup complete: removed {deleted} expired letters", flush=True)
