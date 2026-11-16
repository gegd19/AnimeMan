#!/usr/bin/env python3
"""AnimeMan production entry point: one Waitress process, multiple threads."""
from server_runtime import main

if __name__=='__main__':
    raise SystemExit(main())
