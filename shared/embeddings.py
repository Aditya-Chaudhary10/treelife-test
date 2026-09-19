"""Local embeddings via fastembed (ONNX, CPU, no API cost). EMBEDDING_MODEL=none disables them."""
from __future__ import annotations

import threading

import numpy as np

from .config import settings

_model = None
_lock = threading.Lock()
_disabled = settings.embedding_model.lower() in ("", "none", "off", "false")


def available() -> bool:
    return not _disabled


def _get():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding  # lazy: first import downloads the model (~70MB)

                _model = TextEmbedding(model_name=settings.embedding_model, cache_dir=str(settings.data_dir / "models"))
    return _model


def embed(texts: list[str]) -> np.ndarray:
    """Returns an L2-normalised float32 matrix (n, dim). Empty input -> (0, 0)."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    vecs = np.asarray(list(_get().embed(texts, batch_size=32)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    return vecs / norms


def embed_query(text: str) -> np.ndarray:
    return embed([text])[0]
