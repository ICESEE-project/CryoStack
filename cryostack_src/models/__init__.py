from importlib import import_module

from .capabilities import (
    MODEL_CAPABILITIES,
    SUPPORTED_MODELS,
    ModelCapabilities,
    get_model_capabilities,
)


def get_model_adapter(name: str):
    normalized = (name or "").strip().lower()
    if normalized not in MODEL_CAPABILITIES:
        raise ValueError(f"Unsupported model: {name}")
    return import_module(f"cryostack_src.models.{normalized}")


__all__ = [
    "get_model_adapter",
    "get_model_capabilities",
    "ModelCapabilities",
    "MODEL_CAPABILITIES",
    "SUPPORTED_MODELS",
]
