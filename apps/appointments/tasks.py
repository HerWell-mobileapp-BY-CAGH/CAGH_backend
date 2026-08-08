from datetime import timedelta
from django.utils import timezone
from celery import shared_task
from apps.appointments.models import Appointment
from apps.notifications.models import Notification


@shared_task
def send_automated_appointment_reminders():
    """
    FR-013: Automated Celery background task for sending appointment reminders.
    Triggered periodically (e.g. every 15 mins).
    Sends 24-hour and 1-hour advance reminders to both Patient and Midwife.
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
        # Patient Reminder
        Notification.objects.get_or_create(
            user=apt.user,
            type="APPOINTMENT_REMINDER_24H",
            reference_id=str(apt.id),
            defaults={
                "title": "Upcoming Appointment Reminder (24 Hours)",
                "body": f"Reminder: You have an appointment ({apt.appointment_number}) tomorrow at {apt.start_time.strftime('%H:%M')}.",
                "action": "REMINDER_24H",
            }
        )

        # Midwife Reminder
        if apt.midwife and apt.midwife.user:
            Notification.objects.get_or_create(
                user=apt.midwife.user,
                type="APPOINTMENT_REMINDER_24H",
                reference_id=str(apt.id),
                defaults={
                    "title": "Midwife Appointment Reminder (24 Hours)",
                    "body": f"Reminder: You have an appointment ({apt.appointment_number}) with {apt.user.username} tomorrow at {apt.start_time.strftime('%H:%M')}.",
                    "action": "REMINDER_24H",
                }
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
        # Patient Reminder
        Notification.objects.get_or_create(
            user=apt.user,
            type="APPOINTMENT_REMINDER_1H",
            reference_id=str(apt.id),
            defaults={
                "title": "Appointment Reminder (1 Hour)",
                "body": f"Reminder: Your consultation ({apt.appointment_number}) starts in less than an hour at {apt.start_time.strftime('%H:%M')}.",
                "action": "REMINDER_1H",
            }
        )

        # Midwife Reminder
        if apt.midwife and apt.midwife.user:
            Notification.objects.get_or_create(
                user=apt.midwife.user,
                type="APPOINTMENT_REMINDER_1H",
                reference_id=str(apt.id),
                defaults={
                    "title": "Midwife Consultation Starting Soon (1 Hour)",
                    "body": f"Reminder: Consultation ({apt.appointment_number}) with {apt.user.username} starts at {apt.start_time.strftime('%H:%M')}.",
                    "action": "REMINDER_1H",
                }
            )
        reminders_sent += 1

    return f"Processed automated appointment reminders. Sent {reminders_sent} reminder batches."
