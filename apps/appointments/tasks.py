from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.notifications.call_notifications import send_general_push_notification


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
        title_pat = "Upcoming Appointment Reminder (24 Hours)"
        body_pat = f"Reminder: You have an appointment ({apt.appointment_number}) tomorrow at {apt.start_time.strftime('%H:%M')}."

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
            title_mw = "Midwife Appointment Reminder (24 Hours)"
            body_mw = f"Reminder: You have an appointment ({apt.appointment_number}) with {apt.user.username} tomorrow at {apt.start_time.strftime('%H:%M')}."

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
        title_pat = "Appointment Reminder (1 Hour)"
        body_pat = f"Reminder: Your consultation ({apt.appointment_number}) starts in less than an hour at {apt.start_time.strftime('%H:%M')}."

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
            title_mw = "Midwife Consultation Starting Soon (1 Hour)"
            body_mw = f"Reminder: Consultation ({apt.appointment_number}) with {apt.user.username} starts at {apt.start_time.strftime('%H:%M')}."

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
