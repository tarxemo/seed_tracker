from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import *

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
        elif user and user.role == 'ward':
            self.fields['farmer'].queryset = Farmer.objects.filter(village__ward=user.ward)
        elif user and user.role == 'district':
            self.fields['farmer'].queryset = Farmer.objects.filter(village__ward__district=user.district)
        self.fields['season'].queryset = FarmingSeasons.objects.filter(is_active=True)

class AllocationApproveForm(forms.ModelForm):
    class Meta:
        model = SeedAllocation
        fields = ['collection_date','collection_location','notes']
        widgets = {'collection_date': forms.DateInput(attrs={'type':'date','class':'form-control'})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            if not isinstance(f.widget, forms.Textarea):
                f.widget.attrs.setdefault('class','form-control')
            else:
                f.widget.attrs.setdefault('class','form-control')

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
        if cleaned_data.get('password1') != cleaned_data.get('password2'):
            raise forms.ValidationError("Passwords do not match.")
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
