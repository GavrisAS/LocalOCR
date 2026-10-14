"""LocalOCR has no dependency on development agents at runtime."""

try:
    from localocr._build_version import BUILD_VERSION as __version__  # ty: ignore[unresolved-import]
except ImportError:
    __version__ = "0.1"
