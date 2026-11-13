"""Inspecciona los checkpoints persistidos del router en Postgres."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import sys

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.router.tools import open_checkpointer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Muestra la memoria persistida del router.")
    parser.add_argument("thread_id", nargs="?", help="Hilo que se quiere inspeccionar.")
    return parser.parse_args()


def checkpoint_timestamp(checkpoint: dict) -> str:
    timestamp = checkpoint.get("ts")
    if not timestamp:
        return "sin fecha"
    return datetime.fromisoformat(timestamp).astimezone().isoformat(timespec="seconds")


def main() -> None:
    args = parse_args()
    handle = open_checkpointer()
    try:
        if handle.mode != "postgres":
            raise SystemExit(
                "No hay memoria persistida disponible: "
                f"{handle.fallback_reason or 'Postgres no está configurado.'}"
            )

        if args.thread_id:
            config = {"configurable": {"thread_id": args.thread_id}}
            checkpoint_tuple = next(handle.checkpointer.list(config), None)
            if checkpoint_tuple is None:
                print(f"No hay checkpoints para el hilo {args.thread_id!r}.")
                return
            messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
            print(f"Hilo: {args.thread_id}")
            for message in messages:
                role = getattr(message, "type", message.__class__.__name__)
                content = getattr(message, "content", str(message))
                print(f"[{role}] {content}")
            return

        threads: dict[str, list[dict]] = defaultdict(list)
        for checkpoint_tuple in handle.checkpointer.list(None):
            thread_id = checkpoint_tuple.config.get("configurable", {}).get("thread_id")
            if thread_id:
                threads[str(thread_id)].append(checkpoint_tuple.checkpoint)

        if not threads:
            print("No hay hilos guardados.")
            return
        for thread_id, checkpoints in sorted(threads.items()):
            latest = max(checkpoints, key=lambda checkpoint: checkpoint.get("ts", ""))
            print(
                f"{thread_id}: {len(checkpoints)} checkpoints; "
                f"último: {checkpoint_timestamp(latest)}"
            )
    finally:
        handle.close()


if __name__ == "__main__":
    main()
