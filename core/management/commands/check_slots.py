from django.core.management.base import BaseCommand
from core.models import Tenant, BusinessHours, Professional, ProfessionalAvailability, ProfessionalService, Service
from datetime import date, timedelta


class Command(BaseCommand):
    help = "Debug slots"

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        for t in tenants:
            self.stdout.write("\n=== {} (slug={}) ===".format(t.name, t.slug))
            bhs = BusinessHours.objects.bypass_tenant().filter(tenant=t, is_open=True)
            for bh in bhs:
                self.stdout.write("  BH: {} OPEN {}-{}".format(bh.get_weekday_display(), bh.open_time, bh.close_time))
            profs = Professional.objects.bypass_tenant().filter(tenant=t, is_active=True)
            for p in profs:
                self.stdout.write("  Prof: {} (user={})".format(p, p.user.email))
                avails = ProfessionalAvailability.objects.bypass_tenant().filter(
                    tenant=t, professional=p, available=True
                )
                for a in avails:
                    self.stdout.write("    Avail: {} {}-{}".format(a.get_weekday_display(), a.start_time, a.end_time))
                psvcs = ProfessionalService.objects.bypass_tenant().filter(professional=p)
                for ps in psvcs:
                    self.stdout.write("    Service: {} ({}min)".format(ps.service.name, ps.service.duration_minutes))

        self.stdout.write("\n\n=== SIMULANDO _get_available_slots ===")
        t = tenants.first()
        if t:
            prof = Professional.objects.bypass_tenant().filter(tenant=t, is_active=True).first()
            svc = Service.objects.bypass_tenant().filter(tenant=t, is_active=True).first()
            if prof and svc:
                tomorrow = date.today() + timedelta(days=1)
                wd = (tomorrow.weekday() + 1) % 7
                self.stdout.write("Date: {} weekday_python={} weekday_sistema={}".format(tomorrow, tomorrow.weekday(), wd))
                bh = BusinessHours.objects.bypass_tenant().filter(tenant=t, weekday=wd).first()
                self.stdout.write("BusinessHours for weekday {}: is_open={}".format(wd, bh.is_open if bh else "N/A"))
                avail = ProfessionalAvailability.objects.bypass_tenant().filter(
                    tenant=t, professional=prof, weekday=wd
                ).first()
                self.stdout.write("Availability for weekday {}: available={}".format(wd, avail.available if avail else "N/A"))
                if avail and avail.available:
                    self.stdout.write("  start={} end={}".format(avail.start_time, avail.end_time))
                    if avail.break_start:
                        self.stdout.write("  break={}-{}".format(avail.break_start, avail.break_end))
