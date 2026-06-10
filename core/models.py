from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

class Region(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class District(models.Model):
    name = models.CharField(max_length=100)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='districts')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"{self.name} ({self.region})"

class Ward(models.Model):
    name = models.CharField(max_length=100)
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='wards')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"{self.name} ({self.district})"

class Village(models.Model):
    name = models.CharField(max_length=100)
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='villages')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"{self.name} ({self.ward})"

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'System Administrator'),
        ('regional', 'Regional Officer'),
        ('district', 'District Officer'),
        ('ward', 'Ward Officer'),
        ('village', 'Village Officer'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='village')
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True)
    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, blank=True)
    village = models.ForeignKey(Village, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self): return f"{self.get_full_name()} ({self.role})"

class SeedType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=30, default='kg')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class SeedInventory(models.Model):
    seed_type = models.ForeignKey(SeedType, on_delete=models.CASCADE, related_name='inventory')
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    date_received = models.DateField()
    source = models.CharField(max_length=200, blank=True)
    region = models.ForeignKey(Region, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True)
    added_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"{self.seed_type} - {self.quantity} {self.seed_type.unit}"

SEASON_CHOICES = [
    ('long_rains_2024', 'Long Rains 2024'),
    ('short_rains_2024', 'Short Rains 2024'),
    ('long_rains_2025', 'Long Rains 2025'),
    ('short_rains_2025', 'Short Rains 2025'),
]

class FarmingSeasons(models.Model):
    name = models.CharField(max_length=100, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

CROP_CHOICES = [
    ('maize', 'Maize'), ('rice', 'Rice'), ('beans', 'Beans'),
    ('sunflower', 'Sunflower'), ('sorghum', 'Sorghum'), ('millet', 'Millet'),
    ('wheat', 'Wheat'), ('cassava', 'Cassava'), ('other', 'Other'),
]

class Farmer(models.Model):
    STATUS_CHOICES = [('active','Active'),('inactive','Inactive'),('pending','Pending')]
    farmer_id = models.CharField(max_length=20, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20)
    village = models.ForeignKey(Village, on_delete=models.CASCADE, related_name='farmers')
    farm_location = models.CharField(max_length=200, blank=True)
    farm_size = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text='Acres')
    crop_type = models.CharField(max_length=50, choices=CROP_CHOICES, default='maize')
    national_id = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    registered_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='registered_farmers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.farmer_id:
            import random, string
            self.farmer_id = 'F' + ''.join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)

    def __str__(self): return f"{self.first_name} {self.last_name} ({self.farmer_id})"

    @property
    def full_name(self): return f"{self.first_name} {self.last_name}"

    @property
    def ward(self): return self.village.ward

    @property
    def district(self): return self.village.ward.district

    @property
    def region(self): return self.village.ward.district.region

class SeedAllocation(models.Model):
    STATUS_CHOICES = [
        ('pending','Pending'),('approved','Approved'),
        ('rejected','Rejected'),('distributed','Distributed'),
    ]
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name='allocations')
    seed_type = models.ForeignKey(SeedType, on_delete=models.CASCADE)
    season = models.ForeignKey(FarmingSeasons, on_delete=models.CASCADE)
    quantity_allocated = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    collection_date = models.DateField(null=True, blank=True)
    collection_location = models.CharField(max_length=200, blank=True)
    requested_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='requests')
    approved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approvals')
    rejection_reason = models.TextField(blank=True)
    sms_sent = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('farmer', 'seed_type', 'season')

    def __str__(self): return f"{self.farmer} - {self.seed_type} ({self.season})"

class Distribution(models.Model):
    allocation = models.OneToOneField(SeedAllocation, on_delete=models.CASCADE, related_name='distribution')
    quantity_distributed = models.DecimalField(max_digits=10, decimal_places=2)
    collection_date = models.DateField(default=timezone.now)
    collection_confirmed = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmations')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): return f"Distribution: {self.allocation}"

class SMSLog(models.Model):
    STATUS_CHOICES = [('sent','Sent'),('failed','Failed'),('pending','Pending')]
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name='sms_logs')
    phone_number = models.CharField(max_length=20)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    allocation = models.ForeignKey(SeedAllocation, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): return f"SMS to {self.phone_number} - {self.status}"

class ActivityLog(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=200)
    model_name = models.CharField(max_length=50, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): return f"{self.user} - {self.action}"
