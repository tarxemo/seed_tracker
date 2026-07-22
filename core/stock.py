from decimal import Decimal
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _
from .models import SeedInventory, StockTransfer, SeedAllocation, SeedType

ALLOCATION_RESERVED_STATUSES = ('pending', 'approved', 'distributed')


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))['t'] or Decimal('0')


def region_received(seed_type, region):
    if region is None:
        return Decimal('0')
    return _sum(SeedInventory.objects.filter(seed_type=seed_type, region=region), 'quantity')


def district_received(seed_type, district):
    if district is None:
        return Decimal('0')
    return _sum(StockTransfer.objects.filter(seed_type=seed_type, level='region_to_district', to_district=district, status='approved'), 'quantity')


def ward_received(seed_type, ward):
    if ward is None:
        return Decimal('0')
    return _sum(StockTransfer.objects.filter(seed_type=seed_type, level='district_to_ward', to_ward=ward, status='approved'), 'quantity')


def village_received(seed_type, village):
    if village is None:
        return Decimal('0')
    return _sum(StockTransfer.objects.filter(seed_type=seed_type, level='ward_to_village', to_village=village, status='approved'), 'quantity')


def region_balance(seed_type, region):
    if region is None:
        return Decimal('0')
    sent = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='region_to_district', from_region=region, status='approved'), 'quantity')
    return region_received(seed_type, region) - sent


def district_balance(seed_type, district):
    if district is None:
        return Decimal('0')
    sent = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='district_to_ward', from_district=district, status='approved'), 'quantity')
    return district_received(seed_type, district) - sent


def ward_balance(seed_type, ward):
    if ward is None:
        return Decimal('0')
    sent = _sum(StockTransfer.objects.filter(seed_type=seed_type, level='ward_to_village', from_ward=ward, status='approved'), 'quantity')
    return ward_received(seed_type, ward) - sent


def village_balance(seed_type, village):
    if village is None:
        return Decimal('0')
    allocated = _sum(SeedAllocation.objects.filter(seed_type=seed_type, farmer__village=village, status__in=ALLOCATION_RESERVED_STATUSES), 'quantity_allocated')
    return village_received(seed_type, village) - allocated


BALANCE_FN_BY_ROLE = {
    'regional': lambda seed_type, user: region_balance(seed_type, user.region),
    'district': lambda seed_type, user: district_balance(seed_type, user.district),
    'ward': lambda seed_type, user: ward_balance(seed_type, user.ward),
    'village': lambda seed_type, user: village_balance(seed_type, user.village),
}

RECEIVED_FN_BY_ROLE = {
    'regional': lambda seed_type, user: region_received(seed_type, user.region),
    'district': lambda seed_type, user: district_received(seed_type, user.district),
    'ward': lambda seed_type, user: ward_received(seed_type, user.ward),
    'village': lambda seed_type, user: village_received(seed_type, user.village),
}


def balance_for_user(seed_type, user):
    fn = BALANCE_FN_BY_ROLE.get(user.role)
    return fn(seed_type, user) if fn else Decimal('0')


def received_for_user(seed_type, user):
    fn = RECEIVED_FN_BY_ROLE.get(user.role)
    return fn(seed_type, user) if fn else Decimal('0')


def total_balance_for_user(user):
    return sum((balance_for_user(st, user) for st in SeedType.objects.all()), Decimal('0'))


def total_received_for_user(user):
    return sum((received_for_user(st, user) for st in SeedType.objects.all()), Decimal('0'))


LOCATION_LABEL_BY_ROLE = {
    'regional': (_('Region'), 'region'),
    'district': (_('District'), 'district'),
    'ward': (_('Ward'), 'ward'),
    'village': (_('Village'), 'village'),
}


def location_for_user(user):
    """Returns (level_label, location_obj) for the officer's own node, or (None, None)."""
    entry = LOCATION_LABEL_BY_ROLE.get(user.role)
    if not entry:
        return None, None
    label, attr = entry
    return label, getattr(user, attr)


def lock_user_location(user):
    """Locks the officer's own location row for the duration of the enclosing transaction.atomic()
    block, so concurrent balance-check-then-write operations on that location serialize.
    Must be called inside transaction.atomic(). No-op if the role has no fixed location."""
    _, location = location_for_user(user)
    if location is not None:
        type(location).objects.select_for_update().get(pk=location.pk)
