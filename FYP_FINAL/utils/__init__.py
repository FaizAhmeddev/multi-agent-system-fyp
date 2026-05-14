try:
    from .file_parser import parse_file
    __all__ = ["parse_file"]
except Exception:
    pass
