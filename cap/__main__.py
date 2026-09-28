"""Allow ``python -m cap`` as an alias for ``cap``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
