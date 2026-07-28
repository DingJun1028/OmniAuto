#!/usr/bin/env python3
"""Fix nginx config on VPS - add favicon location before location / blocks."""

import re, sys

with open(sys.argv[1]) as f:
    config = f.read()

favicon_block = """    location = /favicon.ico {
        root /var/www/aistation;
        expires 30d;
        access_log off;
    }

"""

config = re.sub(r'(location / \{)', favicon_block + r'\1', config)

with open(sys.argv[1], 'w') as f:
    f.write(config)

print("OK: favicon injected")
