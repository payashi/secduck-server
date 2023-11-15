import base64
from datetime import datetime


def marshal(data: bytes) -> str:
    """Encode data before sending them"""
    return base64.b64encode(data).decode("utf-8")


def unmarshal(data: str) -> bytes:
    """Decode data after receiving them"""
    return base64.b64decode(data.encode("utf-8"))


def is_today(timestamp: float) -> bool:
    """Check if `timestamp` is today"""
    x = datetime.fromtimestamp(timestamp)
    return x.date() == datetime.now().date()
