from decimal import Decimal
from django.db.models import Sum
from .models import SeedInventory, StockTransfer, SeedAllocation

ALLOCATION_RESERVED_STATUSES = ('pending', 'approved', 'distributed')


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))['t'] or Decimal('0')


def region_balance(seed_type, region):
    if region is None:
        return Decimal('0')
    received = _sum(SeedInventory.objects.filter(seed_type=seed_type, region=region), 'quantity')
    sent = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='region_to_district', from_region=region, status='approved'), 'quantity')
    return received - sent


def district_balance(seed_type, district):
    if district is None:
        return Decimal('0')
    received = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='region_to_district', to_district=district, status='approved'), 'quantity')
    sent = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='district_to_ward', from_district=district, status='approved'), 'quantity')
    return received - sent


def ward_balance(seed_type, ward):
    if ward is None:
        return Decimal('0')
    received = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='district_to_ward', to_ward=ward, status='approved'), 'quantity')
    sent = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='ward_to_village', from_ward=ward, status='approved'), 'quantity')
    return received - sent


def village_balance(seed_type, village):
    if village is None:
        return Decimal('0')
    received = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='ward_to_village', to_village=village, status='approved'), 'quantity')
    allocated = _sum(SeedAllocation.objects.filter(seed_type=seed_type, farmer__village=village, status__in=ALLOCATION_RESERVED_STATUSES), 'quantity_allocated')
    return received - allocated


BALANCE_FN_BY_ROLE = {
    'regional': lambda seed_type, user: region_balance(seed_type, user.region),
    'district': lambda seed_type, user: district_balance(seed_type, user.district),
    'ward': lambda seed_type, user: ward_balance(seed_type, user.ward),
    'village': lambda seed_type, user: village_balance(seed_type, user.village),
}


def balance_for_user(seed_type, user):
    fn = BALANCE_FN_BY_ROLE.get(user.role)
    return fn(seed_type, user) if fn else Decimal('0')


LOCATION_LABEL_BY_ROLE = {
    'regional': ('Region', 'region'),
    'district': ('District', 'district'),
    'ward': ('Ward', 'ward'),
    'village': ('Village', 'village'),
}


def location_for_user(user):
    """Returns (level_label, location_obj) for the officer's own node, or (None, None)."""
    entry = LOCATION_LABEL_BY_ROLE.get(user.role)
    if not entry:
        return None, None
    label, attr = entry
    return label, getattr(user, attr)
