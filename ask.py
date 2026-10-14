"""Ask the document adviser from the project root without starting Discord."""

import sys

from skycity_bot.ask import main


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
