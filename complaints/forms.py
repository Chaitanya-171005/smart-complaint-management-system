"""B07: server-side intake validation (SRS REQ-CMP-01, DOM-02, Appendix B-2)."""

import logging

from django import forms

from .reference_data import CategoryOption, LocationOption
from .validators import validate_description, validate_single_line, visible_length

logger = logging.getLogger(__name__)


class SingleLineField(forms.CharField):
    def to_python(self, value):
        # Inspect before CharField strips leading/trailing newlines or tabs.
        if isinstance(value, str):
            validate_single_line(value)
        return super().to_python(value)


class ComplaintForm(forms.Form):
    class Priority:
        LOW = "LOW"
        MEDIUM = "MEDIUM"
        HIGH = "HIGH"
        CRITICAL = "CRITICAL"

        CHOICES = (
            (LOW, "Low"),
            (MEDIUM, "Medium"),
            (HIGH, "High"),
            (CRITICAL, "Critical"),
        )

    category = forms.ChoiceField(choices=())
    sub_category = SingleLineField(label="Sub-category", max_length=50, required=False)
    location = forms.ChoiceField(choices=())
    title = SingleLineField(max_length=120)
    description = forms.CharField(
        min_length=20, max_length=2000, widget=forms.Textarea,
        validators=[validate_description],
    )
    priority = forms.ChoiceField(choices=Priority.CHOICES, initial=Priority.MEDIUM)

    def __init__(self, *args, categories, locations, **kwargs):
        super().__init__(*args, **kwargs)
        self._categories = self._active_options(categories, CategoryOption)
        self._locations = self._active_options(locations, LocationOption)
        self.fields["category"].choices = [("", "Select category")] + [
            (key, option.name) for key, option in self._categories.items()
        ]
        self.fields["location"].choices = [("", "Select location")] + [
            (key, option.label) for key, option in self._locations.items()
        ]

    @staticmethod
    def _active_options(options, expected_type):
        result = {}
        seen = set()
        for option in options:
            if not isinstance(option, expected_type):
                logger.warning("Ignoring invalid intake reference record (%s).", expected_type.__name__)
                continue
            # Inactive master data must never disrupt the active intake options.
            if option.active is False:
                continue
            try:
                if option.active is not True:
                    raise forms.ValidationError("Active must be a boolean.")
                ComplaintForm._reference_text(option.key)
                if isinstance(option, CategoryOption):
                    ComplaintForm._reference_text(option.name, max_length=50)
                else:
                    ComplaintForm._reference_text(option.block, max_length=20)
                    ComplaintForm._reference_text(option.floor, max_length=10, required=False)
                    ComplaintForm._reference_text(option.room_area, max_length=30)
            except forms.ValidationError:
                # Log the kind, never raw configuration text/control characters.
                logger.warning("Ignoring invalid intake reference record (%s).", expected_type.__name__)
                continue
            if option.key in seen:
                # Neither of two ambiguous active records may be selected.
                result.pop(option.key, None)
                logger.warning("Ignoring duplicate intake reference key (%s).", expected_type.__name__)
                continue
            seen.add(option.key)
            result[option.key] = option
        return result

    @staticmethod
    def _reference_text(value, max_length=None, required=True):
        if not isinstance(value, str):
            raise forms.ValidationError("Reference text must be a string.")
        validate_single_line(value)
        if required and not visible_length(value):
            raise forms.ValidationError("Reference text is required.")
        if max_length is not None and len(value) > max_length:
            raise forms.ValidationError("Reference text exceeds its limit.")

    def clean_category(self):
        return self._categories[self.cleaned_data["category"]]

    def clean_location(self):
        return self._locations[self.cleaned_data["location"]]
