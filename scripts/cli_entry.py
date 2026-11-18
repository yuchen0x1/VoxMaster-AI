"""Console entry point used by the frozen Windows CLI executable."""
import sys

from vox.cli import main


if __name__ == '__main__':
    sys.exit(main())
