from datetime import date

from common.test_utils import ApiTestCase, TwoOrganizationApiTestCase

from .models import DabingPerson, DabingRecord, DabingStore, KyotoDrawBatch, KyotoPerson, KyotoRecord


class LotteryWorkflowTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login_as(self.admin)

    def test_dabing_stores_are_seeded_separately_from_operational_branches(self):
        response = self.client.get('/api/lottery/dabing-stores/?is_active=true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['name'] for row in response.data], ['天王寺', '高岛屋', '梅田'])
        self.assertEqual(DabingStore.objects.count(), 3)

    def test_dabing_record_snapshots_person_data_and_lists_by_store_and_date(self):
        store = DabingStore.objects.create(organization=self.org, name='京都', sort_order=10)
        person = DabingPerson.objects.create(
            organization=self.org, name='DEMO/TEST 大饼', phone='09012341749', birthday=date(1990, 1, 2), mobile_model='povo',
        )
        response = self.client.post('/api/lottery/dabing-records/', {
            'store': store.id, 'person': person.id, 'draw_date': '2026-08-31', 'draw_time': '10点',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        record = DabingRecord.objects.get()
        self.assertEqual(record.organization_id, self.org.id)
        self.assertEqual(record.phone_snapshot, '09012341749')
        self.assertEqual(record.birthday_snapshot, date(1990, 1, 2))
        self.assertEqual(response.data['phone_last_four'], '1749')

        listed = self.client.get(f'/api/lottery/dabing-records/?draw_date=2026-08-31&store={store.id}')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)
        self.assertEqual(listed.data[0]['store_name'], '京都')

        duplicate = self.client.post('/api/lottery/dabing-records/', {
            'store': store.id, 'person': person.id, 'draw_date': '2026-08-31', 'draw_time': '10点',
        }, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('record-already-exists', str(duplicate.data))

    def test_kyoto_record_uses_its_own_batch_and_person_tables(self):
        batch = KyotoDrawBatch.objects.create(
            organization=self.org, draw_start_date=date(2026, 8, 14), draw_end_date=date(2026, 8, 16), publish_date=date(2026, 8, 27),
        )
        person = KyotoPerson.objects.create(organization=self.org, name='DEMO/TEST 京都', phone='09055556666')
        response = self.client.post('/api/lottery/kyoto-records/', {'batch': batch.id, 'person': person.id}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(KyotoRecord.objects.count(), 1)
        self.assertEqual(response.data['batch_label'], '2026-08-14〜2026-08-16')
        self.assertEqual(response.data['phone_last_four'], '6666')

        duplicate = self.client.post('/api/lottery/kyoto-records/', {'batch': batch.id, 'person': person.id}, format='json')
        self.assertEqual(duplicate.status_code, 400)

    def test_dabing_records_filter_by_date_range_and_name_search(self):
        store = DabingStore.objects.create(organization=self.org, name='梅田', sort_order=1)
        alice = DabingPerson.objects.create(organization=self.org, name='DEMO Alice', phone='09011112222')
        bob = DabingPerson.objects.create(organization=self.org, name='DEMO Bob', phone='09033334444')
        DabingRecord.objects.create(organization=self.org, store=store, person=alice, draw_date=date(2026, 8, 1))
        DabingRecord.objects.create(organization=self.org, store=store, person=bob, draw_date=date(2026, 8, 20), phone_snapshot='09033334444')
        DabingRecord.objects.create(organization=self.org, store=store, person=alice, draw_date=date(2026, 9, 5))

        ranged = self.client.get('/api/lottery/dabing-records/?date_from=2026-08-01&date_to=2026-08-31')
        self.assertEqual(ranged.status_code, 200)
        self.assertEqual(len(ranged.data), 2)

        searched = self.client.get('/api/lottery/dabing-records/?date_from=2026-01-01&date_to=2026-12-31&search=alice')
        self.assertEqual([row['person_name'] for row in searched.data], ['DEMO Alice', 'DEMO Alice'])

        by_tail = self.client.get('/api/lottery/dabing-records/?search=3333')
        self.assertEqual(len(by_tail.data), 1)
        self.assertEqual(by_tail.data[0]['person_name'], 'DEMO Bob')

    def test_kyoto_records_filter_across_batches_by_publish_date_and_name(self):
        early = KyotoDrawBatch.objects.create(
            organization=self.org, draw_start_date=date(2026, 7, 1), draw_end_date=date(2026, 7, 3), publish_date=date(2026, 7, 15),
        )
        late = KyotoDrawBatch.objects.create(
            organization=self.org, draw_start_date=date(2026, 8, 1), draw_end_date=date(2026, 8, 3), publish_date=date(2026, 8, 27),
        )
        carol = KyotoPerson.objects.create(organization=self.org, name='DEMO Carol', phone='09055556666')
        dave = KyotoPerson.objects.create(organization=self.org, name='DEMO Dave', phone='09077778888')
        KyotoRecord.objects.create(organization=self.org, batch=early, person=carol)
        KyotoRecord.objects.create(organization=self.org, batch=late, person=carol)
        KyotoRecord.objects.create(organization=self.org, batch=late, person=dave)

        all_rows = self.client.get('/api/lottery/kyoto-records/')
        self.assertEqual(len(all_rows.data), 3)

        windowed = self.client.get('/api/lottery/kyoto-records/?publish_from=2026-08-01&publish_to=2026-08-31')
        self.assertEqual(len(windowed.data), 2)

        by_name = self.client.get('/api/lottery/kyoto-records/?search=carol')
        self.assertEqual(len(by_name.data), 2)
        self.assertTrue(all(row['person_name'] == 'DEMO Carol' for row in by_name.data))

    def test_staff_account_can_use_shared_lottery_workspace(self):
        self.login_as(self.staff_user)
        store = DabingStore.objects.create(organization=self.org, name='共享店铺')
        person = DabingPerson.objects.create(organization=self.org, name='DEMO/TEST 多用户')
        response = self.client.post('/api/lottery/dabing-records/', {
            'store': store.id, 'person': person.id, 'draw_date': '2026-08-31', 'draw_time': '10点',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['created_by_name'], self.staff_user.username)


class LotteryOrganizationIsolationTests(TwoOrganizationApiTestCase):
    def test_organization_cannot_read_or_write_another_organizations_lottery_data(self):
        foreign_store = DabingStore.objects.create(organization=self.org_b, name='B店')
        foreign_person = DabingPerson.objects.create(organization=self.org_b, name='B人员')
        self.login_as(self.admin_a)
        response = self.client.get('/api/lottery/dabing-stores/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('B店', [row['name'] for row in response.data])

        response = self.client.post('/api/lottery/dabing-records/', {
            'store': foreign_store.id, 'person': foreign_person.id, 'draw_date': '2026-08-31', 'draw_time': '10点',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(DabingRecord.objects.count(), 0)
