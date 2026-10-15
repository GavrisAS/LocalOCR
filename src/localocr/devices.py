"""Deterministic owned-engine candidates and fail-closed offload evidence."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeCandidate:
    backend: str
    engine: Path


def candidates(settings):
    engine, _, _ = settings.paths()
    root = engine.parent.parent
    result = []
    if settings.engine:
        # A custom executable is probed, never assumed GPU-capable.
        result.extend(RuntimeCandidate(b, engine) for b in ("cuda", "vulkan"))
    else:
        result.extend(
            RuntimeCandidate(b, root / "engines" / b / engine.name) for b in ("cuda", "vulkan")
        )
    if settings.device_mode != "gpu":
        cpu = root / "engines" / "cpu" / engine.name
        result.append(RuntimeCandidate("cpu", cpu if cpu.is_file() else engine))
    return [c for c in result if settings.device_mode != "cpu" or c.backend == "cpu"]


def parse_devices(text: str, backend: str):
    prefix = "CUDA" if backend == "cuda" else "Vulkan"
    for line in text.splitlines():
        match = re.match(r"\s*(" + prefix + r"\d+):\s*(.+)", line)
        if match and not any(
            word in line.lower()
            for word in (
                "llvmpipe",
                "lavapipe",
                "software",
                "cpu",
                "swiftshader",
                "microsoft basic render",
                "warp",
            )
        ):
            return match.group(1), match.group(2)
    raise ValueError(f"{backend.upper()}: физическое GPU не найдено в --list-devices")


def offload_evidence(text: str, backend: str) -> list[str]:
    """Require all LLM layers AND an explicit vision GPU compute buffer."""
    prefix = "CUDA" if backend == "cuda" else "Vulkan"
    layers = re.search(r"offloaded (\d+)/(\d+) layers to GPU", text)
    vision = [
        line
        for line in text.splitlines()
        if ("clip" in line.lower() or "vision" in line.lower())
        and prefix.lower() in line.lower()
        and ("buffer" in line.lower() or "using" in line.lower())
    ]
    vision_buffers = [
        line
        for line in text.splitlines()
        if "reserve_compute_meta" in line
        and prefix.lower() in line.lower()
        and "compute buffer size" in line
    ]
    if (
        not layers
        or int(layers[1]) == 0
        or layers[1] != layers[2]
        or not vision
        or not vision_buffers
    ):
        raise ValueError(
            "GPU_OFFLOAD_UNCONFIRMED: требуется полный LLM + vision offload; partial запрещён"
        )
    return [layers[0], *vision, *vision_buffers]


def failure_category(detail: str) -> str:
    text = detail.lower()
    if any(
        word in text for word in ("out of memory", "failed to allocate", "cuda_error_out_of_memory")
    ):
        return "GPU_OOM"
    if any(
        word in text
        for word in (
            "no kernel image",
            "invalid device function",
            "unsupported architecture",
            "unsupported gpu",
        )
    ):
        return "GPU_ARCH_UNSUPPORTED"
    if any(
        word in text for word in ("dll", "shared librar", "c0000135", "3221225781", "-1073741515")
    ):
        return "GPU_RUNTIME_OR_DRIVER_MISSING"
    if "offload_unconfirmed" in text:
        return "GPU_OFFLOAD_UNCONFIRMED"
    if "физическое gpu не найдено" in text:
        return "GPU_NOT_FOUND"
    return "ENGINE_START_FAILED"


def native_gpu_failure(line: str) -> bool:
    """Only native GPU diagnostic prefixes, never general completion output."""
    native = re.search(
        r"^\s*(?:\d[\d:.]*\s+[A-Z]\s+)?(?:CUDA error:|Vulkan error:|ggml_cuda[\w:]*|ggml_backend_cuda[\w:]*|ggml_vulkan[\w:]*|ggml_backend_vk[\w:]*)",
        line,
        re.IGNORECASE,
    )
    return bool(native) and (
        "error" in line.lower() or failure_category(line) != "ENGINE_START_FAILED"
    )
