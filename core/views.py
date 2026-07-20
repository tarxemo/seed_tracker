from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db import transaction
import json, csv
from datetime import timedelta
from .models import *
from .forms import *
from .decorators import role_required, user_can_access_farmer, farmer_required
from .utils import send_allocation_sms
from .stock import balance_for_user, location_for_user, village_balance, total_balance_for_user, total_received_for_user, lock_user_location

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        ActivityLog.objects.create(user=user, action='User logged in', ip_address=request.META.get('REMOTE_ADDR'))
        return redirect('dashboard')
    return render(request, 'registration/login.html', {'form': form})

@login_required
def logout_view(request):
    ActivityLog.objects.create(user=request.user, action='User logged out', ip_address=request.META.get('REMOTE_ADDR'))
    logout(request)
    return redirect('login')

@login_required
def change_password(request):
    form = ChangePasswordForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        ActivityLog.objects.create(user=user, action='Changed their own password')
        messages.success(request, 'Your password has been changed.')
        return redirect('dashboard')
    return render(request, 'registration/change_password.html', {'form': form})

@login_required
def dashboard(request):
    user = request.user
    if user.role == 'farmer':
        return redirect('farmer_dashboard')
    ctx = {}
    # Stats scoped by role
    farmers_qs = Farmer.objects.all()
    alloc_qs = SeedAllocation.objects.all()
    dist_qs = Distribution.objects.all()
    inv_qs = SeedInventory.objects.all()

    if user.role == 'village':
        farmers_qs = farmers_qs.filter(village=user.village)
        alloc_qs = alloc_qs.filter(farmer__village=user.village)
        dist_qs = dist_qs.filter(allocation__farmer__village=user.village)
        ctx['pending_fulfillments'] = SeedRequest.objects.filter(farmer__village=user.village, status='verified').count()
    elif user.role in ('ward', 'extension'):
        farmers_qs = farmers_qs.filter(village__ward=user.ward)
        alloc_qs = alloc_qs.filter(farmer__village__ward=user.ward)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward=user.ward)
    elif user.role == 'district':
        farmers_qs = farmers_qs.filter(village__ward__district=user.district)
        alloc_qs = alloc_qs.filter(farmer__village__ward__district=user.district)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward__district=user.district)
    elif user.role == 'regional':
        farmers_qs = farmers_qs.filter(village__ward__district__region=user.region)
        alloc_qs = alloc_qs.filter(farmer__village__ward__district__region=user.region)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward__district__region=user.region)
        inv_qs = inv_qs.filter(region=user.region)

    ctx['total_farmers'] = farmers_qs.count()
    ctx['total_allocations'] = alloc_qs.count()
    ctx['approved_allocations'] = alloc_qs.filter(status='approved').count()
    ctx['pending_allocations'] = alloc_qs.filter(status='pending').count()
    ctx['distributed'] = dist_qs.count()
    if user.role in ('district', 'ward', 'village'):
        ctx['total_seeds_received'] = total_balance_for_user(user)
        ctx['stock_label'] = 'Current Stock Balance (kg)'
    elif user.role == 'extension':
        ctx['total_seeds_received'] = SeedRequest.objects.filter(farmer__village__ward=user.ward, status='submitted').count()
        ctx['stock_label'] = 'Pending Seed Requests'
    else:
        ctx['total_seeds_received'] = inv_qs.aggregate(t=Sum('quantity'))['t'] or 0
        ctx['stock_label'] = 'Total Seeds Received (kg)'
    ctx['total_seeds_distributed'] = dist_qs.aggregate(t=Sum('quantity_distributed'))['t'] or 0

    # Chart: allocations by seed type
    seed_alloc = alloc_qs.filter(status__in=['approved','distributed']).values('seed_type__name').annotate(total=Sum('quantity_allocated')).order_by('-total')[:8]
    ctx['seed_alloc_labels'] = json.dumps([x['seed_type__name'] for x in seed_alloc])
    ctx['seed_alloc_data'] = json.dumps([float(x['total']) for x in seed_alloc])

    # Chart: monthly allocations last 6 months
    months = []
    month_counts = []
    for i in range(5, -1, -1):
        d = timezone.now() - timedelta(days=30*i)
        count = alloc_qs.filter(created_at__year=d.year, created_at__month=d.month).count()
        months.append(d.strftime('%b %Y'))
        month_counts.append(count)
    ctx['month_labels'] = json.dumps(months)
    ctx['month_counts'] = json.dumps(month_counts)

    # Chart: farmer crop types
    crops = farmers_qs.values('crop_type').annotate(cnt=Count('id')).order_by('-cnt')
    ctx['crop_labels'] = json.dumps([x['crop_type'] for x in crops])
    ctx['crop_data'] = json.dumps([x['cnt'] for x in crops])

    # Chart: allocation status breakdown
    statuses = alloc_qs.values('status').annotate(cnt=Count('id'))
    status_map = {x['status']: x['cnt'] for x in statuses}
    ctx['status_data'] = json.dumps([
        status_map.get('pending',0), status_map.get('approved',0),
        status_map.get('rejected',0), status_map.get('distributed',0)
    ])

    ctx['recent_activities'] = ActivityLog.objects.order_by('-created_at')[:8]
    ctx['recent_allocations'] = alloc_qs.order_by('-created_at')[:5]
    active_season = FarmingSeasons.objects.filter(is_active=True).first()
    ctx['active_season'] = active_season

    return render(request, 'core/dashboard.html', ctx)

# =================== FARMERS ===================
@login_required
def farmer_list(request):
    user = request.user
    qs = Farmer.objects.select_related('village__ward__district__region')
    if user.role == 'village': qs = qs.filter(village=user.village)
    elif user.role in ('ward','extension'): qs = qs.filter(village__ward=user.ward)
    elif user.role == 'district': qs = qs.filter(village__ward__district=user.district)
    elif user.role == 'regional': qs = qs.filter(village__ward__district__region=user.region)

    q = request.GET.get('q','')
    if q: qs = qs.filter(Q(first_name__icontains=q)|Q(last_name__icontains=q)|Q(farmer_id__icontains=q)|Q(phone_number__icontains=q))
    crop_filter = request.GET.get('crop','')
    if crop_filter: qs = qs.filter(crop_type=crop_filter)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/farmer_list.html', {'page_obj': page, 'q': q, 'crop_filter': crop_filter, 'crop_choices': CROP_CHOICES})

@login_required
def farmer_create(request):
    user = request.user
    if user.role not in ['admin','village','ward','district']:
        messages.error(request, 'No permission.')
        return redirect('farmer_list')
    form = FarmerForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        f = form.save(commit=False)
        f.registered_by = user
        f.save()
        ActivityLog.objects.create(user=user, action=f'Registered farmer {f.full_name}', model_name='Farmer', object_id=f.id)
        messages.success(request, f'Farmer {f.full_name} registered successfully.')
        return redirect('farmer_list')
    return render(request, 'core/farmer_form.html', {'form': form, 'title': 'Register Farmer'})

@login_required
def farmer_edit(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    user = request.user
    if user.role not in ['admin','village','ward','district'] or not user_can_access_farmer(user, farmer):
        messages.error(request, 'You do not have permission to edit this farmer.')
        return redirect('farmer_list')
    form = FarmerForm(request.POST or None, instance=farmer, user=user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Farmer updated.')
        return redirect('farmer_list')
    return render(request, 'core/farmer_form.html', {'form': form, 'title': 'Edit Farmer', 'farmer': farmer})

@login_required
def farmer_detail(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    if not user_can_access_farmer(request.user, farmer):
        messages.error(request, 'You do not have permission to view this farmer.')
        return redirect('farmer_list')
    allocs = farmer.allocations.select_related('seed_type','season').order_by('-created_at')
    return render(request, 'core/farmer_detail.html', {'farmer': farmer, 'allocations': allocs})

# =================== INVENTORY ===================
@login_required
@role_required('regional')
def inventory_list(request):
    user = request.user
    qs = SeedInventory.objects.select_related('seed_type','region','added_by').order_by('-date_received')
    summary_qs = SeedInventory.objects.all()
    if user.role == 'regional':
        qs = qs.filter(region=user.region)
        summary_qs = summary_qs.filter(region=user.region)
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    # Summary by seed type
    summary = summary_qs.values('seed_type__name','seed_type__unit').annotate(total=Sum('quantity')).order_by('-total')
    return render(request, 'core/inventory_list.html', {'page_obj': page, 'summary': summary})

@login_required
@role_required('regional')
def inventory_create(request):
    form = SeedInventoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        inv = form.save(commit=False)
        inv.added_by = request.user
        inv.save()
        ActivityLog.objects.create(user=request.user, action=f'Added inventory: {inv}')
        messages.success(request, 'Inventory added.')
        return redirect('inventory_list')
    return render(request, 'core/inventory_form.html', {'form': form, 'title': 'Add Seed Inventory'})

# =================== ALLOCATIONS ===================
def create_farmer_allocation(farmer, seed_type, season, quantity, collection_date, collection_location, notes, actor):
    """Shared by direct officer creation (allocation_create) and SeedRequest fulfillment.
    Returns (allocation, error_message) - exactly one will be None."""
    with transaction.atomic():
        Village.objects.select_for_update().get(pk=farmer.village_id)
        if SeedAllocation.objects.filter(farmer=farmer, seed_type=seed_type, season=season).exists():
            return None, 'This farmer already has an allocation for this seed type in this season.'
        available = village_balance(seed_type, farmer.village)
        if quantity > available:
            return None, f'Insufficient village stock for {seed_type.name}. Available: {available} {seed_type.unit}. Request more stock from your Ward Officer.'
        a = SeedAllocation.objects.create(
            farmer=farmer, seed_type=seed_type, season=season, quantity_allocated=quantity,
            collection_date=collection_date, collection_location=collection_location, notes=notes,
            requested_by=actor, status='approved', approved_by=actor,
        )
    send_allocation_sms(a)
    ActivityLog.objects.create(user=actor, action=f'Allocated {a.quantity_allocated} {a.seed_type.unit} of {a.seed_type.name} to {a.farmer.full_name}')
    return a, None

@login_required
def allocation_list(request):
    user = request.user
    qs = SeedAllocation.objects.select_related('farmer','seed_type','season','requested_by')
    if user.role == 'village': qs = qs.filter(farmer__village=user.village)
    elif user.role in ('ward','extension'): qs = qs.filter(farmer__village__ward=user.ward)
    elif user.role == 'district': qs = qs.filter(farmer__village__ward__district=user.district)
    elif user.role == 'regional': qs = qs.filter(farmer__village__ward__district__region=user.region)
    elif user.role == 'farmer' and hasattr(user, 'farmer_profile'): qs = qs.filter(farmer=user.farmer_profile)

    status_filter = request.GET.get('status','')
    if status_filter: qs = qs.filter(status=status_filter)
    q = request.GET.get('q','')
    if q: qs = qs.filter(Q(farmer__first_name__icontains=q)|Q(farmer__last_name__icontains=q)|Q(farmer__farmer_id__icontains=q))

    paginator = Paginator(qs.order_by('-created_at'), 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/allocation_list.html', {'page_obj': page, 'status_filter': status_filter, 'q': q})

@login_required
@role_required('village')
def allocation_create(request):
    user = request.user
    form = SeedAllocationForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        a, error = create_farmer_allocation(
            farmer=cd['farmer'], seed_type=cd['seed_type'], season=cd['season'],
            quantity=cd['quantity_allocated'], collection_date=cd['collection_date'],
            collection_location=cd['collection_location'], notes=cd.get('notes',''), actor=user,
        )
        if error:
            messages.error(request, error)
            return render(request, 'core/allocation_form.html', {'form': form, 'title': 'New Seed Allocation'})
        messages.success(request, f'Allocation recorded and SMS sent to {a.farmer.phone_number}.')
        return redirect('allocation_list')
    return render(request, 'core/allocation_form.html', {'form': form, 'title': 'New Seed Allocation'})

@login_required
def allocation_detail(request, pk):
    allocation = get_object_or_404(SeedAllocation, pk=pk)
    if not user_can_access_farmer(request.user, allocation.farmer):
        messages.error(request, 'You do not have permission to view this allocation.')
        return redirect('allocation_list')
    return render(request, 'core/allocation_detail.html', {'allocation': allocation})

# =================== DISTRIBUTION ===================
@login_required
def distribution_list(request):
    user = request.user
    qs = Distribution.objects.select_related('allocation__farmer','allocation__seed_type')
    if user.role == 'village': qs = qs.filter(allocation__farmer__village=user.village)
    elif user.role in ('ward','extension'): qs = qs.filter(allocation__farmer__village__ward=user.ward)
    elif user.role == 'district': qs = qs.filter(allocation__farmer__village__ward__district=user.district)
    elif user.role == 'regional': qs = qs.filter(allocation__farmer__village__ward__district__region=user.region)
    elif user.role == 'farmer' and hasattr(user, 'farmer_profile'): qs = qs.filter(allocation__farmer=user.farmer_profile)
    paginator = Paginator(qs.order_by('-created_at'), 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/distribution_list.html', {'page_obj': page})

@login_required
@role_required('village')
def distribution_record(request, allocation_pk):
    allocation = get_object_or_404(SeedAllocation, pk=allocation_pk, status='approved')
    if not user_can_access_farmer(request.user, allocation.farmer):
        messages.error(request, 'You can only record distributions for farmers in your own village.')
        return redirect('distribution_list')
    if hasattr(allocation, 'distribution'):
        messages.warning(request, 'Distribution already recorded.')
        return redirect('distribution_list')
    form = DistributionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        dist = form.save(commit=False)
        dist.allocation = allocation
        dist.confirmed_by = request.user
        dist.collection_confirmed = True
        dist.save()
        allocation.status = 'distributed'
        allocation.save()
        ActivityLog.objects.create(user=request.user, action=f'Recorded distribution for {allocation.farmer}')
        messages.success(request, 'Distribution recorded.')
        return redirect('distribution_list')
    return render(request, 'core/distribution_form.html', {'form': form, 'allocation': allocation})

# =================== REPORTS ===================
REPORT_BREAKDOWN_BY_ROLE = {
    'admin': ('farmer__village__ward__district__region__name', 'Region'),
    'regional': ('farmer__village__ward__district__name', 'District'),
    'district': ('farmer__village__ward__name', 'Ward'),
    'ward': ('farmer__village__name', 'Village'),
    'extension': ('farmer__village__name', 'Village'),
}

@login_required
def reports(request):
    user = request.user
    inv_qs = SeedInventory.objects.all()
    dist_qs = Distribution.objects.all()
    alloc_qs = SeedAllocation.objects.all()
    farmers_qs = Farmer.objects.all()

    if user.role == 'regional':
        alloc_qs = alloc_qs.filter(farmer__village__ward__district__region=user.region)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward__district__region=user.region)
        farmers_qs = farmers_qs.filter(village__ward__district__region=user.region)
        inv_qs = inv_qs.filter(region=user.region)
    elif user.role == 'district':
        alloc_qs = alloc_qs.filter(farmer__village__ward__district=user.district)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward__district=user.district)
        farmers_qs = farmers_qs.filter(village__ward__district=user.district)
    elif user.role in ('ward', 'extension'):
        alloc_qs = alloc_qs.filter(farmer__village__ward=user.ward)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward=user.ward)
        farmers_qs = farmers_qs.filter(village__ward=user.ward)
    elif user.role == 'village':
        alloc_qs = alloc_qs.filter(farmer__village=user.village)
        dist_qs = dist_qs.filter(allocation__farmer__village=user.village)
        farmers_qs = farmers_qs.filter(village=user.village)

    # Season filter applies to every allocation-derived figure on the page
    season_id = request.GET.get('season','')
    if season_id:
        alloc_qs = alloc_qs.filter(season_id=season_id)

    if user.role in ('district','ward','village'):
        total_received = total_received_for_user(user)
        remaining_stock = total_balance_for_user(user)
        received_label = 'Total Seeds Received via Transfers (kg)'
        remaining_label = 'Remaining Stock (kg)'
    elif user.role == 'extension':
        ward_requests = SeedRequest.objects.filter(farmer__village__ward=user.ward)
        total_received = ward_requests.filter(status='submitted').count()
        remaining_stock = ward_requests.filter(status='verified').count()
        received_label = 'Seed Requests Submitted'
        remaining_label = 'Awaiting Fulfillment'
    else:
        total_received = inv_qs.aggregate(t=Sum('quantity'))['t'] or 0
        remaining_stock = total_received - (dist_qs.aggregate(t=Sum('quantity_distributed'))['t'] or 0)
        received_label = 'Total Seeds Received (kg)'
        remaining_label = 'Remaining Stock (kg)'

    completed_qs = alloc_qs.filter(status__in=['approved','distributed'])

    ctx = {
        'total_received': total_received,
        'total_distributed': dist_qs.aggregate(t=Sum('quantity_distributed'))['t'] or 0,
        'total_farmers': farmers_qs.count(),
        'total_allocations': alloc_qs.count(),
        'approved_allocations': alloc_qs.filter(status='approved').count(),
        'distributed_allocations': alloc_qs.filter(status='distributed').count(),
        'seed_summary': completed_qs.values('seed_type__name','seed_type__unit').annotate(qty=Sum('quantity_allocated'), cnt=Count('id')).order_by('-qty'),
        'remaining_stock': remaining_stock,
        'received_label': received_label,
        'remaining_label': remaining_label,
        'seasons': FarmingSeasons.objects.all(),
        'selected_season': season_id,
    }

    # Breakdown one organizational level below the viewer (village officers see per-farmer)
    if user.role == 'village':
        breakdown_label = 'Farmer'
        raw = completed_qs.values('farmer__farmer_id','farmer__first_name','farmer__last_name').annotate(cnt=Count('id'), qty=Sum('quantity_allocated')).order_by('-qty')
        breakdown = [{'label': f"{r['farmer__first_name']} {r['farmer__last_name']} ({r['farmer__farmer_id']})", 'cnt': r['cnt'], 'qty': r['qty']} for r in raw]
    else:
        field, breakdown_label = REPORT_BREAKDOWN_BY_ROLE.get(user.role, REPORT_BREAKDOWN_BY_ROLE['admin'])
        raw = completed_qs.values(field).annotate(cnt=Count('id'), qty=Sum('quantity_allocated')).order_by('-qty')
        breakdown = [{'label': r[field] or 'Unknown', 'cnt': r['cnt'], 'qty': r['qty']} for r in raw]

    ctx['breakdown_label'] = breakdown_label
    ctx['breakdown'] = breakdown
    ctx['chart_labels'] = json.dumps([b['label'] for b in breakdown[:8]])
    ctx['chart_data'] = json.dumps([float(b['qty'] or 0) for b in breakdown[:8]])

    return render(request, 'core/reports.html', ctx)

@login_required
def export_farmers_csv(request):
    qs = Farmer.objects.select_related('village__ward__district__region')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="farmers_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['ID','Name','Phone','Village','Ward','District','Region','Crop','Status'])
    for f in qs:
        writer.writerow([f.farmer_id, f.full_name, f.phone_number, f.village.name, f.ward.name, f.district.name, f.region.name, f.crop_type, f.status])
    return response

@login_required
def export_allocations_csv(request):
    qs = SeedAllocation.objects.select_related('farmer','seed_type','season')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="allocations_export.csv"'
    writer = csv.writer(response)
    writer.writerow(['Farmer ID','Farmer','Seed','Season','Quantity','Status','Collection Date','Collection Location'])
    for a in qs:
        writer.writerow([a.farmer.farmer_id, a.farmer.full_name, a.seed_type.name, a.season.name, a.quantity_allocated, a.status, a.collection_date, a.collection_location])
    return response

# =================== USER MANAGEMENT ===================
@login_required
@role_required('admin')
def user_list(request):
    users = CustomUser.objects.all().order_by('role','username')
    return render(request, 'core/user_list.html', {'users': users})

def location_tree_json():
    """Full region/district/ward/village hierarchy, for cascading dropdown JS."""
    return json.dumps({
        'districts': list(District.objects.values('id','name','region_id')),
        'wards': list(Ward.objects.values('id','name','district_id')),
        'villages': list(Village.objects.values('id','name','ward_id')),
    })

@login_required
@role_required('admin')
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        ActivityLog.objects.create(user=request.user, action=f'Created user {user.username}')
        messages.success(request, f'User {user.username} created.')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'title': 'Create User', 'location_tree': location_tree_json()})

@login_required
@role_required('admin')
def user_edit(request, pk):
    u = get_object_or_404(CustomUser, pk=pk)
    form = UserCreateForm(request.POST or None, instance=u)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'User updated.')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'title': 'Edit User', 'edit_user': u, 'location_tree': location_tree_json()})

# =================== SETTINGS / ADMIN ===================
@login_required
@role_required('admin')
def seed_type_list(request):
    seeds = SeedType.objects.annotate(total_inv=Sum('inventory__quantity')).all()
    return render(request, 'core/seed_type_list.html', {'seeds': seeds})

@login_required
@role_required('admin')
def seed_type_create(request):
    form = SeedTypeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Seed type added.')
        return redirect('seed_type_list')
    return render(request, 'core/seed_type_form.html', {'form': form, 'title': 'Add Seed Type'})

@login_required
@role_required('admin')
def season_list(request):
    seasons = FarmingSeasons.objects.all().order_by('-start_date')
    return render(request, 'core/season_list.html', {'seasons': seasons})

@login_required
@role_required('admin')
def season_create(request):
    form = FarmingSeasonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        season = form.save()
        if season.is_active:
            FarmingSeasons.objects.exclude(pk=season.pk).update(is_active=False)
        messages.success(request, 'Season created.')
        return redirect('season_list')
    return render(request, 'core/season_form.html', {'form': form, 'title': 'Add Season'})

@login_required
@role_required('admin')
def location_manage(request):
    regions = Region.objects.prefetch_related('districts__wards__villages').all()
    region_form = RegionForm(prefix='region')
    district_form = DistrictForm(prefix='district')
    ward_form = WardForm(prefix='ward')
    village_form = VillageForm(prefix='village')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_region':
            region_form = RegionForm(request.POST, prefix='region')
            if region_form.is_valid():
                region_form.save()
                messages.success(request, 'Region added.')
                return redirect('location_manage')
        elif action == 'add_district':
            district_form = DistrictForm(request.POST, prefix='district')
            if district_form.is_valid():
                district_form.save()
                messages.success(request, 'District added.')
                return redirect('location_manage')
        elif action == 'add_ward':
            ward_form = WardForm(request.POST, prefix='ward')
            if ward_form.is_valid():
                ward_form.save()
                messages.success(request, 'Ward added.')
                return redirect('location_manage')
        elif action == 'add_village':
            village_form = VillageForm(request.POST, prefix='village')
            if village_form.is_valid():
                village_form.save()
                messages.success(request, 'Village added.')
                return redirect('location_manage')

    return render(request, 'core/location_manage.html', {
        'regions': regions, 'region_form': region_form,
        'district_form': district_form, 'ward_form': ward_form, 'village_form': village_form
    })

@login_required
def sms_logs(request):
    logs = SMSLog.objects.select_related('farmer','allocation').order_by('-created_at')
    paginator = Paginator(logs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/sms_logs.html', {'page_obj': page})

@login_required
def activity_logs(request):
    if request.user.role not in ['admin']:
        return redirect('dashboard')
    logs = ActivityLog.objects.select_related('user').order_by('-created_at')
    paginator = Paginator(logs, 30)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/activity_logs.html', {'page_obj': page})

# =================== STOCK TRANSFERS ===================
@login_required
def stock_list(request):
    user = request.user
    location_label, location = location_for_user(user)

    balances = []
    if location:
        for st in SeedType.objects.all():
            qty = balance_for_user(st, user)
            if qty:
                balances.append({'seed_type': st, 'quantity': qty})

    sent = StockTransfer.objects.none()
    incoming_requests = StockTransfer.objects.none()
    received = StockTransfer.objects.none()
    my_requests = StockTransfer.objects.none()

    if user.role == 'regional' and user.region:
        sent = StockTransfer.objects.filter(level='region_to_district', from_region=user.region, kind='distribution')
        incoming_requests = StockTransfer.objects.filter(level='region_to_district', from_region=user.region, kind='request')
    elif user.role == 'district' and user.district:
        sent = StockTransfer.objects.filter(level='district_to_ward', from_district=user.district, kind='distribution')
        incoming_requests = StockTransfer.objects.filter(level='district_to_ward', from_district=user.district, kind='request')
        received = StockTransfer.objects.filter(level='region_to_district', to_district=user.district, status='approved')
        my_requests = StockTransfer.objects.filter(level='region_to_district', to_district=user.district, kind='request')
    elif user.role == 'ward' and user.ward:
        sent = StockTransfer.objects.filter(level='ward_to_village', from_ward=user.ward, kind='distribution')
        incoming_requests = StockTransfer.objects.filter(level='ward_to_village', from_ward=user.ward, kind='request')
        received = StockTransfer.objects.filter(level='district_to_ward', to_ward=user.ward, status='approved')
        my_requests = StockTransfer.objects.filter(level='district_to_ward', to_ward=user.ward, kind='request')
    elif user.role == 'village' and user.village:
        received = StockTransfer.objects.filter(level='ward_to_village', to_village=user.village, status='approved')
        my_requests = StockTransfer.objects.filter(level='ward_to_village', to_village=user.village, kind='request')
    elif user.role == 'admin':
        sent = StockTransfer.objects.filter(kind='distribution')
        incoming_requests = StockTransfer.objects.filter(kind='request')

    ctx = {
        'location_label': location_label,
        'location': location,
        'balances': balances,
        'sent': sent.select_related('seed_type','initiated_by').order_by('-created_at')[:50],
        'incoming_requests': incoming_requests.select_related('seed_type','initiated_by').order_by('status','-created_at')[:50],
        'received': received.select_related('seed_type','initiated_by','responded_by').order_by('-created_at')[:50],
        'my_requests': my_requests.select_related('seed_type','responded_by').order_by('-created_at')[:50],
    }
    return render(request, 'core/stock_list.html', ctx)

@login_required
@role_required('regional','district','ward')
def stock_distribute(request):
    user = request.user
    form = StockDistributeForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        seed_type = form.cleaned_data['seed_type']
        quantity = form.cleaned_data['quantity']
        target = form.cleaned_data['target']
        with transaction.atomic():
            lock_user_location(user)
            available = balance_for_user(seed_type, user)
            if quantity > available:
                form.add_error('quantity', f'Insufficient balance. Available: {available} {seed_type.unit}.')
                transfer = None
            else:
                transfer = StockTransfer(
                    seed_type=seed_type, quantity=quantity, kind='distribution', status='approved',
                    initiated_by=user, responded_by=user, notes=form.cleaned_data.get('notes','')
                )
                if user.role == 'regional':
                    transfer.level = 'region_to_district'; transfer.from_region = user.region; transfer.to_district = target
                elif user.role == 'district':
                    transfer.level = 'district_to_ward'; transfer.from_district = user.district; transfer.to_ward = target
                elif user.role == 'ward':
                    transfer.level = 'ward_to_village'; transfer.from_ward = user.ward; transfer.to_village = target
                transfer.save()
        if transfer is not None:
            ActivityLog.objects.create(user=user, action=f'Distributed {quantity} {seed_type.unit} of {seed_type.name} to {target}')
            messages.success(request, f'{quantity} {seed_type.unit} of {seed_type.name} distributed to {target}.')
            return redirect('stock_list')
    return render(request, 'core/stock_distribute_form.html', {'form': form})

@login_required
@role_required('district','ward','village')
def stock_request_create(request):
    user = request.user
    form = StockRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        seed_type = form.cleaned_data['seed_type']
        quantity = form.cleaned_data['quantity']
        transfer = StockTransfer(
            seed_type=seed_type, quantity=quantity, kind='request', status='pending',
            initiated_by=user, notes=form.cleaned_data.get('notes','')
        )
        if user.role == 'district':
            transfer.level = 'region_to_district'; transfer.from_region = user.region; transfer.to_district = user.district
        elif user.role == 'ward':
            transfer.level = 'district_to_ward'; transfer.from_district = user.district; transfer.to_ward = user.ward
        elif user.role == 'village':
            transfer.level = 'ward_to_village'; transfer.from_ward = user.ward; transfer.to_village = user.village
        transfer.save()
        ActivityLog.objects.create(user=user, action=f'Requested {quantity} {seed_type.unit} of {seed_type.name}')
        messages.success(request, 'Stock request submitted.')
        return redirect('stock_list')
    return render(request, 'core/stock_request_form.html', {'form': form})

@login_required
@role_required('regional','district','ward')
def stock_request_respond(request, pk):
    user = request.user
    transfer = get_object_or_404(StockTransfer, pk=pk, kind='request', status='pending')
    authorized = (
        (user.role == 'regional' and transfer.level == 'region_to_district' and transfer.from_region_id == user.region_id) or
        (user.role == 'district' and transfer.level == 'district_to_ward' and transfer.from_district_id == user.district_id) or
        (user.role == 'ward' and transfer.level == 'ward_to_village' and transfer.from_ward_id == user.ward_id)
    )
    if not authorized:
        messages.error(request, 'You are not authorized to respond to this request.')
        return redirect('stock_list')
    form = StockRespondForm(request.POST or None)
    available = balance_for_user(transfer.seed_type, user)
    if request.method == 'POST':
        if 'approve' in request.POST:
            with transaction.atomic():
                lock_user_location(user)
                current_available = balance_for_user(transfer.seed_type, user)
                if transfer.quantity > current_available:
                    messages.error(request, f'Insufficient balance to approve. Available: {current_available} {transfer.seed_type.unit}.')
                    approved = False
                else:
                    transfer.status = 'approved'
                    transfer.responded_by = user
                    transfer.save()
                    approved = True
            if approved:
                ActivityLog.objects.create(user=user, action=f'Approved stock request from {transfer.initiated_by}')
                messages.success(request, 'Request approved and stock transferred.')
                return redirect('stock_list')
        elif 'reject' in request.POST and form.is_valid():
            transfer.status = 'rejected'
            transfer.responded_by = user
            transfer.rejection_reason = form.cleaned_data.get('rejection_reason','')
            transfer.save()
            ActivityLog.objects.create(user=user, action=f'Rejected stock request from {transfer.initiated_by}')
            messages.warning(request, 'Request rejected.')
            return redirect('stock_list')
    return render(request, 'core/stock_request_respond.html', {'transfer': transfer, 'form': form, 'available': available})

# =================== FARMER SELF-SERVICE (Mkulima) ===================
def farmer_register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = FarmerRegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user, farmer = form.save()
        login(request, user)
        ActivityLog.objects.create(user=user, action=f'Farmer self-registered: {farmer.full_name}', model_name='Farmer', object_id=farmer.id)
        messages.success(request, f'Welcome, {farmer.full_name}! Your farmer ID is {farmer.farmer_id}.')
        return redirect('farmer_dashboard')
    return render(request, 'registration/farmer_register.html', {'form': form})

@farmer_required
def farmer_dashboard(request):
    farmer = request.user.farmer_profile
    requests_qs = farmer.seed_requests.select_related('seed_type','season').order_by('-created_at')
    allocations_qs = farmer.allocations.select_related('seed_type','season').order_by('-created_at')
    ctx = {
        'farmer': farmer,
        'requests': requests_qs[:10],
        'allocations': allocations_qs[:10],
        'pending_requests': requests_qs.filter(status__in=['submitted','verified']).count(),
        'total_requests': requests_qs.count(),
        'total_allocations': allocations_qs.count(),
        'sms_logs': farmer.sms_logs.order_by('-created_at')[:5],
        'open_feedback': farmer.feedback_items.filter(status='open').count(),
    }
    return render(request, 'core/farmer_dashboard.html', ctx)

@farmer_required
def farmer_profile_edit(request):
    farmer = request.user.farmer_profile
    form = FarmerSelfUpdateForm(request.POST or None, instance=farmer)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your farm information has been updated.')
        return redirect('farmer_dashboard')
    return render(request, 'core/farmer_profile_form.html', {'form': form, 'farmer': farmer})

@farmer_required
def farmer_confirm_receipt(request, pk):
    farmer = request.user.farmer_profile
    distribution = get_object_or_404(Distribution, pk=pk, allocation__farmer=farmer)
    if request.method == 'POST':
        distribution.farmer_confirmed = True
        distribution.farmer_confirmed_at = timezone.now()
        distribution.save()
        messages.success(request, 'Thank you for confirming receipt of your seeds.')
        return redirect('farmer_dashboard')
    return render(request, 'core/farmer_confirm_receipt.html', {'distribution': distribution})

# =================== SEED REQUESTS (Farmer -> Extension -> Village Officer) ===================
@login_required
def seed_request_create(request):
    user = request.user
    if user.role not in ('farmer', 'extension'):
        messages.error(request, 'You do not have permission to submit seed requests.')
        return redirect('dashboard')
    if user.role == 'farmer' and not hasattr(user, 'farmer_profile'):
        messages.error(request, 'No farmer profile found for this account.')
        return redirect('dashboard')
    form = SeedRequestForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        farmer = user.farmer_profile if user.role == 'farmer' else form.cleaned_data['farmer']
        seed_type = form.cleaned_data['seed_type']
        season = form.cleaned_data['season']
        if SeedRequest.objects.filter(farmer=farmer, seed_type=seed_type, season=season, status__in=['submitted','verified']).exists():
            messages.error(request, 'There is already an open request for this farmer, seed type and season.')
        else:
            SeedRequest.objects.create(
                farmer=farmer, seed_type=seed_type, season=season,
                quantity_requested=form.cleaned_data['quantity_requested'],
                notes=form.cleaned_data.get('notes',''), submitted_by=user,
            )
            ActivityLog.objects.create(user=user, action=f'Submitted seed request for {farmer.full_name} ({seed_type.name})')
            messages.success(request, 'Seed request submitted.')
            return redirect('seed_request_list')
    redirect_target = 'farmer_dashboard' if user.role == 'farmer' else 'seed_request_list'
    return render(request, 'core/seed_request_form.html', {'form': form, 'redirect_target': redirect_target})

@login_required
def seed_request_list(request):
    user = request.user
    qs = SeedRequest.objects.select_related('farmer','seed_type','season','submitted_by','verified_by')
    can_fulfill = False
    can_verify = False
    if user.role == 'farmer':
        if not hasattr(user, 'farmer_profile'):
            messages.error(request, 'No farmer profile found for this account.')
            return redirect('dashboard')
        qs = qs.filter(farmer=user.farmer_profile)
    elif user.role == 'extension':
        qs = qs.filter(farmer__village__ward=user.ward)
        can_verify = True
    elif user.role == 'village':
        qs = qs.filter(farmer__village=user.village)
        can_fulfill = True
    elif user.role == 'ward':
        qs = qs.filter(farmer__village__ward=user.ward)
    elif user.role == 'district':
        qs = qs.filter(farmer__village__ward__district=user.district)
    elif user.role == 'regional':
        qs = qs.filter(farmer__village__ward__district__region=user.region)

    status_filter = request.GET.get('status','')
    if status_filter:
        qs = qs.filter(status=status_filter)
    paginator = Paginator(qs.order_by('-created_at'), 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/seed_request_list.html', {
        'page_obj': page, 'status_filter': status_filter, 'can_fulfill': can_fulfill, 'can_verify': can_verify,
    })

@login_required
@role_required('extension')
def seed_request_verify(request, pk):
    user = request.user
    sr = get_object_or_404(SeedRequest, pk=pk, status='submitted')
    if sr.farmer.village.ward_id != user.ward_id:
        messages.error(request, 'You can only verify requests from farmers in your own ward.')
        return redirect('seed_request_list')
    form = SeedRequestVerifyForm(request.POST or None)
    if request.method == 'POST':
        if 'verify' in request.POST:
            sr.status = 'verified'
            sr.verified_by = user
            sr.save()
            ActivityLog.objects.create(user=user, action=f'Verified seed request for {sr.farmer.full_name}')
            messages.success(request, 'Request verified and forwarded to the Village Officer.')
            return redirect('seed_request_list')
        elif 'reject' in request.POST and form.is_valid():
            sr.status = 'rejected'
            sr.verified_by = user
            sr.rejection_reason = form.cleaned_data.get('rejection_reason','')
            sr.save()
            ActivityLog.objects.create(user=user, action=f'Rejected seed request for {sr.farmer.full_name}')
            messages.warning(request, 'Request rejected.')
            return redirect('seed_request_list')
    return render(request, 'core/seed_request_verify.html', {'request_obj': sr, 'form': form})

@login_required
@role_required('village')
def seed_request_fulfill(request, pk):
    user = request.user
    sr = get_object_or_404(SeedRequest, pk=pk, status='verified')
    if sr.farmer.village_id != user.village_id:
        messages.error(request, 'You can only fulfill requests for farmers in your own village.')
        return redirect('seed_request_list')
    form = SeedRequestFulfillForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        a, error = create_farmer_allocation(
            farmer=sr.farmer, seed_type=sr.seed_type, season=sr.season,
            quantity=sr.quantity_requested, collection_date=form.cleaned_data['collection_date'],
            collection_location=form.cleaned_data['collection_location'], notes=form.cleaned_data.get('notes',''),
            actor=user,
        )
        if error:
            messages.error(request, error)
        else:
            sr.status = 'fulfilled'
            sr.resulting_allocation = a
            sr.save()
            messages.success(request, f'Request fulfilled and SMS sent to {a.farmer.phone_number}.')
            return redirect('seed_request_list')
    return render(request, 'core/seed_request_fulfill.html', {'request_obj': sr, 'form': form})

# =================== FEEDBACK / COMPLAINTS ===================
@farmer_required
def feedback_create(request):
    farmer = request.user.farmer_profile
    form = FeedbackForm(request.POST or None, farmer=farmer)
    if request.method == 'POST' and form.is_valid():
        Feedback.objects.create(
            farmer=farmer, category=form.cleaned_data['category'],
            message=form.cleaned_data['message'], related_allocation=form.cleaned_data.get('related_allocation'),
        )
        messages.success(request, 'Thank you - your feedback has been submitted.')
        return redirect('feedback_list')
    return render(request, 'core/feedback_form.html', {'form': form})

@login_required
def feedback_list(request):
    user = request.user
    qs = Feedback.objects.select_related('farmer','related_allocation','resolved_by')
    can_resolve = False
    if user.role == 'farmer':
        if not hasattr(user, 'farmer_profile'):
            messages.error(request, 'No farmer profile found for this account.')
            return redirect('dashboard')
        qs = qs.filter(farmer=user.farmer_profile)
    elif user.role == 'extension':
        qs = qs.filter(farmer__village__ward=user.ward)
        can_resolve = True
    elif user.role == 'village':
        qs = qs.filter(farmer__village=user.village)
    elif user.role == 'ward':
        qs = qs.filter(farmer__village__ward=user.ward)
    elif user.role == 'district':
        qs = qs.filter(farmer__village__ward__district=user.district)
    elif user.role == 'regional':
        qs = qs.filter(farmer__village__ward__district__region=user.region)

    status_filter = request.GET.get('status','')
    if status_filter:
        qs = qs.filter(status=status_filter)
    paginator = Paginator(qs.order_by('-created_at'), 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/feedback_list.html', {'page_obj': page, 'status_filter': status_filter, 'can_resolve': can_resolve})

@login_required
@role_required('extension')
def feedback_resolve(request, pk):
    user = request.user
    fb = get_object_or_404(Feedback, pk=pk, status='open')
    if fb.farmer.village.ward_id != user.ward_id:
        messages.error(request, 'You can only resolve feedback from farmers in your own ward.')
        return redirect('feedback_list')
    form = FeedbackResolveForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        fb.status = 'resolved'
        fb.response = form.cleaned_data['response']
        fb.resolved_by = user
        fb.resolved_at = timezone.now()
        fb.save()
        ActivityLog.objects.create(user=user, action=f'Resolved feedback from {fb.farmer.full_name}')
        messages.success(request, 'Feedback resolved.')
        return redirect('feedback_list')
    return render(request, 'core/feedback_resolve.html', {'feedback': fb, 'form': form})
