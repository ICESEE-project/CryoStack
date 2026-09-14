"""P2: every model's result package and visualizer satisfies the shared,
model-neutral contract in results_common."""
from __future__ import annotations

from cryostack_src.models import SUPPORTED_MODELS
from cryostack_src.models.results_common import (
    RESULT_CONTRACT_METHODS,
    ResultPackageProtocol,
    VisualizerProtocol,
    describe_package,
    resolve_result_reader,
    resolve_visualizer,
)


def test_each_model_result_package_is_contract_conformant(tmp_path):
    for model in SUPPORTED_MODELS:
        reader = resolve_result_reader(model)
        pkg = reader(tmp_path)                 # empty dir -> a "missing" package
        for method in RESULT_CONTRACT_METHODS:
            assert callable(getattr(pkg, method, None)), (
                f"{model} package missing {method}()")
        assert isinstance(getattr(pkg, "status", None), str)
        assert isinstance(pkg, ResultPackageProtocol)
        # describe_package never raises, even on an empty package
        d = describe_package(pkg)
        assert d["readable"] is False
        assert d["solutions"] == []


def test_visualizer_resolves_iff_capabilities_say_so():
    from cryostack_src.models.capabilities import MODEL_CAPABILITIES
    for model, cap in MODEL_CAPABILITIES.items():
        viz = resolve_visualizer(model)
        if cap.visualization:
            assert viz is not None
            assert isinstance(viz, VisualizerProtocol)
        else:
            assert viz is None
    assert resolve_visualizer("no-such-model") is None


def test_unknown_model_reader_falls_back_without_crashing(tmp_path):
    pkg = resolve_result_reader("no-such-model")(tmp_path)
    assert pkg.is_readable() is False
