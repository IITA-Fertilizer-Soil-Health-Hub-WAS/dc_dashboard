from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Look up a dict value by a variable key in templates."""
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None
