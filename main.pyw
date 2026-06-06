"""Windowless entry point. Run with pythonw.exe for no console:

    pythonw main.pyw

Or with python for a console (useful while tuning the silence threshold)."""

import sys

from gamenote.app import main

if __name__ == "__main__":
    sys.exit(main())
