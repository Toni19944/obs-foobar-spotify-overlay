"""Entry routing (orchestration O2; research D5).

Default invocation launches the GUI. When the frozen exe re-invokes itself with
``--run-spectrum <foobar|spotify> --device "<name>" [--port <n>]`` it dispatches
to the spectrum shim instead, so the single bundled interpreter serves both the
GUI and the carried spectrum server.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="FoobarOverlay", add_help=True)
    parser.add_argument(
        "--run-spectrum",
        choices=["foobar", "spotify"],
        default=None,
        help="Internal: run the carried spectrum server (self-reinvocation).",
    )
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--port", type=int, default=None)
    args, _unknown = parser.parse_known_args(argv)

    if args.run_spectrum:
        # Spectrum self-reinvocations inherit the bootloader splash; close it
        # immediately so an owned background child never flashes a splash window
        # (feature 010, FR-004 detail / research D4). Guarded for unfrozen dev runs.
        try:
            import pyi_splash  # type: ignore

            pyi_splash.close()
        except ImportError:
            pass

        from .spectrum_shim import run_spectrum

        run_spectrum(args.run_spectrum, args.device, args.port)
        return 0

    # Default: launch the GUI.
    from .app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
