"""Module entrypoint so ``python -m app.services.fx`` invokes the CLI."""
import sys
from app.services.fx.cli import main

if __name__ == "__main__":
    sys.exit(main())
