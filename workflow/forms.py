from django import forms


class ProgressForm(forms.Form):
    revision = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    remarks = forms.CharField(required=False, max_length=2000, widget=forms.Textarea)


class ResolutionForm(forms.Form):
    revision = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    remarks = forms.CharField(min_length=20, max_length=2000, widget=forms.Textarea)
    # The view passes the COMPLETE request.FILES batch to B09. A forms.FileField
    # would silently select one file unless a custom multi-file field is used.
