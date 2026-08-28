from importlib import import_module


def get_model_adapter(name: str):
    normalized = (name or "").strip().lower()
    if normalized not in {"issm", "icepack"}:
        raise ValueError(f"Unsupported model: {name}")
    return import_module(f"cryostack_src.models.{normalized}")


__all__ = ["get_model_adapter"]
