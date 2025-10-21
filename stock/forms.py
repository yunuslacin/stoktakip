from django import forms
from django.contrib.auth import get_user_model

from .models import (
    Product,
    Project,
    StockAdjustment,
    StockEntry,
    StockRequest,
    Supplier,
    UserProfile,
    Warehouse,
)

User = get_user_model()


class DateInput(forms.DateInput):
    input_type = "date"


class StockEntryForm(forms.ModelForm):
    class Meta:
        model = StockEntry
        fields = [
            "product",
            "warehouse",
            "supplier",
            "invoice_number",
            "quantity",
            "unit_cost",
            "received_at",
            "notes",
        ]
        widgets = {
            "received_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("quantity", 0) <= 0:
            self.add_error("quantity", "Miktar pozitif olmalıdır.")
        if cleaned_data.get("unit_cost", 0) < 0:
            self.add_error("unit_cost", "Birim maliyet negatif olamaz.")
        return cleaned_data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["received_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]


class StockIssueForm(forms.Form):
    request = forms.ModelChoiceField(
        queryset=StockRequest.objects.none(), required=False, label="İlgili Talep"
    )
    product = forms.ModelChoiceField(queryset=Product.objects.all())
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.all())
    project = forms.ModelChoiceField(queryset=Project.objects.all())
    quantity = forms.IntegerField(min_value=1)
    note = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["request"].queryset = StockRequest.objects.filter(
            status=StockRequest.STATUS_APPROVED
        )

    def clean(self):
        cleaned_data = super().clean()
        request_obj = cleaned_data.get("request")
        if request_obj:
            if cleaned_data.get("product") and cleaned_data["product"] != request_obj.product:
                self.add_error("product", "Talep ile aynı ürünü seçmelisiniz.")
            if cleaned_data.get("warehouse") and cleaned_data["warehouse"] != request_obj.warehouse:
                self.add_error("warehouse", "Talep ile aynı depoyu seçmelisiniz.")
            if cleaned_data.get("project") and cleaned_data["project"] != request_obj.project:
                self.add_error("project", "Talep ile aynı projeyi seçmelisiniz.")
            if cleaned_data.get("quantity") and cleaned_data["quantity"] != request_obj.quantity:
                self.add_error("quantity", "Talep edilen miktarı kullanmalısınız.")
        return cleaned_data


class StockRequestForm(forms.ModelForm):
    class Meta:
        model = StockRequest
        fields = [
            "product",
            "quantity",
            "warehouse",
            "project",
            "need_by_date",
            "description",
        ]
        widgets = {
            "need_by_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class StockApprovalForm(forms.ModelForm):
    status = forms.ChoiceField(
        choices=[
            (StockRequest.STATUS_APPROVED, "Onayla"),
            (StockRequest.STATUS_REJECTED, "Reddet"),
        ],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = StockRequest
        fields = ["status", "decision_reason"]
        widgets = {"decision_reason": forms.Textarea(attrs={"rows": 3})}


class StockAdjustmentForm(forms.ModelForm):
    class Meta:
        model = StockAdjustment
        fields = ["product", "warehouse", "quantity_change", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 2})}


class UserProfileForm(forms.ModelForm):
    manager = forms.ModelChoiceField(
        queryset=User.objects.all(), required=False, label="Yönetici"
    )

    class Meta:
        model = UserProfile
        fields = ["department", "manager"]

    def __init__(self, *args, **kwargs):
        user = kwargs.get("instance").user if kwargs.get("instance") else None
        super().__init__(*args, **kwargs)
        if user:
            self.fields["manager"].queryset = User.objects.exclude(pk=user.pk)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_name", "email", "phone", "address", "tax_number"]


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "sku", "description", "unit_of_measure", "reorder_level"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "location", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}
