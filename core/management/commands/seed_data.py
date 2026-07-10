from django.core.management.base import BaseCommand
from core.models import *
from datetime import date

class Command(BaseCommand):
    help = 'Seed demo data for the system'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding data...')
        mbeya, _ = Region.objects.get_or_create(name='Mbeya')
        rungwe, _ = Region.objects.get_or_create(name='Rungwe')
        mbeya_dc, _ = District.objects.get_or_create(name='Mbeya District Council', region=mbeya)
        mbeya_cc, _ = District.objects.get_or_create(name='Mbeya City Council', region=mbeya)
        rungwe_dc, _ = District.objects.get_or_create(name='Rungwe District', region=rungwe)
        kyela, _ = District.objects.get_or_create(name='Kyela District', region=mbeya)
        chunya, _ = District.objects.get_or_create(name='Chunya District', region=mbeya)
        wards_data = [
            ('Iyunga Ward', mbeya_dc), ('Iwambi Ward', mbeya_dc), ('Itiji Ward', mbeya_dc),
            ('Iziwa Ward', mbeya_cc), ('Mwanjelwa Ward', mbeya_cc),
            ('Kiwira Ward', rungwe_dc), ('Tukuyu Ward', rungwe_dc),
            ('Ipinda Ward', kyela), ('Kyela Ward', kyela), ('Chunya Ward', chunya),
        ]
        ward_objs = {}
        for name, dist in wards_data:
            w, _ = Ward.objects.get_or_create(name=name, district=dist)
            ward_objs[name] = w
        villages_data = [
            ('Iyunga Village', 'Iyunga Ward'), ('Iwambi Village', 'Iwambi Ward'),
            ('Itiji Village', 'Itiji Ward'), ('Iziwa Village', 'Iziwa Ward'),
            ('Mwanjelwa Village', 'Mwanjelwa Ward'), ('Kiwira Village', 'Kiwira Ward'),
            ('Tukuyu Village', 'Tukuyu Ward'), ('Ipinda Village', 'Ipinda Ward'),
            ('Kyela Village', 'Kyela Ward'), ('Chunya Village', 'Chunya Ward'),
        ]
        village_objs = {}
        for name, ward_name in villages_data:
            v, _ = Village.objects.get_or_create(name=name, ward=ward_objs[ward_name])
            village_objs[name] = v
        seed_types_data = [
            ('Maize SC403', 'kg'), ('Maize DK8031', 'kg'), ('Rice Supa', 'kg'),
            ('Beans Jesca', 'kg'), ('Sunflower Hysun', 'kg'), ('Sorghum Serena', 'kg'),
        ]
        seed_objs = {}
        for name, unit in seed_types_data:
            st, _ = SeedType.objects.get_or_create(name=name, defaults={'unit': unit})
            seed_objs[name] = st
        if not SeedInventory.objects.exists():
            for sname, unit in seed_types_data:
                SeedInventory.objects.create(
                    seed_type=seed_objs[sname], quantity=5000,
                    date_received=date(2025, 1, 15), source='TARI Uyole', region=mbeya
                )
        season, _ = FarmingSeasons.objects.get_or_create(
            name='Long Rains 2025',
            defaults={'start_date': date(2025,2,1), 'end_date': date(2025,7,31), 'is_active': True}
        )
        admin_user, c = CustomUser.objects.get_or_create(username='admin', defaults={
            'first_name':'System','last_name':'Admin','role':'admin','is_staff':True,'is_superuser':True
        })
        if c: admin_user.set_password('admin123'); admin_user.save()
        reg_user, c = CustomUser.objects.get_or_create(username='regional_officer', defaults={
            'first_name':'John','last_name':'Mwakipesile','role':'regional','region':mbeya
        })
        if c: reg_user.set_password('pass1234'); reg_user.save()
        dist_user, c = CustomUser.objects.get_or_create(username='district_officer', defaults={
            'first_name':'Mary','last_name':'Ngowi','role':'district','region':mbeya,'district':mbeya_dc
        })
        if c: dist_user.set_password('pass1234'); dist_user.save()
        ward_user, c = CustomUser.objects.get_or_create(username='ward_officer', defaults={
            'first_name':'Peter','last_name':'Banda','role':'ward','region':mbeya,'district':mbeya_dc,'ward':ward_objs['Iyunga Ward']
        })
        if c: ward_user.set_password('pass1234'); ward_user.save()
        vill_user, c = CustomUser.objects.get_or_create(username='village_officer', defaults={
            'first_name':'Grace','last_name':'Mwamba','role':'village','region':mbeya,
            'district':mbeya_dc,'ward':ward_objs['Iyunga Ward'],'village':village_objs['Iyunga Village']
        })
        if c: vill_user.set_password('pass1234'); vill_user.save()

        # Give the demo Iyunga chain (the only villages/wards with real officer logins) real stock,
        # so village_officer can immediately try creating new allocations through the UI.
        if not StockTransfer.objects.exists():
            iyunga_ward = ward_objs['Iyunga Ward']
            iyunga_village = village_objs['Iyunga Village']
            for sname, unit in seed_types_data:
                st = seed_objs[sname]
                StockTransfer.objects.create(
                    seed_type=st, quantity=1200, level='region_to_district', kind='distribution', status='approved',
                    from_region=mbeya, to_district=mbeya_dc, initiated_by=reg_user, responded_by=reg_user,
                    notes='Initial regional distribution'
                )
                StockTransfer.objects.create(
                    seed_type=st, quantity=600, level='district_to_ward', kind='distribution', status='approved',
                    from_district=mbeya_dc, to_ward=iyunga_ward, initiated_by=dist_user, responded_by=dist_user,
                    notes='Initial district distribution'
                )
                StockTransfer.objects.create(
                    seed_type=st, quantity=300, level='ward_to_village', kind='distribution', status='approved',
                    from_ward=iyunga_ward, to_village=iyunga_village, initiated_by=ward_user, responded_by=ward_user,
                    notes='Initial ward distribution'
                )

        farmers_data = [
            ('Abedi','Luvanda','0754100001','Iyunga Village','maize'),
            ('Fatuma','Mwambene','0756200002','Iyunga Village','rice'),
            ('Joseph','Kapembwa','0712300003','Iwambi Village','beans'),
            ('Rehema','Sanga','0762400004','Iwambi Village','maize'),
            ('Simon','Chilumba','0714500005','Kiwira Village','sunflower'),
            ('Amina','Phiri','0754600006','Tukuyu Village','sorghum'),
            ('Daniel','Mwenye','0716700007','Kyela Village','maize'),
            ('Zaituni','Hamisi','0764800008','Ipinda Village','rice'),
            ('Moses','Tembo','0754900009','Chunya Village','maize'),
            ('Esther','Mwale','0756000010','Iziwa Village','beans'),
        ]
        farmer_objs = []
        for fn, ln, phone, vname, crop in farmers_data:
            f, _ = Farmer.objects.get_or_create(phone_number=phone, defaults={
                'first_name':fn,'last_name':ln,'village':village_objs[vname],'crop_type':crop,'registered_by':vill_user
            })
            farmer_objs.append(f)
        seed_map = {'maize': 'Maize SC403','rice': 'Rice Supa','beans': 'Beans Jesca','sunflower': 'Sunflower Hysun','sorghum': 'Sorghum Serena'}
        if not SeedAllocation.objects.exists():
            for i, farmer in enumerate(farmer_objs):
                sn = seed_map.get(farmer.crop_type, 'Maize SC403')
                st = seed_objs[sn]
                # Village officers allocate + approve their own farmers now - no pending/rejected states
                status = ['approved','distributed'][i % 2]
                a = SeedAllocation.objects.create(
                    farmer=farmer, seed_type=st, season=season, quantity_allocated=25,
                    status=status, collection_date=date(2025,3,15),
                    collection_location=f'{farmer.village.name} Collection Point',
                    requested_by=vill_user, approved_by=vill_user, sms_sent=True,
                )
                from core.models import SMSLog
                SMSLog.objects.create(farmer=farmer, phone_number=farmer.phone_number,
                    message=f"Dear {farmer.full_name}, your {st.name} allocation of 25kg is approved. Collect at {a.collection_location} on 15 Mar 2025.",
                    status='sent', allocation=a)
                if status == 'distributed':
                    Distribution.objects.create(allocation=a, quantity_distributed=25, collection_date=date(2025,3,16), confirmed_by=vill_user)
        self.stdout.write(self.style.SUCCESS('\n✓ Demo data seeded!\n'))
        self.stdout.write('LOGIN CREDENTIALS:')
        self.stdout.write('  admin           / admin123')
        self.stdout.write('  regional_officer / pass1234')
        self.stdout.write('  district_officer / pass1234')
        self.stdout.write('  ward_officer     / pass1234')
        self.stdout.write('  village_officer  / pass1234')
