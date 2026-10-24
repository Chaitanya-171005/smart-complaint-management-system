from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import User


class RegistrationForm(forms.Form):
    """Public registration form (REQ-AUTH-01).

    There is deliberately no role field: new accounts are always Complainant,
    and any role value sent in a modified request is ignored (BR-04).
    """

    full_name = forms.CharField(max_length=100)
    email = forms.EmailField(max_length=120)
    password = forms.CharField(widget=forms.PasswordInput, strip=False)
    user_type = forms.ChoiceField(choices=User.UserType.choices)
    hostel_resident = forms.BooleanField(required=False, label="I live in a hostel")
    hostel_block = forms.CharField(max_length=20, required=False)
    hostel_room = forms.CharField(max_length=10, required=False)

    def clean_full_name(self):
        name = self.cleaned_data["full_name"].strip()
        if not name:
            raise forms.ValidationError("Full name is required.")
        return name

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("hostel_resident"):
            for field in ("hostel_block", "hostel_room"):
                if not (cleaned.get(field) or "").strip():
                    self.add_error(field, "Required for hostel residents.")
        else:
            cleaned["hostel_block"] = ""
            cleaned["hostel_room"] = ""
        return cleaned
