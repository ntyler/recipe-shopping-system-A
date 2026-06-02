import base64
import hmac
import secrets
import struct
import time
from io import BytesIO
from hashlib import sha1
from urllib.parse import quote

from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash


ISSUER_NAME = "Recipe Shopping System"
TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_VERIFY_WINDOW = 1
BACKUP_CODE_COUNT = 8
BACKUP_CODE_BYTES = 5


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_uri(secret, username, issuer=ISSUER_NAME):
    label = f"{issuer}:{username or 'account'}"
    return (
        f"otpauth://totp/{quote(label)}"
        f"?secret={quote(secret)}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1"
        f"&digits={TOTP_DIGITS}"
        f"&period={TOTP_PERIOD_SECONDS}"
    )


def totp_qr_data_uri(otpauth_uri):
    # Build the QR locally so the account setup secret is not sent to an external QR service.
    try:
        import qrcode
    except ImportError:
        return ""

    image = qrcode.make(str(otpauth_uri or ""))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def totp_code(secret, for_time=None):
    for_time = time.time() if for_time is None else for_time
    counter = int(for_time // TOTP_PERIOD_SECONDS)
    key = decode_base32_secret(secret)
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp_code(secret, code, for_time=None):
    code = normalize_code(code)

    if len(code) != TOTP_DIGITS or not code.isdigit():
        return False

    for_time = time.time() if for_time is None else for_time

    for offset in range(-TOTP_VERIFY_WINDOW, TOTP_VERIFY_WINDOW + 1):
        candidate_time = for_time + (offset * TOTP_PERIOD_SECONDS)
        if hmac.compare_digest(totp_code(secret, candidate_time), code):
            return True

    return False


def decode_base32_secret(secret):
    secret = "".join(str(secret or "").strip().upper().split())
    padding = "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(secret + padding, casefold=True)


def normalize_code(code):
    return "".join(str(code or "").strip().split()).replace("-", "")


def generate_backup_codes():
    return [
        format_backup_code(secrets.token_hex(BACKUP_CODE_BYTES))
        for _ in range(BACKUP_CODE_COUNT)
    ]


def format_backup_code(value):
    value = "".join(str(value or "").upper().split())
    return f"{value[:5]}-{value[5:10]}"


def hash_backup_codes(codes):
    return [
        {
            "code_hash": generate_password_hash(normalize_backup_code(code)),
            "used_at": "",
        }
        for code in codes
    ]


def normalize_backup_code(code):
    return "".join(str(code or "").strip().upper().replace("-", "").split())


def verify_backup_code(two_factor, code, used_at):
    normalized = normalize_backup_code(code)

    if not normalized:
        return False

    for backup_code in two_factor.get("backup_codes", []):
        if backup_code.get("used_at"):
            continue

        if check_password_hash(str(backup_code.get("code_hash") or ""), normalized):
            backup_code["used_at"] = used_at
            return True

    return False


def backup_codes_remaining(two_factor):
    return len([
        backup_code
        for backup_code in two_factor.get("backup_codes", [])
        if not backup_code.get("used_at")
    ])
