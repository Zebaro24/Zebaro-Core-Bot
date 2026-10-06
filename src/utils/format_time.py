def format_duration(seconds: int) -> str | None:
    if seconds == 0:
        return None
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0:
        return f"{days:d}d {hours:d}h"
    elif hours > 0:
        return f"{hours:d}h {minutes:d}m"
    elif minutes > 0:
        return f"{minutes:d}m {seconds:d}s"
    else:
        return f"{seconds:d}s"
