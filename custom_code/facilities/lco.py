from django.conf import settings
from django import forms
from crispy_forms.layout import Layout, Div, HTML, Column, Row, ButtonHolder, Submit
from crispy_forms.bootstrap import PrependedText, AppendedText
from astropy import units as u
import datetime

from tom_observations.facilities.lco import LCOPhotometricSequenceForm, LCOSpectroscopicSequenceForm, LCOFacility, make_request
from tom_observations.widgets import FilterField
from django.contrib.auth.models import Group

# Determine settings for this module.
try:
    LCO_SETTINGS = settings.FACILITIES['LCO']
except (AttributeError, KeyError):
    LCO_SETTINGS = {
        'portal_url': 'https://observe.lco.global',
        'api_key': '',
    }

# Module specific settings.
PORTAL_URL = LCO_SETTINGS['portal_url']
TERMINAL_OBSERVING_STATES = ['COMPLETED', 'CANCELED', 'WINDOW_EXPIRED']

# Units of flux and wavelength for converting to Specutils Spectrum1D objects
FLUX_CONSTANT = (1e-15 * u.erg) / (u.cm ** 2 * u.second * u.angstrom)
WAVELENGTH_UNITS = u.angstrom


class SnexPhotometricSequenceForm(LCOPhotometricSequenceForm):
    filters = ['U', 'B', 'V', 'R', 'I', 'up', 'gp', 'rp', 'ip', 'zs', 'w']
    max_airmass = forms.FloatField(initial=1.6, min_value=0, label='Max Airmass')
    min_lunar_distance = forms.IntegerField(min_value=0, label='Minimum Lunar Distance', initial=20, required=False)
    cadence_frequency = forms.FloatField(required=True, min_value=0.0, initial=3.0, label='')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Remove labels from several filter fields
        for filter_name in self.filters:
            self.fields[filter_name] = FilterField(label='', required=False)

        # Do not give choices for proposals
        self.fields['proposal'] = forms.CharField()

        # Massage cadence form to be SNEx-styled
        self.fields['name'].label = ''
        self.fields['name'].widget.attrs['placeholder'] = 'Name'
        self.fields['cadence_strategy'] = forms.ChoiceField(
            choices=[('', 'Once in the next'), ('ResumeCadenceAfterFailureStrategy', 'Repeating every')],
            required=False,
            label=''
        )

        self.fields['instrument_type'] = forms.ChoiceField(choices=self.instrument_choices(),
                                                           initial=('1M0-SCICAM-SINISTRO', '1.0 meter Sinistro'))

        self.helper.layout = Layout(
            Div(
                Column('name'),
                Column('cadence_strategy'),
                Column(AppendedText('cadence_frequency', 'Days')),
                css_class='form-row'
            ),
            Layout('facility', 'target_id', 'observation_type'),
            self.layout(),
            self.button_layout()
        )

    def clean(self):
        """
        Sets "end" to correspond to 1-day window for cadenced requests, cadence_frequency for one-time requests
        """
        #TODO: look into implementing a "delay start by" option like in SNEx
        cleaned_data = super().clean()
        start = datetime.datetime.fromisoformat(cleaned_data['start'])
        window = datetime.timedelta(days=1. if cleaned_data['cadence_strategy'] else cleaned_data['cadence_frequency'])
        cleaned_data['end'] = (start + window).isoformat()
        return cleaned_data

    def layout(self):
        if settings.TARGET_PERMISSIONS_ONLY:
            groups = Div()
        else:
            groups = Row('groups')

        # Add filters to layout
        filter_layout = Layout(
            Row(
                Column(HTML('Exposure Time')),
                Column(HTML('No. of Exposures')),
                Column(HTML('Block No.')),
            )
        )
        for filter_name in self.filters:
            filter_layout.append(Row(PrependedText(filter_name, filter_name)))
        return Div(
            Div(
                filter_layout,
                css_class='col-md-6'
            ),
            Div(
                Row('max_airmass'),
                Row(
                    PrependedText('min_lunar_distance', '>')
                ),
                Row('instrument_type'),
                Row('proposal'),
                Row('observation_mode'),
                Row('ipp_value'),
                groups,
                css_class='col-md-6'
            ),
            css_class='form-row'
        )

    def button_layout(self):
        target_id = self.initial.get('target_id')
        return ButtonHolder(
                Submit('submit', 'Submit', css_id='phot-submit')
                #HTML(f'''<a class="btn btn-outline-primary" href={{% url 'tom_targets:detail' {target_id} %}}>
                #         Back</a>''')
            )


class SnexSpectroscopicSequenceForm(LCOSpectroscopicSequenceForm):
    exposure_count = forms.IntegerField(min_value=1, required=False, initial=1, widget=forms.HiddenInput())
    cadence_frequency = forms.FloatField(required=True, min_value=0.0, initial=3.0, widget=forms.NumberInput(attrs={'placeholder': 'Days'}), label='')
    max_airmass = forms.FloatField(initial=1.6, min_value=0, label='Max Airmass')
    acquisition_radius = forms.FloatField(min_value=0, required=False, initial=5.0)
    guider_exposure_time = forms.FloatField(min_value=0, initial=10.0)
    name = forms.CharField()
    min_lunar_distance = forms.IntegerField(min_value=0, label='Minimum Lunar Distance', initial=20, required=False)
    exposure_time = forms.IntegerField(min_value=1,
                                       widget=forms.TextInput(attrs={'placeholder': 'Seconds'}),
                                       initial=1800)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['proposal'] = forms.CharField()

        self.fields['filter'].label = 'Slit'

        self.helper.layout = Layout(
            Div(
                Column('name'),
                Column('cadence_strategy'),
                Column(AppendedText('cadence_frequency', 'Days')),
                css_class='form-row'
            ),
            Layout('facility', 'target_id', 'observation_type'),
            self.layout(),
            self.button_layout()
        )

    def layout(self):
        if settings.TARGET_PERMISSIONS_ONLY:
            groups = Div()
        else:
            groups = Row('groups')

        return Row(
            Div(
                Row('exposure_time'),
                Row('filter'),
                Row('acquisition_radius'),
                Row('guider_mode'),
                Row('guider_exposure_time'),
                css_class='col-md-6'
            ),
            Div(
                Row('max_airmass'),
                Row(
                    PrependedText('min_lunar_distance', '>')
                ),
                Row('site'),
                Row('proposal'),
                Row('observation_mode'),
                Row('ipp_value'),
                groups,
                css_class='col-md-6'
            ),
            css_class='form-row'
        )

    def clean(self):
        """
        This clean method does the following:
            - Hardcodes filter as "slit_2.0as" because it's the only slit this form uses
            - Sets "end" to correspond to 1-day window for cadenced requests, cadence_frequency for one-time requests
        """
        cleaned_data = super().clean()
        self.cleaned_data['filter'] = 'slit_2.0as'
        start = datetime.datetime.fromisoformat(cleaned_data['start'])
        window = datetime.timedelta(days=1. if cleaned_data['cadence_strategy'] else cleaned_data['cadence_frequency'])
        cleaned_data['end'] = (start + window).isoformat()
        return cleaned_data


class SnexLCOFacility(LCOFacility):
    name = 'LCO'
    observation_types = [('IMAGING', 'Imaging'),
                         ('SPECTRA', 'Spectra')]
    observation_forms = {
        'IMAGING': SnexPhotometricSequenceForm,
        'SPECTRA': SnexSpectroscopicSequenceForm
    }

    def submit_observation(self, observation_payload):
        response = make_request(
            'POST',
            #PORTAL_URL + '/api/requestgroups/validate/',
            PORTAL_URL + '/api/requestgroups/',
            json=observation_payload,
            headers=self._portal_headers()
        )
        print('Made request')
        return [r['id'] for r in response.json()['requests']]

    def validate_observation(self, observation_payload):
        response = make_request(
            'POST',
            PORTAL_URL + '/api/requestgroups/validate/',
            json=observation_payload,
            headers=self._portal_headers()
        )
        print('Validating observation')
        return response.json()['errors']

    def get_date_obs(self, header):
        return self.get_date_obs_from_fits_header(header)
