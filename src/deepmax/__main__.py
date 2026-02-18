"""Entry point for `python -m deepmax`."""

import asyncio

from deepmax.main import main

if __name__ == "__main__":
    asyncio.run(main())
