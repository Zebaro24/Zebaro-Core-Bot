def format_memory(b: float) -> str:
    mb = b / (1024**2)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.2f} MB"
