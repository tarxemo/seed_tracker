from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from .models import *

TARGET_MODEL_BY_ROLE = {
    'regional': (District, 'region', 'District'),
    'district': (Ward, 'district', 'Ward'),
    'ward': (Village, 'ward', 'Village'),
}

class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class':'form-control','placeholder':'Username'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class':'form-control','placeholder':'Password'}))

class FarmerForm(forms.ModelForm):
    class Meta:
        model = Farmer
        fields = ['first_name','last_name','phone_number','village','farm_location','farm_size','crop_type','national_id','status']
        widgets = {f: forms.TextInput(attrs={'class':'form-control'}) for f in ['first_name','last_name','phone_number','farm_location','national_id']}
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, (forms.Select,forms.CheckboxInput)):
                f.widget.attrs.setdefault('class','form-control')
            else:
                f.widget.attrs.setdefault('class','form-select')
        if user and user.role == 'village':
            self.fields['village'].queryset = Village.objects.filter(id=user.village_id)
            self.fields['village'].initial = user.village_id
        elif user and user.role == 'ward':
            self.fields['village'].queryset = Village.objects.filter(ward=user.ward)
        elif user and user.role == 'district':
            self.fields['village'].queryset = Village.objects.filter(ward__district=user.district)

class SeedInventoryForm(forms.ModelForm):
    class Meta:
        model = SeedInventory
        fields = ['seed_type','quantity','date_received','source','region','notes']
        widgets = {'date_received': forms.DateInput(attrs={'type':'date','class':'form-control'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, (forms.Select,forms.Textarea)):
                f.widget.attrs.setdefault('class','form-control')
            elif isinstance(f.widget, forms.Select):
                f.widget.attrs.setdefault('class','form-select')
            else:
                f.widget.attrs.setdefault('class','form-control')

class SeedAllocationForm(forms.ModelForm):
    class Meta:
        model = SeedAllocation
        fields = ['farmer','seed_type','season','quantity_allocated','collection_date','collection_location','notes']
        widgets = {'collection_date': forms.DateInput(attrs={'type':'date','class':'form-control'})}
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, (forms.Select,forms.Textarea)):
                f.widget.attrs.setdefault('class','form-control')
            elif isinstance(f.widget, forms.Select):
                f.widget.attrs.setdefault('class','form-select')
            else:
                f.widget.attrs.setdefault('class','form-control')
        if user and user.role == 'village':
            self.fields['farmer'].queryset = Farmer.objects.filter(village=user.village)
        self.fields['season'].queryset = FarmingSeasons.objects.filter(is_active=True)

class DistributionForm(forms.ModelForm):
    class Meta:
        model = Distribution
        fields = ['quantity_distributed','collection_date','notes']
        widgets = {'collection_date': forms.DateInput(attrs={'type':'date','class':'form-control'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, forms.Textarea):
                f.widget.attrs.setdefault('class','form-control')
            else:
                f.widget.attrs.setdefault('class','form-control')

class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class':'form-control'}))
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput(attrs={'class':'form-control'}))
    class Meta:
        model = CustomUser
        fields = ['username','first_name','last_name','email','role','phone','region','district','ward','village']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, forms.Select):
                f.widget.attrs.setdefault('class','form-control')
            else:
                f.widget.attrs.setdefault('class','form-select')
    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 != password2:
            raise forms.ValidationError("Passwords do not match.")
        if password1:
            temp_user = CustomUser(username=cleaned_data.get('username',''), first_name=cleaned_data.get('first_name',''),
                                    last_name=cleaned_data.get('last_name',''), email=cleaned_data.get('email',''))
            try:
                validate_password(password1, user=temp_user)
            except forms.ValidationError as e:
                self.add_error('password1', e)
        return cleaned_data
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit: user.save()
        return user

class SeedTypeForm(forms.ModelForm):
    class Meta:
        model = SeedType
        fields = ['name','description','unit']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class','form-control')

class FarmingSeasonForm(forms.ModelForm):
    class Meta:
        model = FarmingSeasons
        fields = ['name','start_date','end_date','is_active']
        widgets = {
            'start_date': forms.DateInput(attrs={'type':'date','class':'form-control'}),
            'end_date': forms.DateInput(attrs={'type':'date','class':'form-control'}),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for n, f in self.fields.items():
            if n != 'is_active' and not isinstance(f.widget, forms.DateInput):
                f.widget.attrs.setdefault('class','form-control')

class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ['name']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class','form-control')

class DistrictForm(forms.ModelForm):
    class Meta:
        model = District
        fields = ['name','region']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class','form-control')
        self.fields['region'].widget.attrs['class'] = 'form-select'

class WardForm(forms.ModelForm):
    class Meta:
        model = Ward
        fields = ['name','district']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class','form-control')
        self.fields['district'].widget.attrs['class'] = 'form-select'

class VillageForm(forms.ModelForm):
    class Meta:
        model = Village
        fields = ['name','ward']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class','form-control')
        self.fields['ward'].widget.attrs['class'] = 'form-select'

class StockDistributeForm(forms.Form):
    seed_type = forms.ModelChoiceField(queryset=SeedType.objects.all(), widget=forms.Select(attrs={'class':'form-select'}))
    quantity = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01, widget=forms.NumberInput(attrs={'class':'form-control'}))
    target = forms.ModelChoiceField(queryset=District.objects.none(), widget=forms.Select(attrs={'class':'form-select'}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        model, parent_attr, label = TARGET_MODEL_BY_ROLE.get(user.role, (District.objects.none().model, None, 'Target'))
        self.fields['target'].label = label
        if parent_attr:
            parent_value = getattr(user, parent_attr)
            self.fields['target'].queryset = model.objects.filter(**{parent_attr: parent_value}) if parent_value else model.objects.none()

class StockRequestForm(forms.Form):
    seed_type = forms.ModelChoiceField(queryset=SeedType.objects.all(), widget=forms.Select(attrs={'class':'form-select'}))
    quantity = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01, widget=forms.NumberInput(attrs={'class':'form-control'}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))

class StockRespondForm(forms.Form):
    rejection_reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))

class FarmerRegisterForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class':'form-control'}))
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput(attrs={'class':'form-control'}))
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput(attrs={'class':'form-control'}))
    first_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class':'form-control'}))
    last_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class':'form-control'}))
    phone_number = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class':'form-control'}))
    village = forms.ModelChoiceField(queryset=Village.objects.select_related('ward__district__region').order_by('name'), widget=forms.Select(attrs={'class':'form-select'}))
    farm_location = forms.CharField(max_length=200, required=False, widget=forms.TextInput(attrs={'class':'form-control'}))
    farm_size = forms.DecimalField(max_digits=8, decimal_places=2, required=False, widget=forms.NumberInput(attrs={'class':'form-control'}))
    crop_type = forms.ChoiceField(choices=CROP_CHOICES, widget=forms.Select(attrs={'class':'form-select'}))
    national_id = forms.CharField(max_length=30, required=False, widget=forms.TextInput(attrs={'class':'form-control'}))

    def clean_username(self):
        username = self.cleaned_data['username']
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_phone_number(self):
        phone_number = self.cleaned_data['phone_number']
        if Farmer.objects.filter(phone_number=phone_number).exists():
            raise forms.ValidationError('A farmer with this phone number is already registered. If this is you, please contact your Village Officer for help accessing your account.')
        return phone_number

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 != password2:
            raise forms.ValidationError('Passwords do not match.')
        if password1:
            temp_user = CustomUser(username=cleaned_data.get('username',''), first_name=cleaned_data.get('first_name',''),
                                    last_name=cleaned_data.get('last_name',''))
            try:
                validate_password(password1, user=temp_user)
            except forms.ValidationError as e:
                self.add_error('password1', e)
        return cleaned_data

    def save(self):
        cd = self.cleaned_data
        user = CustomUser(username=cd['username'], first_name=cd['first_name'], last_name=cd['last_name'], phone=cd['phone_number'], role='farmer')
        user.set_password(cd['password1'])
        user.save()
        farmer = Farmer.objects.create(
            first_name=cd['first_name'], last_name=cd['last_name'], phone_number=cd['phone_number'],
            village=cd['village'], farm_location=cd.get('farm_location',''), farm_size=cd.get('farm_size'),
            crop_type=cd['crop_type'], national_id=cd.get('national_id',''), user=user,
        )
        return user, farmer

class FarmerSelfUpdateForm(forms.ModelForm):
    class Meta:
        model = Farmer
        fields = ['phone_number','farm_location','farm_size','crop_type','national_id']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, forms.Select):
                f.widget.attrs.setdefault('class','form-control')
            else:
                f.widget.attrs.setdefault('class','form-select')

class SeedRequestForm(forms.Form):
    farmer = forms.ModelChoiceField(queryset=Farmer.objects.none(), required=False, widget=forms.Select(attrs={'class':'form-select'}))
    seed_type = forms.ModelChoiceField(queryset=SeedType.objects.all(), widget=forms.Select(attrs={'class':'form-select'}))
    season = forms.ModelChoiceField(queryset=FarmingSeasons.objects.filter(is_active=True), widget=forms.Select(attrs={'class':'form-select'}))
    quantity_requested = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01, widget=forms.NumberInput(attrs={'class':'form-control'}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.role == 'extension':
            self.fields['farmer'].queryset = Farmer.objects.filter(village__ward=user.ward)
            self.fields['farmer'].required = True
        else:
            del self.fields['farmer']

class SeedRequestVerifyForm(forms.Form):
    rejection_reason = forms.CharField(required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))

class SeedRequestFulfillForm(forms.Form):
    collection_date = forms.DateField(widget=forms.DateInput(attrs={'type':'date','class':'form-control'}))
    collection_location = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class':'form-control'}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'class':'form-control','rows':3}))

class FeedbackForm(forms.Form):
    category = forms.ChoiceField(choices=Feedback.CATEGORY_CHOICES, widget=forms.Select(attrs={'class':'form-select'}))
    related_allocation = forms.ModelChoiceField(queryset=SeedAllocation.objects.none(), required=False, label='Related Allocation (optional)', widget=forms.Select(attrs={'class':'form-select'}))
    message = forms.CharField(widget=forms.Textarea(attrs={'class':'form-control','rows':4}))

    def __init__(self, *args, farmer=None, **kwargs):
        super().__init__(*args, **kwargs)
        if farmer:
            self.fields['related_allocation'].queryset = farmer.allocations.all()

class FeedbackResolveForm(forms.Form):
    response = forms.CharField(widget=forms.Textarea(attrs={'class':'form-control','rows':3}))
