"""Validate native Model Fit thread identifiers before local file access."""

import re


SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,100}")
