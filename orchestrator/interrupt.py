import asyncio
import sys

def run_with_interrupt(main_coro):
    try:
        asyncio.run(main_coro)
    except KeyboardInterrupt:
        print("\nInterrupted by user, exiting...")
        sys.exit(130)