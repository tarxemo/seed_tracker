from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.core.paginator import Paginator
import json, csv
from datetime import timedelta
from .models import *
from .forms import *
from .decorators import role_required
from .utils import send_allocation_sms
from .stock import balance_for_user, location_for_user, village_balance

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
def dashboard(request):
    user = request.user
    ctx = {}
    # Stats scoped by role
    farmers_qs = Farmer.objects.all()
    alloc_qs = SeedAllocation.objects.all()
    dist_qs = Distribution.objects.all()
    inv_qs = SeedInventory.objects.all()

    if user.role == 'village':
        farmers_qs = farmers_qs.filter(village=user.village)
        alloc_qs = alloc_qs.filter(farmer__village=user.village)
    elif user.role == 'ward':
        farmers_qs = farmers_qs.filter(village__ward=user.ward)
        alloc_qs = alloc_qs.filter(farmer__village__ward=user.ward)
    elif user.role == 'district':
        farmers_qs = farmers_qs.filter(village__ward__district=user.district)
        alloc_qs = alloc_qs.filter(farmer__village__ward__district=user.district)
    elif user.role == 'regional':
        farmers_qs = farmers_qs.filter(village__ward__district__region=user.region)
        alloc_qs = alloc_qs.filter(farmer__village__ward__district__region=user.region)

    ctx['total_farmers'] = farmers_qs.count()
    ctx['total_allocations'] = alloc_qs.count()
    ctx['approved_allocations'] = alloc_qs.filter(status='approved').count()
    ctx['pending_allocations'] = alloc_qs.filter(status='pending').count()
    ctx['distributed'] = dist_qs.count()
    ctx['total_seeds_received'] = inv_qs.aggregate(t=Sum('quantity'))['t'] or 0
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
    elif user.role == 'ward': qs = qs.filter(village__ward=user.ward)
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
    form = FarmerForm(request.POST or None, instance=farmer, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Farmer updated.')
        return redirect('farmer_list')
    return render(request, 'core/farmer_form.html', {'form': form, 'title': 'Edit Farmer', 'farmer': farmer})

@login_required
def farmer_detail(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    allocs = farmer.allocations.select_related('seed_type','season').order_by('-created_at')
    return render(request, 'core/farmer_detail.html', {'farmer': farmer, 'allocations': allocs})

# =================== INVENTORY ===================
@login_required
def inventory_list(request):
    qs = SeedInventory.objects.select_related('seed_type','region','added_by').order_by('-date_received')
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    # Summary by seed type
    summary = SeedInventory.objects.values('seed_type__name','seed_type__unit').annotate(total=Sum('quantity')).order_by('-total')
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
@login_required
def allocation_list(request):
    user = request.user
    qs = SeedAllocation.objects.select_related('farmer','seed_type','season','requested_by')
    if user.role == 'village': qs = qs.filter(farmer__village=user.village)
    elif user.role == 'ward': qs = qs.filter(farmer__village__ward=user.ward)
    elif user.role == 'district': qs = qs.filter(farmer__village__ward__district=user.district)
    elif user.role == 'regional': qs = qs.filter(farmer__village__ward__district__region=user.region)

    status_filter = request.GET.get('status','')
    if status_filter: qs = qs.filter(status=status_filter)
    q = request.GET.get('q','')
    if q: qs = qs.filter(Q(farmer__first_name__icontains=q)|Q(farmer__last_name__icontains=q)|Q(farmer__farmer_id__icontains=q))

    paginator = Paginator(qs.order_by('-created_at'), 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/allocation_list.html', {'page_obj': page, 'status_filter': status_filter, 'q': q})

@login_required
def allocation_create(request):
    user = request.user
    form = SeedAllocationForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        a = form.save(commit=False)
        a.requested_by = user
        # Check duplicate
        if SeedAllocation.objects.filter(farmer=a.farmer, seed_type=a.seed_type, season=a.season).exists():
            messages.error(request, 'This farmer already has an allocation for this seed type in this season.')
            return render(request, 'core/allocation_form.html', {'form': form, 'title': 'New Allocation'})
        # Check village has enough received stock
        available = village_balance(a.seed_type, a.farmer.village)
        if a.quantity_allocated > available:
            messages.error(request, f'Insufficient village stock for {a.seed_type.name}. Available: {available} {a.seed_type.unit}. Request more stock from your Ward Officer.')
            return render(request, 'core/allocation_form.html', {'form': form, 'title': 'New Seed Allocation'})
        a.save()
        ActivityLog.objects.create(user=user, action=f'Created allocation for {a.farmer}')
        messages.success(request, 'Allocation request submitted.')
        return redirect('allocation_list')
    return render(request, 'core/allocation_form.html', {'form': form, 'title': 'New Seed Allocation'})

@login_required
@role_required('admin','district','regional')
def allocation_approve(request, pk):
    allocation = get_object_or_404(SeedAllocation, pk=pk)
    if allocation.status != 'pending':
        messages.warning(request, 'This allocation is not pending.')
        return redirect('allocation_list')
    form = AllocationApproveForm(request.POST or None, instance=allocation)
    if request.method == 'POST':
        if 'approve' in request.POST and form.is_valid():
            a = form.save(commit=False)
            a.status = 'approved'
            a.approved_by = request.user
            a.save()
            send_allocation_sms(a)
            ActivityLog.objects.create(user=request.user, action=f'Approved allocation for {a.farmer}')
            messages.success(request, f'Allocation approved and SMS sent to {a.farmer.phone_number}.')
        elif 'reject' in request.POST:
            allocation.status = 'rejected'
            allocation.rejection_reason = request.POST.get('rejection_reason','')
            allocation.approved_by = request.user
            allocation.save()
            ActivityLog.objects.create(user=request.user, action=f'Rejected allocation for {allocation.farmer}')
            messages.warning(request, 'Allocation rejected.')
        return redirect('allocation_list')
    return render(request, 'core/allocation_approve.html', {'allocation': allocation, 'form': form})

@login_required
def allocation_detail(request, pk):
    allocation = get_object_or_404(SeedAllocation, pk=pk)
    return render(request, 'core/allocation_detail.html', {'allocation': allocation})

# =================== DISTRIBUTION ===================
@login_required
def distribution_list(request):
    user = request.user
    qs = Distribution.objects.select_related('allocation__farmer','allocation__seed_type')
    if user.role == 'village': qs = qs.filter(allocation__farmer__village=user.village)
    elif user.role == 'ward': qs = qs.filter(allocation__farmer__village__ward=user.ward)
    elif user.role == 'district': qs = qs.filter(allocation__farmer__village__ward__district=user.district)
    elif user.role == 'regional': qs = qs.filter(allocation__farmer__village__ward__district__region=user.region)
    paginator = Paginator(qs.order_by('-created_at'), 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'core/distribution_list.html', {'page_obj': page})

@login_required
def distribution_record(request, allocation_pk):
    allocation = get_object_or_404(SeedAllocation, pk=allocation_pk, status='approved')
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
    elif user.role == 'district':
        alloc_qs = alloc_qs.filter(farmer__village__ward__district=user.district)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward__district=user.district)
        farmers_qs = farmers_qs.filter(village__ward__district=user.district)
    elif user.role == 'ward':
        alloc_qs = alloc_qs.filter(farmer__village__ward=user.ward)
        dist_qs = dist_qs.filter(allocation__farmer__village__ward=user.ward)
        farmers_qs = farmers_qs.filter(village__ward=user.ward)

    ctx = {
        'total_received': inv_qs.aggregate(t=Sum('quantity'))['t'] or 0,
        'total_distributed': dist_qs.aggregate(t=Sum('quantity_distributed'))['t'] or 0,
        'total_farmers': farmers_qs.count(),
        'total_allocations': alloc_qs.count(),
        'approved_allocations': alloc_qs.filter(status='approved').count(),
        'distributed_allocations': alloc_qs.filter(status='distributed').count(),
        'seed_summary': alloc_qs.filter(status__in=['approved','distributed']).values('seed_type__name','seed_type__unit').annotate(qty=Sum('quantity_allocated'), cnt=Count('id')).order_by('-qty'),
        'region_summary': alloc_qs.values('farmer__village__ward__district__region__name').annotate(cnt=Count('id'), qty=Sum('quantity_allocated')).order_by('-qty'),
        'district_summary': alloc_qs.values('farmer__village__ward__district__name').annotate(cnt=Count('id'), qty=Sum('quantity_allocated')).order_by('-qty')[:10],
        'ward_summary': alloc_qs.values('farmer__village__ward__name').annotate(cnt=Count('id'), qty=Sum('quantity_allocated')).order_by('-qty')[:10],
        'village_summary': alloc_qs.values('farmer__village__name').annotate(cnt=Count('id'), qty=Sum('quantity_allocated')).order_by('-qty')[:10],
        'remaining_stock': (inv_qs.aggregate(t=Sum('quantity'))['t'] or 0) - (dist_qs.aggregate(t=Sum('quantity_distributed'))['t'] or 0),
        'seasons': FarmingSeasons.objects.all(),
    }
    # Season filter
    season_id = request.GET.get('season','')
    if season_id:
        alloc_qs2 = alloc_qs.filter(season_id=season_id)
        ctx['seed_summary'] = alloc_qs2.filter(status__in=['approved','distributed']).values('seed_type__name','seed_type__unit').annotate(qty=Sum('quantity_allocated'), cnt=Count('id')).order_by('-qty')
    # Chart: distribution by district
    dist_chart = alloc_qs.filter(status__in=['approved','distributed']).values('farmer__village__ward__district__name').annotate(qty=Sum('quantity_allocated')).order_by('-qty')[:8]
    ctx['dist_chart_labels'] = json.dumps([x['farmer__village__ward__district__name'] or 'Unknown' for x in dist_chart])
    ctx['dist_chart_data'] = json.dumps([float(x['qty'] or 0) for x in dist_chart])

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

@login_required
@role_required('admin')
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        ActivityLog.objects.create(user=request.user, action=f'Created user {user.username}')
        messages.success(request, f'User {user.username} created.')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'title': 'Create User'})

@login_required
@role_required('admin')
def user_edit(request, pk):
    u = get_object_or_404(CustomUser, pk=pk)
    form = UserCreateForm(request.POST or None, instance=u)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'User updated.')
        return redirect('user_list')
    return render(request, 'core/user_form.html', {'form': form, 'title': 'Edit User', 'edit_user': u})

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
        available = balance_for_user(seed_type, user)
        if quantity > available:
            form.add_error('quantity', f'Insufficient balance. Available: {available} {seed_type.unit}.')
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
            if transfer.quantity > available:
                messages.error(request, f'Insufficient balance to approve. Available: {available} {transfer.seed_type.unit}.')
            else:
                transfer.status = 'approved'
                transfer.responded_by = user
                transfer.save()
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
