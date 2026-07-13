import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


def gerar_cpf():
    def digito(digits):
        s = sum(d * (len(digits) + 1 - i) for i, d in enumerate(digits))
        r = 11 - (s % 11)
        return 0 if r >= 11 else r
    base = [random.randint(0, 9) for _ in range(9)]
    d1 = digito(base)
    d2 = digito(base + [d1])
    return "".join(str(d) for d in base + [d1, d2])


class Command(BaseCommand):
    help = "Preenche CPF para usuarios que nao possuem"

    def handle(self, *args, **options):
        User = get_user_model()
        existentes = set(User.objects.exclude(cpf__isnull=True).exclude(cpf="").values_list("cpf", flat=True))
        qs = User.objects.filter(cpf__isnull=True) | User.objects.filter(cpf="")
        count = 0
        for user in qs.iterator():
            while True:
                cpf = gerar_cpf()
                if cpf not in existentes:
                    break
            user.cpf = cpf
            user.save(update_fields=["cpf"])
            existentes.add(cpf)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"{count} CPFs preenchidos."))
