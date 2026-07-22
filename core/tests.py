from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

from core.models import (
    Region, District, Ward, Village, CustomUser, SeedType, SeedInventory,
    FarmingSeasons, Farmer, SeedAllocation, StockTransfer, SeedRequest, Distribution,
)
from core.decorators import user_can_access_farmer
from core.stock import region_balance, district_balance, ward_balance, village_balance
from core.views import create_farmer_allocation


class SeedTrackerTestCase(TestCase):
    """Shared fixture: one region -> one district -> two wards -> two villages,
    mirroring the shape of core/management/commands/seed_data.py but trimmed for speed."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name='Mbeya')
        cls.district = District.objects.create(name='Mbeya District Council', region=cls.region)
        cls.ward = Ward.objects.create(name='Iyunga Ward', district=cls.district)
        cls.other_ward = Ward.objects.create(name='Itiji Ward', district=cls.district)
        cls.village = Village.objects.create(name='Iyunga Village', ward=cls.ward)
        cls.other_village = Village.objects.create(name='Itiji Village', ward=cls.other_ward)

        cls.seed_type = SeedType.objects.create(name='Maize SC403', unit='kg')
        cls.season = FarmingSeasons.objects.create(
            name='Long Rains 2025', start_date=date(2025, 2, 1), end_date=date(2025, 7, 31), is_active=True
        )

        cls.admin = CustomUser.objects.create_superuser('admin_t', 'admin@test.com', 'AdminPass123!', role='admin')
        cls.regional = CustomUser.objects.create_user('regional_t', password='Pass1234!', role='regional', region=cls.region)
        cls.district_officer = CustomUser.objects.create_user('district_t', password='Pass1234!', role='district', region=cls.region, district=cls.district)
        cls.ward_officer = CustomUser.objects.create_user('ward_t', password='Pass1234!', role='ward', region=cls.region, district=cls.district, ward=cls.ward)
        cls.village_officer = CustomUser.objects.create_user('village_t', password='Pass1234!', role='village', region=cls.region, district=cls.district, ward=cls.ward, village=cls.village)
        cls.extension_officer = CustomUser.objects.create_user('extension_t', password='Pass1234!', role='extension', region=cls.region, district=cls.district, ward=cls.ward)

        cls.farmer = Farmer.objects.create(
            first_name='Abedi', last_name='Luvanda', phone_number='0754100001',
            village=cls.village, crop_type='maize', registered_by=cls.village_officer,
        )
        cls.other_farmer = Farmer.objects.create(
            first_name='Zawadi', last_name='Ngoma', phone_number='0754200002',
            village=cls.other_village, crop_type='maize', registered_by=cls.village_officer,
        )

    def give_village_stock(self, quantity=Decimal('100')):
        """Push real stock all the way down to self.village so allocation/balance tests have something to work with."""
        SeedInventory.objects.create(seed_type=self.seed_type, quantity=quantity, date_received=date(2025, 1, 1), source='Test', region=self.region)
        StockTransfer.objects.create(seed_type=self.seed_type, quantity=quantity, level='region_to_district', kind='distribution',
                                      status='approved', from_region=self.region, to_district=self.district, initiated_by=self.regional, responded_by=self.regional)
        StockTransfer.objects.create(seed_type=self.seed_type, quantity=quantity, level='district_to_ward', kind='distribution',
                                      status='approved', from_district=self.district, to_ward=self.ward, initiated_by=self.district_officer, responded_by=self.district_officer)
        StockTransfer.objects.create(seed_type=self.seed_type, quantity=quantity, level='ward_to_village', kind='distribution',
                                      status='approved', from_ward=self.ward, to_village=self.village, initiated_by=self.ward_officer, responded_by=self.ward_officer)


class StockBalanceTests(SeedTrackerTestCase):
    def test_region_balance_nets_outgoing_transfers(self):
        SeedInventory.objects.create(seed_type=self.seed_type, quantity=Decimal('500'), date_received=date(2025, 1, 1), source='Test', region=self.region)
        self.assertEqual(region_balance(self.seed_type, self.region), Decimal('500'))
        StockTransfer.objects.create(seed_type=self.seed_type, quantity=Decimal('200'), level='region_to_district', kind='distribution',
                                      status='approved', from_region=self.region, to_district=self.district, initiated_by=self.regional, responded_by=self.regional)
        self.assertEqual(region_balance(self.seed_type, self.region), Decimal('300'))

    def test_pending_or_rejected_transfers_dont_count(self):
        SeedInventory.objects.create(seed_type=self.seed_type, quantity=Decimal('500'), date_received=date(2025, 1, 1), source='Test', region=self.region)
        StockTransfer.objects.create(seed_type=self.seed_type, quantity=Decimal('200'), level='region_to_district', kind='request',
                                      status='pending', from_region=self.region, to_district=self.district, initiated_by=self.district_officer)
        self.assertEqual(region_balance(self.seed_type, self.region), Decimal('500'))

    def test_full_chain_balances(self):
        self.give_village_stock(Decimal('300'))
        self.assertEqual(region_balance(self.seed_type, self.region), Decimal('0'))  # 300 in, 300 out
        self.assertEqual(district_balance(self.seed_type, self.district), Decimal('0'))
        self.assertEqual(ward_balance(self.seed_type, self.ward), Decimal('0'))
        self.assertEqual(village_balance(self.seed_type, self.village), Decimal('300'))

    def test_village_balance_nets_allocations(self):
        self.give_village_stock(Decimal('100'))
        SeedAllocation.objects.create(farmer=self.farmer, seed_type=self.seed_type, season=self.season,
                                       quantity_allocated=Decimal('30'), status='approved', requested_by=self.village_officer, approved_by=self.village_officer)
        self.assertEqual(village_balance(self.seed_type, self.village), Decimal('70'))


class CreateFarmerAllocationTests(SeedTrackerTestCase):
    def test_creates_approved_allocation_with_sms_and_log(self):
        self.give_village_stock(Decimal('100'))
        allocation, error = create_farmer_allocation(
            farmer=self.farmer, seed_type=self.seed_type, season=self.season, quantity=Decimal('25'),
            collection_date=date(2025, 3, 15), collection_location='Iyunga Point', notes='', actor=self.village_officer,
        )
        self.assertIsNone(error)
        self.assertEqual(allocation.status, 'approved')
        self.assertTrue(allocation.sms_sent)
        self.assertEqual(allocation.farmer.sms_logs.count(), 1)

    def test_rejects_duplicate_allocation(self):
        self.give_village_stock(Decimal('100'))
        create_farmer_allocation(self.farmer, self.seed_type, self.season, Decimal('20'), date(2025, 3, 15), 'x', '', self.village_officer)
        allocation, error = create_farmer_allocation(
            farmer=self.farmer, seed_type=self.seed_type, season=self.season, quantity=Decimal('10'),
            collection_date=date(2025, 3, 15), collection_location='x', notes='', actor=self.village_officer,
        )
        self.assertIsNone(allocation)
        self.assertIn('already has an allocation', error)

    def test_rejects_insufficient_stock(self):
        self.give_village_stock(Decimal('10'))
        allocation, error = create_farmer_allocation(
            farmer=self.farmer, seed_type=self.seed_type, season=self.season, quantity=Decimal('50'),
            collection_date=date(2025, 3, 15), collection_location='x', notes='', actor=self.village_officer,
        )
        self.assertIsNone(allocation)
        self.assertIn('Insufficient village stock', error)


class TerritoryAccessTests(SeedTrackerTestCase):
    def test_village_officer_scoped_to_own_village(self):
        self.assertTrue(user_can_access_farmer(self.village_officer, self.farmer))
        self.assertFalse(user_can_access_farmer(self.village_officer, self.other_farmer))

    def test_extension_officer_scoped_to_own_ward(self):
        self.assertTrue(user_can_access_farmer(self.extension_officer, self.farmer))
        self.assertFalse(user_can_access_farmer(self.extension_officer, self.other_farmer))

    def test_admin_bypasses_all_scoping(self):
        self.assertTrue(user_can_access_farmer(self.admin, self.farmer))
        self.assertTrue(user_can_access_farmer(self.admin, self.other_farmer))

    def test_seed_request_verify_blocks_cross_ward(self):
        sr = SeedRequest.objects.create(farmer=self.other_farmer, seed_type=self.seed_type, season=self.season, quantity_requested=Decimal('10'))
        client = Client()
        client.login(username='extension_t', password='Pass1234!')
        resp = client.post(f'/requests/{sr.pk}/verify/', {'verify': '1'}, follow=True)
        sr.refresh_from_db()
        self.assertEqual(sr.status, 'submitted')  # untouched
        self.assertEqual(resp.redirect_chain[-1][0], '/requests/')

    def test_seed_request_fulfill_blocks_cross_village(self):
        self.give_village_stock(Decimal('100'))
        sr = SeedRequest.objects.create(farmer=self.other_farmer, seed_type=self.seed_type, season=self.season,
                                         quantity_requested=Decimal('10'), status='verified', verified_by=self.extension_officer)
        client = Client()
        client.login(username='village_t', password='Pass1234!')
        resp = client.post(f'/requests/{sr.pk}/fulfill/', {'collection_date': '2025-04-01', 'collection_location': 'x', 'notes': ''}, follow=True)
        sr.refresh_from_db()
        self.assertEqual(sr.status, 'verified')  # untouched
        self.assertIsNone(sr.resulting_allocation)


class SeedRequestPipelineTests(SeedTrackerTestCase):
    def test_full_pipeline_farmer_to_extension_to_village(self):
        self.give_village_stock(Decimal('100'))
        farmer_user = CustomUser.objects.create_user('farmer_t', password='Pass1234!', role='farmer')
        self.farmer.user = farmer_user
        self.farmer.save(update_fields=['user'])

        farmer_client = Client()
        farmer_client.login(username='farmer_t', password='Pass1234!')
        resp = farmer_client.post('/requests/new/', {
            'seed_type': self.seed_type.id, 'season': self.season.id, 'quantity_requested': '15', 'notes': '',
        }, follow=True)
        sr = SeedRequest.objects.get(farmer=self.farmer)
        self.assertEqual(sr.status, 'submitted')

        ext_client = Client()
        ext_client.login(username='extension_t', password='Pass1234!')
        ext_client.post(f'/requests/{sr.pk}/verify/', {'verify': '1'})
        sr.refresh_from_db()
        self.assertEqual(sr.status, 'verified')
        self.assertEqual(sr.verified_by, self.extension_officer)

        vill_client = Client()
        vill_client.login(username='village_t', password='Pass1234!')
        vill_client.post(f'/requests/{sr.pk}/fulfill/', {'collection_date': '2025-04-01', 'collection_location': 'Iyunga Point', 'notes': ''})
        sr.refresh_from_db()
        self.assertEqual(sr.status, 'fulfilled')
        self.assertIsNotNone(sr.resulting_allocation)
        self.assertEqual(sr.resulting_allocation.status, 'approved')
        self.assertEqual(village_balance(self.seed_type, self.village), Decimal('85'))


class FarmerRegistrationTests(SeedTrackerTestCase):
    def test_registration_creates_linked_user_and_farmer(self):
        client = Client()
        resp = client.post('/register/', {
            'username': 'newfarmer_t', 'password1': 'GreatPass987!', 'password2': 'GreatPass987!',
            'first_name': 'Neema', 'last_name': 'Mwasomola', 'phone_number': '0788111222',
            'village': self.village.id, 'crop_type': 'maize', 'farm_location': '', 'farm_size': '', 'national_id': '',
        }, follow=True)
        user = CustomUser.objects.get(username='newfarmer_t')
        farmer = Farmer.objects.get(user=user)
        self.assertEqual(user.role, 'farmer')
        self.assertEqual(farmer.phone_number, '0788111222')
        self.assertIn(str(user.pk), client.session.get('_auth_user_id', ''))

    def test_duplicate_phone_rejected(self):
        client = Client()
        resp = client.post('/register/', {
            'username': 'dupe_t', 'password1': 'GreatPass987!', 'password2': 'GreatPass987!',
            'first_name': 'Copy', 'last_name': 'Cat', 'phone_number': self.farmer.phone_number,
            'village': self.village.id, 'crop_type': 'maize', 'farm_location': '', 'farm_size': '', 'national_id': '',
        })
        self.assertFalse(CustomUser.objects.filter(username='dupe_t').exists())
        self.assertContains(resp, 'already registered')

    def test_weak_password_rejected(self):
        client = Client()
        resp = client.post('/register/', {
            'username': 'weak_t', 'password1': '1234', 'password2': '1234',
            'first_name': 'Weak', 'last_name': 'Pass', 'phone_number': '0788999888',
            'village': self.village.id, 'crop_type': 'maize', 'farm_location': '', 'farm_size': '', 'national_id': '',
        })
        self.assertFalse(CustomUser.objects.filter(username='weak_t').exists())


class SeedRequestDuplicateTests(SeedTrackerTestCase):
    def test_fulfilled_request_blocks_new_request_same_season(self):
        SeedRequest.objects.create(farmer=self.farmer, seed_type=self.seed_type, season=self.season,
                                    quantity_requested=Decimal('10'), status='fulfilled')
        farmer_user = CustomUser.objects.create_user('farmer_dup_t', password='Pass1234!', role='farmer')
        self.farmer.user = farmer_user
        self.farmer.save(update_fields=['user'])

        client = Client()
        client.login(username='farmer_dup_t', password='Pass1234!')
        client.post('/requests/new/', {'seed_type': self.seed_type.id, 'season': self.season.id, 'quantity_requested': '5', 'notes': ''})
        self.assertEqual(SeedRequest.objects.filter(farmer=self.farmer, seed_type=self.seed_type, season=self.season).count(), 1)

    def test_rejected_request_does_not_block_resubmission(self):
        SeedRequest.objects.create(farmer=self.farmer, seed_type=self.seed_type, season=self.season,
                                    quantity_requested=Decimal('10'), status='rejected')
        farmer_user = CustomUser.objects.create_user('farmer_retry_t', password='Pass1234!', role='farmer')
        self.farmer.user = farmer_user
        self.farmer.save(update_fields=['user'])

        client = Client()
        client.login(username='farmer_retry_t', password='Pass1234!')
        client.post('/requests/new/', {'seed_type': self.seed_type.id, 'season': self.season.id, 'quantity_requested': '5', 'notes': ''})
        self.assertEqual(SeedRequest.objects.filter(farmer=self.farmer, seed_type=self.seed_type, season=self.season).count(), 2)


class ConfirmBeforeVerifyTests(SeedTrackerTestCase):
    def _create_unconfirmed_distribution(self, confirmed):
        allocation = SeedAllocation.objects.create(
            farmer=self.farmer, seed_type=self.seed_type, season=self.season,
            quantity_allocated=Decimal('20'), status='distributed',
            requested_by=self.village_officer, approved_by=self.village_officer,
        )
        Distribution.objects.create(
            allocation=allocation, quantity_distributed=Decimal('20'), confirmed_by=self.village_officer,
            farmer_confirmed=confirmed, farmer_confirmed_at=timezone.now() if confirmed else None,
        )

    def test_blocks_verify_when_farmer_has_unconfirmed_distribution(self):
        self._create_unconfirmed_distribution(confirmed=False)
        self.assertTrue(self.farmer.has_unconfirmed_distribution)
        other_seed = SeedType.objects.create(name='Rice Supa', unit='kg')
        sr = SeedRequest.objects.create(farmer=self.farmer, seed_type=other_seed, season=self.season, quantity_requested=Decimal('5'))

        client = Client()
        client.login(username='extension_t', password='Pass1234!')
        client.post(f'/requests/{sr.pk}/verify/', {'verify': '1'})
        sr.refresh_from_db()
        self.assertEqual(sr.status, 'submitted')  # still blocked

    def test_allows_verify_once_farmer_confirms(self):
        self._create_unconfirmed_distribution(confirmed=True)
        self.assertFalse(self.farmer.has_unconfirmed_distribution)
        other_seed = SeedType.objects.create(name='Rice Supa', unit='kg')
        sr = SeedRequest.objects.create(farmer=self.farmer, seed_type=other_seed, season=self.season, quantity_requested=Decimal('5'))

        client = Client()
        client.login(username='extension_t', password='Pass1234!')
        client.post(f'/requests/{sr.pk}/verify/', {'verify': '1'})
        sr.refresh_from_db()
        self.assertEqual(sr.status, 'verified')


class ForgotPasswordTests(SeedTrackerTestCase):
    @patch('core.views.send_email')
    def test_valid_token_resets_password(self, mock_send_email):
        mock_send_email.return_value = True
        self.village_officer.email = 'village@test.com'
        self.village_officer.save()

        client = Client()
        client.post('/forgot-password/', {'username_or_email': 'village_t'})
        self.assertTrue(mock_send_email.called)

        uid = urlsafe_base64_encode(force_bytes(self.village_officer.pk))
        token = default_token_generator.make_token(self.village_officer)
        client.post(f'/reset-password/{uid}/{token}/', {'new_password1': 'BrandNewPass99!', 'new_password2': 'BrandNewPass99!'})
        self.assertTrue(Client().login(username='village_t', password='BrandNewPass99!'))

    @patch('core.views.send_email')
    def test_unknown_identifier_gives_same_generic_message_and_sends_nothing(self, mock_send_email):
        client = Client()
        resp = client.post('/forgot-password/', {'username_or_email': 'nobody_here'}, follow=True)
        self.assertFalse(mock_send_email.called)
        self.assertContains(resp, 'password reset link has been sent')

    def test_tampered_token_rejected(self):
        uid = urlsafe_base64_encode(force_bytes(self.village_officer.pk))
        client = Client()
        resp = client.get(f'/reset-password/{uid}/bad-token-xyz/')
        self.assertContains(resp, 'Invalid or Expired')
        resp2 = client.post(f'/reset-password/{uid}/bad-token-xyz/', {'new_password1': 'X', 'new_password2': 'X'})
        self.assertFalse(Client().login(username='village_t', password='X'))
