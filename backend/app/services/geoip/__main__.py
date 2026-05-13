"""Module entrypoint so ``python -m app.services.geoip`` invokes the CLI.

The CLI logic itself lives in ``cli.py``; this file just makes the
package directly runnable. Convention: ``python -m <package>`` should
"do the obvious thing", which for us means dispatching to the CLI.
"""
from app.services.geoip.cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
