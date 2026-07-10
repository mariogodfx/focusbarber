from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    return d.get(key)

@register.filter
def format_name(value):
    if not value:
        return value
    parts = value.strip().split()
    if len(parts) == 1:
        return parts[0].capitalize()
    prepositions = {"da", "de", "do", "das", "dos"}
    first = parts[0].capitalize()
    middle = []
    for p in parts[1:-1]:
        if p.lower() not in prepositions:
            middle.append(p[0].upper() + ".")
    last = parts[-1]
    if last.lower() not in prepositions:
        last = last[:3].capitalize() + "."
    else:
        last = ""
    result = " ".join([first] + middle)
    if last:
        result += " " + last
    return result

@register.filter
def format_name_full(value):
    if not value:
        return value
    parts = value.strip().split()
    if len(parts) == 1:
        return parts[0].capitalize()
    prepositions = {"da", "de", "do", "das", "dos"}
    first = parts[0].capitalize()
    middle = []
    for p in parts[1:-1]:
        if p.lower() not in prepositions:
            middle.append(p[0].upper() + ".")
    last = parts[-1]
    if last.lower() not in prepositions:
        last = last.capitalize()
    else:
        last = ""
    result = " ".join([first] + middle)
    if last:
        result += " " + last
    return result
