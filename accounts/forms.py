import hmac

from django.conf import settings
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

User = get_user_model()


class UserRegistrationForm(forms.ModelForm):
    role = forms.ChoiceField(
        choices=User.ROLE_CHOICES,
        initial=User.ROLE_MEMBER,
        widget=forms.Select(attrs={
            'class': 'form-select auth-input',
            'aria-describedby': 'role-error',
        }),
    )
    admin_access_code = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control auth-input',
            'placeholder': 'Enter the admin access code',
            'autocomplete': 'off',
            'aria-describedby': 'admin_access_code-error',
        }),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control auth-input',
            'type': 'email',
            'placeholder': 'you@company.com',
            'autocomplete': 'email',
            'aria-describedby': 'email-error',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control auth-input',
            'placeholder': 'Create a secure password',
            'autocomplete': 'new-password',
            'aria-describedby': 'password-help password-error',
        }),
        min_length=6,
        help_text='At least 6 characters.'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control auth-input',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password',
            'aria-describedby': 'confirm_password-error',
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'department', 'job_title']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control auth-input',
                'placeholder': 'Choose a username',
                'autocomplete': 'username',
                'aria-describedby': 'username-error',
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control auth-input',
                'placeholder': 'First name',
                'autocomplete': 'given-name',
                'aria-describedby': 'first_name-error',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control auth-input',
                'placeholder': 'Last name',
                'autocomplete': 'family-name',
                'aria-describedby': 'last_name-error',
            }),
            'department': forms.TextInput(attrs={
                'class': 'form-control auth-input',
                'placeholder': 'e.g. Design',
                'aria-describedby': 'department-error',
            }),
            'job_title': forms.TextInput(attrs={
                'class': 'form-control auth-input',
                'placeholder': 'e.g. Product designer',
                'aria-describedby': 'job_title-error',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with that email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        access_code = cleaned_data.get('admin_access_code', '')
        if role == User.ROLE_ADMIN:
            configured_code = settings.ADMIN_REGISTRATION_CODE
            if not configured_code:
                self.add_error('role', "Admin registration is currently unavailable.")
            elif not hmac.compare_digest(
                access_code.encode('utf-8'),
                configured_code.encode('utf-8'),
            ):
                self.add_error('admin_access_code', "The admin access code is invalid.")

        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_password', "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data['role']
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control auth-input',
            'placeholder': 'you@company.com or username',
            'autocomplete': 'username',
            'autofocus': True,
            'aria-describedby': 'username-error',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control auth-input',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password',
            'aria-describedby': 'password-error',
        })
    )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'department', 'job_title', 'bio']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class AdminUserCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Initial password'}),
        min_length=6
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'role', 'department', 'job_title', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user
