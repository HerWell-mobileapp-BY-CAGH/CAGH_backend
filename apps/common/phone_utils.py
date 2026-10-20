import re
from typing import Optional, TypedDict


ETHIO_TELECOM_CARRIER = "Ethio Telecom"
SAFARICOM_CARRIER = "Safaricom Ethiopia"
ETHIOPIA_COUNTRY_CODE = "+251"


class NormalizedPhoneDict(TypedDict):
    is_valid: bool
    is_ethiopian: bool
    is_mobile: bool
    carrier: Optional[str]
    phone_number: Optional[str]        # Canonical E.164: "+251911223344"
    phone_number_local: Optional[str]  # Local format: "0911223344"
    tel_uri: Optional[str]             # Standard URI: "tel:+251911223344"
    error: Optional[str]
    raw: Optional[str]


def normalize_ethiopian_phone(phone_input: Optional[str]) -> NormalizedPhoneDict:
    """
    Validates, normalizes, and identifies carrier for Ethiopian mobile phone numbers.
    
    Supports:
    - Ethio Telecom mobile numbers: prefix '9' (local '09...', international '+2519...')
    - Safaricom Ethiopia mobile numbers: prefix '7' (local '07...', international '+2517...')
    
    Accepts:
    - Local formats: '0911223344', '0711223344', '09 11 22 33 44', '(09) 11-22-33-44'
    - International formats: '+251911223344', '+251711223344', '00251911223344', '251911223344'
    - 9-digit formats without leading 0 or +251: '911223344', '711223344'
    
    Returns a standardized dictionary with canonical E.164, local format, tel: URI, and carrier.
    Gracefully handles empty, missing, invalid length, invalid prefix, and non-Ethiopian inputs.
    """
    empty_result: NormalizedPhoneDict = {
        "is_valid": False,
        "is_ethiopian": False,
        "is_mobile": False,
        "carrier": None,
        "phone_number": None,
        "phone_number_local": None,
        "tel_uri": None,
        "error": "Phone number is missing or empty.",
        "raw": phone_input,
    }

    if not phone_input or not str(phone_input).strip():
        return empty_result

    raw = str(phone_input).strip()

    # Strip whitespace, hyphens, brackets, dots, parentheses
    cleaned = re.sub(r'[\s\-\(\)\.]', '', raw)

    # Handle international prefixes: '00251...' or '251...' -> '+251...'
    if cleaned.startswith('00251'):
        cleaned = '+251' + cleaned[5:]
    elif cleaned.startswith('251') and not cleaned.startswith('+'):
        cleaned = '+251' + cleaned[3:]

    # Check for non-Ethiopian international numbers
    if cleaned.startswith('+') and not cleaned.startswith('+251'):
        return {
            "is_valid": False,
            "is_ethiopian": False,
            "is_mobile": False,
            "carrier": None,
            "phone_number": None,
            "phone_number_local": None,
            "tel_uri": None,
            "error": "Phone number does not belong to Ethiopia (+251 country code required).",
            "raw": raw,
        }

    mobile_digits = None

    # Case 1: International format '+251...'
    if cleaned.startswith('+251'):
        remainder = cleaned[4:]
        if not remainder.isdigit():
            return {
                "is_valid": False,
                "is_ethiopian": True,
                "is_mobile": False,
                "carrier": None,
                "phone_number": None,
                "phone_number_local": None,
                "tel_uri": None,
                "error": "Phone number contains non-numeric characters after country code.",
                "raw": raw,
            }
        if len(remainder) != 9:
            return {
                "is_valid": False,
                "is_ethiopian": True,
                "is_mobile": False,
                "carrier": None,
                "phone_number": None,
                "phone_number_local": None,
                "tel_uri": None,
                "error": f"Invalid Ethiopian phone number length. Expected 9 digits after +251, got {len(remainder)}.",
                "raw": raw,
            }
        mobile_digits = remainder

    # Case 2: Local format starting with '0...'
    elif cleaned.startswith('0'):
        remainder = cleaned[1:]
        if not remainder.isdigit():
            return {
                "is_valid": False,
                "is_ethiopian": True,
                "is_mobile": False,
                "carrier": None,
                "phone_number": None,
                "phone_number_local": None,
                "tel_uri": None,
                "error": "Phone number contains non-numeric characters.",
                "raw": raw,
            }
        if len(remainder) != 9:
            return {
                "is_valid": False,
                "is_ethiopian": True,
                "is_mobile": False,
                "carrier": None,
                "phone_number": None,
                "phone_number_local": None,
                "tel_uri": None,
                "error": f"Invalid local phone number length. Expected 10 digits starting with 0, got {len(cleaned)}.",
                "raw": raw,
            }
        mobile_digits = remainder

    # Case 3: 9 digits without leading 0 or +251
    elif len(cleaned) == 9 and cleaned.isdigit():
        mobile_digits = cleaned

    else:
        return {
            "is_valid": False,
            "is_ethiopian": False,
            "is_mobile": False,
            "carrier": None,
            "phone_number": None,
            "phone_number_local": None,
            "tel_uri": None,
            "error": f"Invalid phone number format: '{raw}'.",
            "raw": raw,
        }

    # Inspect mobile prefix: Ethio Telecom (9) or Safaricom Ethiopia (7)
    prefix = mobile_digits[0]
    if prefix == '9':
        carrier = ETHIO_TELECOM_CARRIER
    elif prefix == '7':
        carrier = SAFARICOM_CARRIER
    elif prefix == '1':
        # Addis Ababa / regional fixed line (e.g. 011...)
        return {
            "is_valid": False,
            "is_ethiopian": True,
            "is_mobile": False,
            "carrier": ETHIO_TELECOM_CARRIER,
            "phone_number": f"+251{mobile_digits}",
            "phone_number_local": f"0{mobile_digits}",
            "tel_uri": f"tel:+251{mobile_digits}",
            "error": "This is an Ethiopian landline/fixed number. Midwife consultations require a mobile number (09 or 07).",
            "raw": raw,
        }
    else:
        return {
            "is_valid": False,
            "is_ethiopian": True,
            "is_mobile": False,
            "carrier": None,
            "phone_number": None,
            "phone_number_local": None,
            "tel_uri": None,
            "error": f"Invalid Ethiopian mobile prefix '0{prefix}'. Mobile numbers must start with 09 (Ethio Telecom) or 07 (Safaricom Ethiopia).",
            "raw": raw,
        }

    e164 = f"+251{mobile_digits}"
    local = f"0{mobile_digits}"
    tel_uri = f"tel:{e164}"

    return {
        "is_valid": True,
        "is_ethiopian": True,
        "is_mobile": True,
        "carrier": carrier,
        "phone_number": e164,
        "phone_number_local": local,
        "tel_uri": tel_uri,
        "error": None,
        "raw": raw,
    }


def format_tel_uri(phone_input: Optional[str]) -> Optional[str]:
    """
    Returns RFC 3966 'tel:' URI for valid Ethiopian numbers, or None if invalid.
    """
    res = normalize_ethiopian_phone(phone_input)
    return res["tel_uri"] if res["is_valid"] else None
