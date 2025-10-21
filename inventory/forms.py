from django import forms

from .models import (
    Project,
    StockAdjustment,
    StockEntry,
    StockRequest,
    Supplier,
    UserProfile,
    Warehouse,
)


class DateInput(forms.DateInput):
    input_type = "date"


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


class StockEntryForm(forms.ModelForm):
    class Meta:
        model = StockEntry
        fields = [
            "product",
            "warehouse",
            "quantity",
            "unit_cost",
            "supplier",
            "invoice_number",
            "received_at",
        ]
        widgets = {
            "received_at": DateTimeInput(),
        }


class StockRequestForm(forms.ModelForm):
    class Meta:
        model = StockRequest
        fields = ["product", "project", "warehouse", "quantity", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class StockAdjustmentForm(forms.ModelForm):
    class Meta:
        model = StockAdjustment
        fields = ["product", "warehouse", "quantity_change", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact", "email", "phone"]


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "location"]


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "code", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["manager"]
        widgets = {"manager": forms.Select(attrs={"class": "form-select me-2"})}
