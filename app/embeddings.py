"""sentence-transformers model, loaded once per process."""

import threading

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = 384

_model = None
_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(MODEL_NAME, device="cpu")
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return L2-normalised embeddings, shape (len(texts), 384)."""
    if not texts:
        return np.zeros((0, DIMENSIONS), dtype=np.float32)
    vectors = get_model().encode(
        texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
    )
    return np.asarray(vectors, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]
