import logging
from datetime import datetime
from typing import Optional, Any
from django.utils import timezone
from apps.common.phone_utils import normalize_ethiopian_phone, ETHIO_TELECOM_CARRIER, SAFARICOM_CARRIER

logger = logging.getLogger(__name__)

# Ethiopia is strictly in East Africa Time (EAT, UTC+3) without daylight saving adjustments
try:
    import zoneinfo
    EAT_TIMEZONE = zoneinfo.ZoneInfo("Africa/Addis_Ababa")
except Exception:
    from datetime import timezone as dt_timezone, timedelta as dt_timedelta
    EAT_TIMEZONE = dt_timezone(dt_timedelta(hours=3), name="EAT")


class AppointmentCallService:
    """
    Authoritative service for managing SIM-based phone calling between Patients and Midwives.
    
    Enforces:
    - Appointment ownership & participation permissions (Patient, assigned Midwife, or Admin)
    - Appointment confirmation status (must be CONFIRMED)
    - Ethiopia Time (EAT, UTC+3) scheduled appointment call window (start_time to end_time)
    - Midwife phone number validation for both Ethio Telecom (09...) and Safaricom Ethiopia (07...)
    - Privacy protection: Never discloses phone number or tel: URI until all eligibility checks pass
    - Graceful messages for cancelled, pending, expired, before-window, or missing phone scenarios
    """

    @classmethod
    def get_eat_now(cls) -> datetime:
        """Returns the current instant converted to Ethiopia Local Time (EAT, UTC+3)."""
        return timezone.now().astimezone(EAT_TIMEZONE)

    @classmethod
    def get_display_name(cls, user) -> str:
        if not user:
            return ""
        if hasattr(user, 'profile') and user.profile:
            fn = getattr(user.profile, 'first_name', '').strip()
            ln = getattr(user.profile, 'last_name', '').strip()
            if fn or ln:
                return f"{fn} {ln}".strip()
        if hasattr(user, 'first_name') and (getattr(user, 'first_name', '') or getattr(user, 'last_name', '')):
            fn = getattr(user, 'first_name', '').strip()
            ln = getattr(user, 'last_name', '').strip()
            if fn or ln:
                return f"{fn} {ln}".strip()
        return getattr(user, 'username', '') or ""

    @classmethod
    def calculate_call_window(cls, appointment) -> dict:
        """
        Calculates the start and end of the scheduled appointment window in Ethiopia Time (EAT).
        Compares with the current EAT time to determine whether the call window is active, pending, or expired.
        """
        now_eat = cls.get_eat_now()
        target_date = appointment.scheduled_date
        start_time = appointment.start_time
        end_time = appointment.end_time

        start_dt_eat = datetime.combine(target_date, start_time).replace(tzinfo=EAT_TIMEZONE)
        end_dt_eat = datetime.combine(target_date, end_time).replace(tzinfo=EAT_TIMEZONE)

        if now_eat < start_dt_eat:
            window_state = "BEFORE_WINDOW"
            is_active = False
            seconds_until = max(0, int((start_dt_eat - now_eat).total_seconds()))
            seconds_remaining = 0
        elif now_eat > end_dt_eat:
            window_state = "EXPIRED_WINDOW"
            is_active = False
            seconds_until = 0
            seconds_remaining = 0
        else:
            window_state = "ACTIVE_WINDOW"
            is_active = True
            seconds_until = 0
            seconds_remaining = max(0, int((end_dt_eat - now_eat).total_seconds()))

        return {
            "window_state": window_state,
            "is_call_window_active": is_active,
            "current_time_eat": now_eat,
            "start_time_eat": start_dt_eat,
            "end_time_eat": end_dt_eat,
            "seconds_until_window": seconds_until,
            "seconds_remaining": seconds_remaining,
        }

    @classmethod
    def check_call_eligibility(cls, appointment, user, request=None) -> dict:
        """
        Comprehensive eligibility and call-access resolver.
        
        Evaluates:
        1. User ownership: Patient who booked the appointment, assigned Midwife, or Admin/Staff.
        2. Appointment status: Must be CONFIRMED.
        3. Scheduled call window in EAT (Africa/Addis_Ababa).
        4. Midwife phone number: Ethio Telecom or Safaricom Ethiopia normalization.
        
        Returns a dictionary suitable for API responses and serializer inclusion.
        If can_call is False, phone_number and tel_uri are set to None for data privacy.
        """
        # 1. Authorization check
        user_id_str = str(getattr(user, 'id', ''))
        patient_id_str = str(getattr(appointment, 'user_id', ''))
        
        midwife_user = None
        if appointment.midwife and hasattr(appointment.midwife, 'user') and appointment.midwife.user:
            midwife_user = appointment.midwife.user
        midwife_user_id_str = str(midwife_user.id) if midwife_user else ""
        
        is_patient = (user_id_str == patient_id_str)
        is_assigned_midwife = (
            (hasattr(user, 'midwife_profile') and appointment.midwife_id == user.midwife_profile.id) or
            (midwife_user_id_str != "" and user_id_str == midwife_user_id_str)
        )
        is_admin = bool(getattr(user, 'is_staff', False) or getattr(user, 'role', '') == 'ADMIN')

        is_authorized = bool(is_patient or is_assigned_midwife or is_admin)

        # 2. Window calculation in EAT
        win_info = cls.calculate_call_window(appointment)
        now_eat = win_info["current_time_eat"]
        start_eat = win_info["start_time_eat"]
        end_eat = win_info["end_time_eat"]
        window_state = win_info["window_state"]
        is_window_active = win_info["is_call_window_active"]

        # 3. Midwife phone number lookup and normalization
        raw_phone = None
        if midwife_user and getattr(midwife_user, 'phone_number', None):
            raw_phone = midwife_user.phone_number
        elif appointment.midwife and getattr(appointment.midwife, 'hospital', None):
            raw_phone = getattr(appointment.midwife.hospital, 'phone', None)

        phone_res = normalize_ethiopian_phone(raw_phone)
        has_phone = bool(raw_phone and str(raw_phone).strip())
        is_phone_valid = phone_res["is_valid"]

        # 4. Status eligibility
        from apps.appointments.models import Appointment
        status_confirmed = (appointment.status == Appointment.AppointmentStatus.CONFIRMED)

        # 5. Master can_call determination
        can_call = bool(
            is_authorized and
            status_confirmed and
            is_window_active and
            is_phone_valid
        )

        # 6. User-friendly reason and message formulation
        date_str = appointment.scheduled_date.strftime("%b %d, %Y")
        start_12h = appointment.start_time.strftime("%I:%M %p").lstrip('0') if appointment.start_time else ""
        end_12h = appointment.end_time.strftime("%I:%M %p").lstrip('0') if appointment.end_time else ""

        midwife_name = cls.get_display_name(midwife_user) or "Midwife"
        patient_name = cls.get_display_name(appointment.user) or "Patient"

        reason = None
        if not is_authorized:
            reason = "You do not have permission to access call details for this appointment."
            message = reason
        elif appointment.status == Appointment.AppointmentStatus.CANCELLED:
            reason = "This appointment has been cancelled. Calling is unavailable."
            message = reason
        elif appointment.status == Appointment.AppointmentStatus.PENDING:
            reason = "This appointment is pending confirmation by the midwife. Calling will be enabled once confirmed."
            message = reason
        elif appointment.status == Appointment.AppointmentStatus.COMPLETED:
            reason = "This appointment has already been completed."
            message = reason
        elif appointment.status in [Appointment.AppointmentStatus.REJECTED, Appointment.AppointmentStatus.MISSED]:
            reason = f"This appointment was marked as {appointment.status.lower()}."
            message = reason
        elif window_state == "BEFORE_WINDOW":
            reason = f"Appointment call window has not started yet. The Call Midwife button will be enabled during your scheduled window ({start_12h} - {end_12h} EAT)."
            message = reason
        elif window_state == "EXPIRED_WINDOW":
            reason = f"The scheduled appointment call window ended at {end_12h} EAT on {date_str}."
            message = reason
        elif not has_phone:
            reason = "The midwife has not registered a contact phone number yet. Please contact support or use in-app messaging."
            message = reason
        elif not is_phone_valid:
            reason = f"The midwife's registered phone number format is invalid: {phone_res['error']}"
            message = reason
        else:
            carrier_name = phone_res['carrier'] or "mobile network"
            message = f"Call window is active until {end_12h} EAT. Tap 'Call Midwife' to open dialer via {carrier_name}."

        # 7. Privacy protection: Disclose actual phone number and tel: URI ONLY when can_call is True
        # (or when requested by staff / assigned midwife for administrative purposes)
        disclose_phone = bool(can_call or (is_authorized and (is_admin or is_assigned_midwife) and is_phone_valid))

        phone_number = phone_res["phone_number"] if disclose_phone else None
        phone_local = phone_res["phone_number_local"] if disclose_phone else None
        tel_uri = phone_res["tel_uri"] if disclose_phone else None
        carrier = phone_res["carrier"] if (disclose_phone or is_phone_valid) else None

        return {
            "appointment_id": str(appointment.id),
            "appointment_number": appointment.appointment_number,
            "status": appointment.status,
            "can_call": can_call,
            "is_call_window_active": is_window_active,
            "window_state": window_state,
            "is_authorized": is_authorized,
            "phone_number": phone_number,
            "phone_number_local": phone_local,
            "tel_uri": tel_uri,
            "carrier": carrier,
            "midwife_name": midwife_name,
            "patient_name": patient_name,
            "message": message,
            "reason": reason,
            "scheduled_date": str(appointment.scheduled_date),
            "start_time": appointment.start_time.strftime("%H:%M:%S") if appointment.start_time else None,
            "end_time": appointment.end_time.strftime("%H:%M:%S") if appointment.end_time else None,
            "start_time_12h": start_12h,
            "end_time_12h": end_12h,
            "timezone": "Africa/Addis_Ababa",
            "current_time_eat": now_eat.isoformat(),
            "start_time_eat": start_eat.isoformat(),
            "end_time_eat": end_eat.isoformat(),
            "seconds_until_window": win_info["seconds_until_window"],
            "seconds_remaining": win_info["seconds_remaining"],
            "privacy_limitation_notice": (
                "Normal SIM phone calls do not hide phone numbers. "
                "The midwife's phone number may appear in your dialer and call history, "
                "and your registered number may be visible to the midwife via caller ID."
            ),
        }
