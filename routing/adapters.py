"""Routing reference data for complaint intake."""

from complaints.reference_data import CategoryOption

from .models import Category


def category_options():
    return tuple(CategoryOption(key=str(category.pk), name=category.name)
                 for category in Category.objects.filter(active=True).order_by("name"))
