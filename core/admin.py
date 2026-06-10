from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Role & Location', {'fields': ('role','phone','region','district','ward','village')}),)
    list_display = ['username','get_full_name','role','is_active']

admin.site.register(Region)
admin.site.register(District)
admin.site.register(Ward)
admin.site.register(Village)
admin.site.register(SeedType)
admin.site.register(SeedInventory)
admin.site.register(FarmingSeasons)
admin.site.register(Farmer)
admin.site.register(SeedAllocation)
admin.site.register(Distribution)
admin.site.register(SMSLog)
admin.site.register(ActivityLog)
