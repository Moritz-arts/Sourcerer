"""Sourcerer's entry point. launch.py starts this file in the prepared environment."""
import sys

from sourcerer.desktop import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
