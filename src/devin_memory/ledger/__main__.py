"""``python -m devin_memory.ledger`` — hook subprocess target."""

from __future__ import annotations

import sys

from devin_memory.ledger.cli import main

if __name__ == "__main__":
    sys.exit(main())
