"""Import first in every Streamlit page: copies st.secrets into the environment (Streamlit Cloud
stores LLM_API_KEY etc. there) before shared.config reads it, and pins the working directory."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import streamlit as st

    for key, value in st.secrets.items():  # raises when no secrets are configured; that's fine
        if isinstance(value, (str, int, float, bool)) and key not in os.environ:
            os.environ[key] = str(value)
except Exception:
    pass
