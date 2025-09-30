def format_duration(seconds: int):
    if seconds == 0:
        return None
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0:
        return "%dd %dh" % (days, hours)
    elif hours > 0:
        return "%dh %dm" % (hours, minutes)
    elif minutes > 0:
        return "%dm %ds" % (minutes, seconds)
    else:
        return "%ds" % (seconds,)