from django.contrib import admin

from .models import DabingPerson, DabingRecord, DabingStore, KyotoDrawBatch, KyotoPerson, KyotoRecord


admin.site.register([DabingStore, DabingPerson, DabingRecord, KyotoPerson, KyotoDrawBatch, KyotoRecord])
