from tom_targets.forms import SiderealTargetCreateForm, TargetForm
from tom_targets.models import TargetExtra
from tom_dataproducts.forms import DataProductUploadForm
from tom_dataproducts.models import DataProduct
from guardian.shortcuts import assign_perm, get_groups_with_perms, remove_perm
from django import forms
from custom_code.models import ScienceTags, TargetTags, Papers, ReducedDatumExtra
from django.conf import settings
from django.db.models.functions import Lower
from django.core.exceptions import ValidationError
from django.contrib.auth.models import Group

class CustomTargetCreateForm(SiderealTargetCreateForm):

    sciencetags = forms.ModelMultipleChoiceField(ScienceTags.objects.all().order_by(Lower('tag')), widget=forms.CheckboxSelectMultiple, label='Science Tags')

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            for field in settings.EXTRA_FIELDS:
                if self.cleaned_data.get(field['name']) is not None:
                    TargetExtra.objects.update_or_create(
                            target=instance,
                            key=field['name'],
                            defaults={'value': self.cleaned_data[field['name']]}
                    )
            # Save groups for this target
            for group in self.cleaned_data['groups']:
                assign_perm('tom_targets.view_target', group, instance)
                assign_perm('tom_targets.change_target', group, instance)
                assign_perm('tom_targets.delete_target', group, instance)
            for group in get_groups_with_perms(instance):
                if group not in self.cleaned_data['groups']:
                    remove_perm('tom_targets.view_target', group, instance)
                    remove_perm('tom_targets.change_target', group, instance)
                    remove_perm('tom_targets.delete_target', group, instance)

            # Save science tags for this target
            for tag in self.cleaned_data['sciencetags']:
                TargetTags.objects.update_or_create(
                        target=instance,
                        tag=tag
                )

        return instance


def choices_from_reduced_datum_extras(key):
    """Return choices for a dropdown menu based on a certain keyword in the ReducedDatumExtra table"""
    values = {rde.value[key] for rde in ReducedDatumExtra.objects.all() if key in rde.value}
    return [(r, r) for r in sorted(values)]


class SelectOrOtherWidget(forms.widgets.MultiWidget):
    choices = ()

    def __init__(self, attrs=None):
        widget = (
            forms.widgets.Select(choices=self.choices),
            forms.widgets.TextInput(attrs={'placeholder': 'or add another...'})
        )
        super().__init__(widget, attrs=attrs)

    def decompress(self, value):
        if value:
            if value in [x[0] for x in self.choices]:
                return [value, ""]
            else:
                return ["", value]
        else:
            return ["", ""]


class MultiField(forms.MultiValueField):

    def __init__(self, required=False, widget=None, label=None, initial=None, help_text=None, choices=None):
        widget.choices = [('', '')] + choices
        field = (forms.ChoiceField(required=False), forms.CharField(required=False))
        super(MultiField, self).__init__(required=required, fields=field, widget=widget, label=label, initial=initial, help_text=help_text)

    def compress(self, data_list):
        if not data_list:
            raise ValidationError('Select choice or enter text for this field')
        return data_list[0] or data_list[1]


class CustomDataProductUploadForm(DataProductUploadForm):
    photometry_type = forms.ChoiceField(
        choices=[('Aperture', 'Aperture'), 
                 ('PSF', 'PSF'),
                 ('Mixed', 'Mixed')
        ],
        widget=forms.RadioSelect(),
        required=False
    )

    instrument = MultiField(
        choices=choices_from_reduced_datum_extras('instrument'),
        widget=SelectOrOtherWidget,
    )

    background_subtracted = forms.BooleanField(
        required=False
    )

    subtraction_algorithm = forms.ChoiceField(
        choices=[('Hotpants', 'Hotpants'),
                 ('PyZOGY', 'PyZOGY')
        ],
        widget=forms.RadioSelect(),
        required=False
    )

    #template_source = MultiField(
    template_source = forms.ChoiceField(
        choices=[('LCO', 'LCO'),
                 ('SDSS', 'SDSS'),
        ],
        #widget=SelectOrOtherWidget,
        widget=forms.RadioSelect(),
        required=False
    )

    reducer_group = MultiField(
        choices=choices_from_reduced_datum_extras('reducer_group'),
        widget=SelectOrOtherWidget
    )

    used_in = forms.ModelChoiceField(
        queryset=Papers.objects.all(),
        required=False
    )

    final_reduction = forms.BooleanField(
        required=False
    )

    def __init__(self, *args, **kwargs):
        super(CustomDataProductUploadForm, self).__init__(*args, **kwargs)
        initial_args = kwargs.get('initial', '')
        if initial_args:
            target = initial_args.get('target', '')
            self.fields['used_in'] = forms.ModelChoiceField(queryset=Papers.objects.filter(target=target))


class PapersForm(forms.ModelForm):

    class Meta:
        model = Papers
        fields = ['target', 'author_first_name', 'author_last_name', 'status', 'description']
        labels = {
            'author_first_name': '',
            'author_last_name': '',
            'status': '',
            'description': ''
        }
        help_texts = {
            'author_first_name': '',
            'author_last_name': '',
            'status': '',
            'description': ''
        }
        widgets = {
            'target': forms.HiddenInput(),
            'author_first_name': forms.Textarea(
                attrs={
                    'placeholder': 'First name of first author',
                    'rows': 1,
                    'cols': 20
                }
            ),
            'author_last_name': forms.Textarea(
                attrs={
                    'placeholder': 'Last name of first author',
                    'rows': 1,
                    'cols': 20
                }
            ),
            'description': forms.Textarea(
                attrs={
                    'placeholder': 'Brief description of contents of this paper, i.e. "All photometry and spectra"',
                    'rows': 5,
                    'cols': 20
                }
            )
        }
