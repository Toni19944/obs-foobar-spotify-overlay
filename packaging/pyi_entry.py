"""Frozen-exe entry point.

PyInstaller runs this as ``__main__`` at top level; it defers to the ``launcher``
package so the package's relative imports resolve (and so the self-reinvocation
``sys.executable --run-spectrum …`` routes through the same code path).
"""

import sys

from launcher.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
