"""Tests run without any LLM or embedding model: the deterministic parts are what must be trustworthy."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["LLM_API_KEY"] = ""          # load_dotenv never overrides an existing var -> LLM disabled
os.environ["GROQ_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["EMBEDDING_MODEL"] = "none"   # BM25-only index; no model download in CI
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="treelife-tests-")
