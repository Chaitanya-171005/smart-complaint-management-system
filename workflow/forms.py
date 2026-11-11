from django import forms


class ProgressForm(forms.Form):
    revision = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    remarks = forms.CharField(required=False, max_length=2000, widget=forms.Textarea)


class ResolutionForm(forms.Form):
    revision = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    remarks = forms.CharField(min_length=20, max_length=2000, widget=forms.Textarea)
    # The view passes the COMPLETE request.FILES batch to B09. A forms.FileField
    # would silently select one file unless a custom multi-file field is used.


class ConfirmationForm(forms.Form):
    revision = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    rating = forms.RegexField(regex=r"\A[1-5]\Z", required=False,
                              label="Optional rating (1–5)")

    def clean_rating(self):
        value = self.cleaned_data["rating"]
        return int(value) if value else None
