from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.notifications.call_notifications import send_general_push_notification


def _format_appointment_info(appointment):
    raw_type = appointment.appointment_type
    if raw_type == 'IN_PERSON':
        type_str = "In-Person"
    elif raw_type == 'VIRTUAL_VOICE':
        type_str = "Voice Call"
    elif raw_type == 'VIRTUAL_VIDEO':
        type_str = "Video Call"
    else:
        type_str = appointment.get_appointment_type_display()

    today = timezone.localdate()
    apt_date = appointment.scheduled_date
    if apt_date == today:
        date_str = "Today"
    elif apt_date == today + timedelta(days=1):
        date_str = "Tomorrow"
    else:
        date_str = apt_date.strftime("%a, %b %d")

    time_str = appointment.start_time.strftime("%I:%M %p").lstrip('0') if appointment.start_time else ""

    patient_name = appointment.user.get_full_name() or appointment.user.username
    if appointment.midwife and appointment.midwife.user:
        midwife_name = appointment.midwife.user.get_full_name() or appointment.midwife.user.username
    else:
        midwife_name = "Midwife"

    return type_str, date_str, time_str, patient_name, midwife_name


@shared_task
def send_automated_appointment_reminders():
    """
    Automated Celery background task for sending appointment reminders.
    Triggered periodically to send 24-hour and 1-hour advance reminders to both Patient and Midwife.
    """
    now = timezone.now()
    today_date = now.date()

    # 1. 24-Hour Advance Reminders
    target_24h_date = (now + timedelta(days=1)).date()
    upcoming_24h = Appointment.objects.filter(
        scheduled_date=target_24h_date,
        status__in=[Appointment.AppointmentStatus.CONFIRMED, Appointment.AppointmentStatus.PENDING],
    )

    reminders_sent = 0

    for apt in upcoming_24h:
        type_str, date_str, time_str, patient_name, midwife_name = _format_appointment_info(apt)

        title_pat = "Upcoming Appointment Reminder ⏰"
        body_pat = f"Reminder: You have an {type_str} consultation with Midwife {midwife_name} tomorrow at {time_str}."

        notif_pat, created_pat = Notification.objects.get_or_create(
            user=apt.user,
            type="APPOINTMENT_REMINDER_24H",
            reference_id=str(apt.id),
            defaults={
                "title": title_pat,
                "body": body_pat,
                "action": "REMINDER_24H",
            }
        )
        if created_pat:
            send_general_push_notification(
                user=apt.user,
                title=title_pat,
                body=body_pat,
                extra_data={"type": "REMINDER_24H", "appointment_id": str(apt.id)},
            )

        # Midwife Reminder
        if apt.midwife and apt.midwife.user:
            title_mw = "Upcoming Consultation Reminder ⏰"
            body_mw = f"Reminder: You have an {type_str} consultation with {patient_name} tomorrow at {time_str}."

            notif_mw, created_mw = Notification.objects.get_or_create(
                user=apt.midwife.user,
                type="APPOINTMENT_REMINDER_24H",
                reference_id=str(apt.id),
                defaults={
                    "title": title_mw,
                    "body": body_mw,
                    "action": "REMINDER_24H",
                }
            )
            if created_mw:
                send_general_push_notification(
                    user=apt.midwife.user,
                    title=title_mw,
                    body=body_mw,
                    extra_data={"type": "REMINDER_24H", "appointment_id": str(apt.id)},
                )
        reminders_sent += 1

    # 2. 1-Hour Advance Reminders (for today's appointments)
    current_time = now.time()
    one_hour_later_time = (now + timedelta(hours=1)).time()

    today_1h = Appointment.objects.filter(
        scheduled_date=today_date,
        status__in=[Appointment.AppointmentStatus.CONFIRMED, Appointment.AppointmentStatus.PENDING],
        start_time__gte=current_time,
        start_time__lte=one_hour_later_time,
    )

    for apt in today_1h:
        type_str, date_str, time_str, patient_name, midwife_name = _format_appointment_info(apt)

        title_pat = "Consultation Starting Soon ⏰"
        body_pat = f"Reminder: Your {type_str} consultation with Midwife {midwife_name} starts in less than an hour at {time_str}."

        notif_pat, created_pat = Notification.objects.get_or_create(
            user=apt.user,
            type="APPOINTMENT_REMINDER_1H",
            reference_id=str(apt.id),
            defaults={
                "title": title_pat,
                "body": body_pat,
                "action": "REMINDER_1H",
            }
        )
        if created_pat:
            send_general_push_notification(
                user=apt.user,
                title=title_pat,
                body=body_pat,
                extra_data={"type": "REMINDER_1H", "appointment_id": str(apt.id)},
            )

        # Midwife Reminder
        if apt.midwife and apt.midwife.user:
            title_mw = "Consultation Starting Soon ⏰"
            body_mw = f"Reminder: Your {type_str} consultation with {patient_name} starts in less than an hour at {time_str}."

            notif_mw, created_mw = Notification.objects.get_or_create(
                user=apt.midwife.user,
                type="APPOINTMENT_REMINDER_1H",
                reference_id=str(apt.id),
                defaults={
                    "title": title_mw,
                    "body": body_mw,
                    "action": "REMINDER_1H",
                }
            )
            if created_mw:
                send_general_push_notification(
                    user=apt.midwife.user,
                    title=title_mw,
                    body=body_mw,
                    extra_data={"type": "REMINDER_1H", "appointment_id": str(apt.id)},
                )
        reminders_sent += 1

    return f"Processed automated appointment reminders. Sent {reminders_sent} reminder batches."
