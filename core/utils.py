from .models import SMSLog
from django.utils import timezone

def send_sms(farmer, message, allocation=None):
    """Simulate SMS sending - in production connect to Africa's Talking or Twilio"""
    log = SMSLog.objects.create(
        farmer=farmer,
        phone_number=farmer.phone_number,
        message=message,
        allocation=allocation,
        status='sent',
        sent_at=timezone.now()
    )
    # In production, integrate with Africa's Talking:
    # import africastalking
    # africastalking.initialize(username, api_key)
    # sms = africastalking.SMS
    # response = sms.send(message, [farmer.phone_number])
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
