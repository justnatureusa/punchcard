import io
import secrets

import qrcode


def new_token() -> str:
    """A random, unguessable value to put in an employee's QR code."""
    return secrets.token_urlsafe(16)


def qr_png(token: str) -> bytes:
    image = qrcode.make(token, box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()
