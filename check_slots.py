from core.models import Tenant, BusinessHours, Professional, ProfessionalAvailability, ProfessionalService, Service
from datetime import date, timedelta

tenants = Tenant.objects.all()
for t in tenants:
    print(f"\n=== {t.name} (slug={t.slug}) ===")
    bhs = BusinessHours.objects.bypass_tenant().filter(tenant=t, is_open=True)
    for bh in bhs:
        print(f"  BH: {bh.get_weekday_display()} OPEN {bh.open_time}-{bh.close_time}")
    profs = Professional.objects.bypass_tenant().filter(tenant=t, is_active=True)
    for p in profs:
        print(f"  Prof: {p} (user={p.user.email})")
        avails = ProfessionalAvailability.objects.bypass_tenant().filter(
            tenant=t, professional=p, available=True
        )
        for a in avails:
            print(f"    Avail: {a.get_weekday_display()} {a.start_time}-{a.end_time}")
        psvcs = ProfessionalService.objects.bypass_tenant().filter(professional=p)
        for ps in psvcs:
            print(f"    Service: {ps.service.name} ({ps.service.duration_minutes}min)")

print("\n\n=== SIMULANDO _get_available_slots ===")
t = tenants.first()
if t:
    prof = Professional.objects.bypass_tenant().filter(tenant=t, is_active=True).first()
    svc = Service.objects.bypass_tenant().filter(tenant=t, is_active=True).first()
    if prof and svc:
        tomorrow = date.today() + timedelta(days=1)
        wd = (tomorrow.weekday() + 1) % 7
        print(f"Date: {tomorrow} weekday_python={tomorrow.weekday()} weekday_sistema={wd}")
        bh = BusinessHours.objects.bypass_tenant().filter(tenant=t, weekday=wd).first()
        print(f"BusinessHours for weekday {wd}: is_open={bh.is_open if bh else 'N/A'}")
        avail = ProfessionalAvailability.objects.bypass_tenant().filter(
            tenant=t, professional=prof, weekday=wd
        ).first()
        print(f"Availability for weekday {wd}: available={avail.available if avail else 'N/A'}")
        if avail and avail.available:
            print(f"  start={avail.start_time} end={avail.end_time}")
            if avail.break_start:
                print(f"  break={avail.break_start}-{avail.break_end}")
