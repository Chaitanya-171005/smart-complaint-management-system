"""B07: server-side intake validation (SRS REQ-CMP-01, DOM-02, Appendix B-2)."""

from django import forms

from .reference_data import CategoryOption, LocationOption


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
    sub_category = forms.CharField(label="Sub-category", max_length=50, required=False)
    location = forms.ChoiceField(choices=())
    title = forms.CharField(max_length=120)
    description = forms.CharField(
        min_length=20, max_length=2000, widget=forms.Textarea
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
        for option in options:
            if not isinstance(option, expected_type):
                raise TypeError(f"Expected server-supplied {expected_type.__name__} records.")
            if not isinstance(option.key, str) or not option.key.strip():
                raise ValueError("Reference keys must be nonempty strings.")
            if option.active:
                if option.key in result:
                    raise ValueError("Active reference keys must be unique.")
                result[option.key] = option
        return result

    def clean_category(self):
        option = self._categories[self.cleaned_data["category"]]
        try:
            name = forms.CharField(max_length=50, strip=False).clean(option.name)
            if not name.strip():
                raise forms.ValidationError("Category name is required.")
        except forms.ValidationError as error:
            raise forms.ValidationError(
                "This category is not configured correctly. Select another category."
            ) from error
        return option

    def clean_location(self):
        option = self._locations[self.cleaned_data["location"]]
        try:
            block = forms.CharField(max_length=20, strip=False).clean(option.block)
            forms.CharField(max_length=10, strip=False, required=False).clean(option.floor)
            room = forms.CharField(max_length=30, strip=False).clean(option.room_area)
            if not block.strip() or not room.strip():
                raise forms.ValidationError("Block and room/area are required.")
        except forms.ValidationError as error:
            raise forms.ValidationError(
                "This location is not configured correctly. Select another location."
            ) from error
        return option
