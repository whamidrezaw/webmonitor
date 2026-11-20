"""Website change monitor — entry point.

    python monitor_system.py run              start monitoring (default)
    python monitor_system.py app-url          print authenticated local MiniApp link
    python monitor_system.py validate         validate monitor-config.json
    python monitor_system.py health           check live daemon health (0=ok, 1=degraded, 2=down)
    python monitor_system.py inspect URL      analyse a page and suggest settings
    python monitor_system.py diagnose URL     test all fetch engines and routes
    python monitor_system.py package          build clean monitor-deploy.zip
    python monitor_system.py --help           all commands
"""

import sys

from webmonitor.cli import main

if __name__ == "__main__":
    sys.exit(main())
