def format_memory(b: float) -> str:
    mb = b / (1024**2)

    if mb >= 1024:
        gb = mb / 1024
        return f"{gb:.2f} GB"
    else:
        return f"{mb:.2f} MB"
