import os
from .models import SMSLog
from django.utils import timezone

AT_USERNAME = os.environ.get('AFRICASTALKING_USERNAME')
AT_API_KEY = os.environ.get('AFRICASTALKING_API_KEY')
AT_SENDER_ID = os.environ.get('AFRICASTALKING_SENDER_ID')


def _normalize_phone(phone):
    """Africa's Talking expects E.164. Local numbers are stored as 07XXXXXXXX (Tanzania)."""
    phone = phone.strip().replace(' ', '')
    if phone.startswith('0') and len(phone) == 10:
        return '+255' + phone[1:]
    if phone.startswith('+'):
        return phone
    return phone


def _send_via_africastalking(phone, message):
    import africastalking
    africastalking.initialize(AT_USERNAME, AT_API_KEY)
    sms = africastalking.SMS
    kwargs = {'sender_id': AT_SENDER_ID} if AT_SENDER_ID else {}
    response = sms.send(message, [phone], **kwargs)
    recipients = response.get('SMSMessageData', {}).get('Recipients', [])
    if recipients and recipients[0].get('status') == 'Success':
        return 'sent', ''
    error = recipients[0].get('status') if recipients else str(response)
    return 'failed', error


def send_sms(farmer, message, allocation=None):
    """Sends via Africa's Talking when AFRICASTALKING_USERNAME/API_KEY are set in the
    environment; otherwise simulates (dev default - no credentials required)."""
    phone = _normalize_phone(farmer.phone_number)
    if AT_USERNAME and AT_API_KEY:
        try:
            status, error = _send_via_africastalking(phone, message)
        except Exception as e:
            status, error = 'failed', str(e)
    else:
        status, error = 'sent', ''
    log = SMSLog.objects.create(
        farmer=farmer,
        phone_number=phone,
        message=message,
        allocation=allocation,
        status=status,
        sent_at=timezone.now() if status == 'sent' else None,
        error_message=error,
    )
    return log

def send_allocation_sms(allocation):
    msg = (
        f"Dear {allocation.farmer.full_name}, your seed allocation has been APPROVED. "
        f"Seed: {allocation.seed_type.name}, Quantity: {allocation.quantity_allocated} {allocation.seed_type.unit}. "
        f"Collection: {allocation.collection_location} on {allocation.collection_date}. "
        f"Reference: {allocation.farmer.farmer_id}. - Mbeya Seed Programme"
    )
    log = send_sms(allocation.farmer, msg, allocation)
    allocation.sms_sent = True
    allocation.save(update_fields=['sms_sent'])
    return log
