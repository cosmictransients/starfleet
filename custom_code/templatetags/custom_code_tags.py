from plotly import offline
import plotly.graph_objs as go
from django import template
from django.utils.safestring import mark_safe
from django.conf import settings
from django.db.models.functions import Lower
from django.shortcuts import reverse
from guardian.shortcuts import get_objects_for_user, get_perms
from django.contrib.auth.models import User, Group

from tom_targets.models import Target, TargetExtra
from tom_targets.forms import TargetVisibilityForm
from tom_observations import utils, facility
from tom_dataproducts.models import DataProduct, ReducedDatum, ObservationRecord
from tom_dataproducts.processors.data_serializers import SpectrumSerializer
from tom_dataproducts.processors.spectroscopy_processor import SpectroscopyProcessor

from astroplan import Observer, FixedTarget, AtNightConstraint, time_grid_from_range, moon_illumination
import datetime
import json
from astropy.time import Time
from astropy import units as u
from astropy.coordinates import get_moon, get_sun, SkyCoord, AltAz
import numpy as np
import time
import re

from custom_code.models import ScienceTags, TargetTags, ReducedDatumExtra, Papers
from custom_code.forms import CustomDataProductUploadForm, PapersForm
from urllib.parse import urlencode
from tom_observations.utils import get_sidereal_visibility
from custom_code.facilities.lco import SnexPhotometricSequenceForm, SnexSpectroscopicSequenceForm
register = template.Library()

@register.inclusion_tag('custom_code/airmass_collapse.html')
def airmass_collapse(target):
    interval = 30 #min
    airmass_limit = 3.0

    obj = Target
    obj.ra = target.ra
    obj.dec = target.dec
    obj.epoch = 2000
    obj.type = 'SIDEREAL' 

    plot_data = get_24hr_airmass(obj, interval, airmass_limit)
    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        yaxis=dict(range=[airmass_limit,1.0],gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        margin=dict(l=20,r=10,b=30,t=40),
        hovermode='closest',
        width=250,
        height=200,
        showlegend=False,
        plot_bgcolor='white'
    )
    visibility_graph = offline.plot(
            go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False, config={'staticPlot': True}, include_plotlyjs='cdn'
    )
    return {
        'target': target,
        'figure': visibility_graph
    }

@register.inclusion_tag('custom_code/airmass.html', takes_context=True)
def airmass_plot(context):
    #request = context['request']
    interval = 15 #min
    airmass_limit = 3.0
    plot_data = get_24hr_airmass(context['object'], interval, airmass_limit)
    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        yaxis=dict(range=[airmass_limit,1.0],gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        margin=dict(l=20,r=10,b=30,t=40),
        hovermode='closest',
        width=600,
        height=300,
        plot_bgcolor='white'
    )
    visibility_graph = offline.plot(
        go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False
    )
    return {
        'target': context['object'],
        'figure': visibility_graph
    }

def get_24hr_airmass(target, interval, airmass_limit):

    plot_data = []
    
    start = Time(datetime.datetime.utcnow())
    end = Time(start.datetime + datetime.timedelta(days=1))
    time_range = time_grid_from_range(
        time_range = [start, end],
        time_resolution = interval*u.minute)
    time_plot = time_range.datetime
    
    fixed_target = FixedTarget(name = target.name, 
        coord = SkyCoord(
            target.ra,
            target.dec,
            unit = 'deg'
        )
    )

    #Hack to speed calculation up by factor of ~3
    sun_coords = get_sun(time_range[int(len(time_range)/2)])
    fixed_sun = FixedTarget(name = 'sun',
        coord = SkyCoord(
            sun_coords.ra,
            sun_coords.dec,
            unit = 'deg'
        )
    )

    #Colors to match SNEx1
    colors = {
        'Siding Spring': '#3366cc',
        'Sutherland': '#dc3912',
        'Teide': '#8c6239',
        'Cerro Tololo': '#ff9900',
        'McDonald': '#109618',
        'Haleakala': '#990099'
    }

    for observing_facility in facility.get_service_classes():

        observing_facility_class = facility.get_service_class(observing_facility)
        sites = observing_facility_class().get_observing_sites()

        for site, site_details in sites.items():

            observer = Observer(
                longitude = site_details.get('longitude')*u.deg,
                latitude = site_details.get('latitude')*u.deg,
                elevation = site_details.get('elevation')*u.m
            )
            
            sun_alt = observer.altaz(time_range, fixed_sun).alt
            obj_airmass = observer.altaz(time_range, fixed_target).secz

            bad_indices = np.argwhere(
                (obj_airmass >= airmass_limit) |
                (obj_airmass <= 1) |
                (sun_alt > -18*u.deg)  #between astro twilights
            )

            obj_airmass = [np.nan if i in bad_indices else float(x)
                for i, x in enumerate(obj_airmass)]

            label = '({facility}) {site}'.format(
                facility = observing_facility, site = site
            )

            plot_data.append(
                go.Scatter(x=time_plot, y=obj_airmass, mode='lines', name=label, marker=dict(color=colors.get(site)))
            )

    return plot_data


def get_color(filter_name):
    filter_translate = {'U': 'U', 'B': 'B', 'V': 'V',
        'g': 'g', 'gp': 'g', 'r': 'r', 'rp': 'r', 'i': 'i', 'ip': 'i',
        'g_ZTF': 'g_ZTF', 'r_ZTF': 'r_ZTF', 'i_ZTF': 'i_ZTF', 'UVW2': 'UVW2', 'UVM2': 'UVM2', 
        'UVW1': 'UVW1'}
    colors = {'U': 'rgb(59,0,113)',
        'B': 'rgb(0,87,255)',
        'V': 'rgb(120,255,0)',
        'g': 'rgb(0,204,255)',
        'r': 'rgb(255,124,0)',
        'i': 'rgb(144,0,43)',
        'g_ZTF': 'rgb(0,204,255)',
        'r_ZTF': 'rgb(255,124,0)',
        'i_ZTF': 'rgb(144,0,43)',
        'UVW2': '#FE0683',
        'UVM2': '#BF01BC',
        'UVW1': '#8B06FF',
        'other': 'rgb(0,0,0)'}
    try: color = colors[filter_translate[filter_name]]
    except: color = colors['other']
    return color


@register.inclusion_tag('custom_code/lightcurve.html', takes_context=True)
def lightcurve(context, target):
         
    photometry_data = {}

    if settings.TARGET_PERMISSIONS_ONLY:
        datums = ReducedDatum.objects.filter(target=target, data_type=settings.DATA_PRODUCT_TYPES['photometry'][0])
    else:
        datums = get_objects_for_user(context['request'].user,
                                      'tom_dataproducts.view_reduceddatum',
                                      klass=ReducedDatum.objects.filter(
                                        target=target,
                                        data_type=settings.DATA_PRODUCT_TYPES['photometry'][0]))

    for rd in datums:
    #for rd in ReducedDatum.objects.filter(target=target, data_type='photometry'):
        value = rd.value
        if not value:  # empty
            continue
   
        photometry_data.setdefault(value.get('filter', ''), {})
        photometry_data[value.get('filter', '')].setdefault('time', []).append(rd.timestamp)
        photometry_data[value.get('filter', '')].setdefault('magnitude', []).append(value.get('magnitude',None))
        photometry_data[value.get('filter', '')].setdefault('error', []).append(value.get('error', None))        

    plot_data = [
        go.Scatter(
            x=filter_values['time'],
            y=filter_values['magnitude'], mode='markers',
            marker=dict(color=get_color(filter_name)),
            name=filter_name,
            error_y=dict(
                type='data',
                array=filter_values['error'],
                visible=True,
                color=get_color(filter_name)
            )
        ) for filter_name, filter_values in photometry_data.items()] 
     

    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        yaxis=dict(autorange='reversed',gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        margin=dict(l=30, r=10, b=100, t=40),
        hovermode='closest',
        plot_bgcolor='white'
        #height=500,
        #width=500
    )
    if plot_data:
      return {
          'target': target,
          'plot': offline.plot(go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False)
      }
    else:
        return {
            'target': target,
            'plot': 'No photometry for this target yet.'
        }


@register.inclusion_tag('custom_code/lightcurve_collapse.html')
def lightcurve_collapse(target, user):
         
    photometry_data = {}
    if settings.TARGET_PERMISSIONS_ONLY:
        datums = ReducedDatum.objects.filter(target=target, data_type=settings.DATA_PRODUCT_TYPES['photometry'][0])
    else:
        datums = get_objects_for_user(user,
                                      'tom_dataproducts.view_reduceddatum',
                                      klass=ReducedDatum.objects.filter(
                                        target=target,
                                        data_type=settings.DATA_PRODUCT_TYPES['photometry'][0]))
    #for rd in ReducedDatum.objects.filter(target=target, data_type='photometry'): 
    for rd in datums:
        value = rd.value
        photometry_data.setdefault(value.get('filter', ''), {})
        photometry_data[value.get('filter', '')].setdefault('time', []).append(rd.timestamp)
        photometry_data[value.get('filter', '')].setdefault('magnitude', []).append(value.get('magnitude',None))
        photometry_data[value.get('filter', '')].setdefault('error', []).append(value.get('error', None))
    plot_data = [
        go.Scatter(
            x=filter_values['time'],
            y=filter_values['magnitude'], mode='markers',
            marker=dict(color=get_color(filter_name)),
            error_y=dict(
                type='data',
                array=filter_values['error'],
                visible=True,
                color=get_color(filter_name)
            )
        ) for filter_name, filter_values in photometry_data.items()]
    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        yaxis=dict(autorange='reversed',gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        margin=dict(l=30, r=10, b=30, t=40),
        hovermode='closest',
        height=200,
        width=250,
        showlegend=False,
        plot_bgcolor='white'
    )
    if plot_data:
        return {
            'target': target,
            'plot': offline.plot(go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False, config={'staticPlot': True}, include_plotlyjs='cdn')
        }
    else:
        return {
            'target': target,
            'plot': 'No photometry for this target yet.'
        }

@register.inclusion_tag('custom_code/moon.html')
def moon_vis(target):

    day_range = 30
    times = Time(
        [str(datetime.datetime.utcnow() + datetime.timedelta(days=delta))
            for delta in np.arange(0, day_range, 0.2)],
        format = 'iso', scale = 'utc'
    )
    
    obj_pos = SkyCoord(target.ra, target.dec, unit=u.deg)
    moon_pos = get_moon(times)

    separations = moon_pos.separation(obj_pos).deg
    phases = moon_illumination(times)

    distance_color = 'rgb(0, 0, 255)'
    phase_color = 'rgb(255, 0, 0)'
    plot_data = [
        go.Scatter(x=times.mjd-times[0].mjd, y=separations, 
            mode='lines',name='Moon distance (degrees)',
            line=dict(color=distance_color)
        ),
        go.Scatter(x=times.mjd-times[0].mjd, y=phases, 
            mode='lines', name='Moon phase', yaxis='y2',
            line=dict(color=phase_color))
    ]
    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3', showline=True, linecolor='#D3D3D3', mirror=True, title='Days from now'),
        yaxis=dict(range=[0.,180.],tick0=0.,dtick=45.,
            tickfont=dict(color=distance_color),
            gridcolor='#D3D3D3', showline=True, linecolor='#D3D3D3', mirror=True
        ),
        yaxis2=dict(range=[0., 1.], tick0=0., dtick=0.25, overlaying='y', side='right',
            tickfont=dict(color=phase_color),
            gridcolor='#D3D3D3', showline=True, linecolor='#D3D3D3', mirror=True),
        margin=dict(l=20,r=10,b=30,t=40),
        width=600,
        height=300,
        plot_bgcolor='white'
    )
    figure = offline.plot(
        go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False
    )
   
    return {'plot': figure}

@register.inclusion_tag('custom_code/spectra.html')
def spectra_plot(target, dataproduct=None):
    spectra = []
    spectral_dataproducts = ReducedDatum.objects.filter(target=target, data_type='spectroscopy').order_by('-timestamp')
    if dataproduct:
        spectral_dataproducts = DataProduct.objects.get(dataproduct=dataproduct)
    for spectrum in spectral_dataproducts:
        datum = SpectrumSerializer().deserialize(spectrum.value)
        wavelength = datum.spectral_axis.to(SpectroscopyProcessor.DEFAULT_WAVELENGTH_UNITS).value
        flux = datum.new_flux_unit(SpectroscopyProcessor.DEFAULT_FLUX_CONSTANT).flux.value
        name = str(spectrum.timestamp).split(' ')[0]
        spectra.append((wavelength, flux, name))
    wavelength_unit = SpectroscopyProcessor.DEFAULT_WAVELENGTH_UNITS.to_string('unicode')
    flux_unit = re.sub('\s*─+\s*', ' / ', SpectroscopyProcessor.DEFAULT_FLUX_CONSTANT.to_string('unicode').strip())
    plot_data = [
        go.Scatter(
            x=spectrum[0],
            y=spectrum[1],
            name=spectrum[2]
        ) for spectrum in spectra]
    layout = go.Layout(
        height=600,
        width=700,
        hovermode='closest',
        xaxis=dict(
            tickformat=".0f",
            title=f'Wavelength ({wavelength_unit})',
            gridcolor='#D3D3D3',
            showline=True,
            linecolor='#D3D3D3',
            mirror=True
        ),
        yaxis=dict(
            tickformat=".1eg",
            title=f'Flux ({flux_unit})',
            gridcolor='#D3D3D3',
            showline=True,
            linecolor='#D3D3D3',
            mirror=True
        ),
        plot_bgcolor='white'
    )
    if plot_data:
      return {
          'target': target,
          'plot': offline.plot(go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False)
      }
    else:
        return {
            'target': target,
            'plot': 'No spectra for this target yet.'
        }

@register.inclusion_tag('custom_code/spectra_collapse.html')
def spectra_collapse(target):
    spectral_dataproducts = ReducedDatum.objects.filter(target=target, data_type='spectroscopy').order_by('-timestamp')
    plot_data = [
        go.Scatter(x=spectrum.value['wavelength'], y=spectrum.value['flux']) for spectrum in spectral_dataproducts
    ]
    layout = go.Layout(
        height=200,
        width=250,
        margin=dict(l=30, r=10, b=30, t=40),
        showlegend=False,
        xaxis=dict(
            gridcolor='#D3D3D3',
            showline=True,
            linecolor='#D3D3D3',
            mirror=True
        ),
        yaxis=dict(
            showticklabels=False,
            gridcolor='#D3D3D3',
            showline=True,
            linecolor='#D3D3D3',
            mirror=True
        ),
        plot_bgcolor='white'
    )
    if plot_data:
        return {
            'target': target,
            'plot': offline.plot(go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False, config={'staticPlot': True}, include_plotlyjs='cdn')
        }
    else:
        return {
            'target': target,
            'plot': 'No spectra for this target yet.'
        }

@register.inclusion_tag('custom_code/aladin_collapse.html')
def aladin_collapse(target):
    return {'target': target}

@register.inclusion_tag('custom_code/fleet.html')
def get_fleet_plot(target):
    data_product = target.dataproduct_set.filter(product_id=target.name+'_FLEET').last()
    return {'fleet_plot': data_product, 'target': target}

@register.filter
def photometry(target):
    return target.reduceddatum_set.filter(data_type='photometry')

@register.filter
def magformat(reduceddatum, digits='1'):
    if reduceddatum and reduceddatum.data_type == 'photometry':
        phot = reduceddatum.value
        magstr = '{{filter}}&nbsp;=&nbsp;{{magnitude:.{digits}f}}'
        return mark_safe(magstr.format(digits=digits).format(**phot))
    else:
        return ''

@register.filter
def magerrformat(reduceddatum, digits='1'):
    if reduceddatum and reduceddatum.data_type == 'photometry':
        phot = reduceddatum.value
        magstr = '{{filter}}&nbsp;=&nbsp;{{magnitude:.{digits}f}}&nbsp;&pm;&nbsp;{{error:.{digits}f}}'
        return mark_safe(magstr.format(digits=digits).format(**phot))
    else:
        return ''

@register.filter
def brightest(phot):
    if phot:
        mags = [point.value['magnitude'] for point in phot]
        return phot[int(np.argmin(mags))]
    else:
        return ''

@register.filter
def unit(value, unit):
    if value:
        return value + unit
    else:
        return ''

@register.filter
def get_targetextra_id(target, keyword):
    try:
        targetextra = TargetExtra.objects.get(target_id=target.id, key=keyword)
        return targetextra.id
    except:
        return json.dumps(None)

@register.inclusion_tag('custom_code/classifications_dropdown.html')
def classifications_dropdown(target):
    classifications = [i for i in settings.TARGET_CLASSIFICATIONS]
    return {'target': target,
            'classifications': classifications}

@register.inclusion_tag('custom_code/science_tags_dropdown.html')
def science_tags_dropdown(target):
    tag_query = ScienceTags.objects.all().order_by(Lower('tag'))
    tags = [i.tag for i in tag_query]
    return{'target': target,
           'sciencetags': tags}

@register.filter
def get_target_tags(target):
    #try:
    target_tag_query = TargetTags.objects.filter(target_id=target.id)
    tags = ''
    for i in target_tag_query:
        tag_name = ScienceTags.objects.filter(id=i.tag_id).first().tag
        tags+=(str(tag_name) + ',')
    return json.dumps(tags)
    #except:
    #    return json.dumps(None)


@register.inclusion_tag('custom_code/custom_upload_dataproduct.html', takes_context=True)
def custom_upload_dataproduct(context, obj):
    user = context['user']
    initial = {}
    choices = {}
    if isinstance(obj, Target):
        initial['target'] = obj
        initial['referrer'] = reverse('tom_targets:detail', args=(obj.id,))
        initial['used_in'] = ('', '')

    elif isinstance(obj, ObservationRecord):
        initial['observation_record'] = obj
        initial['referrer'] = reverse('tom_observations:detail', args=(obj.id,))
        
    form = CustomDataProductUploadForm(initial=initial)
    if not settings.TARGET_PERMISSIONS_ONLY:
        if user.is_superuser:
            form.fields['groups'].queryset = Group.objects.all()
        else:
            form.fields['groups'].queryset = user.groups.all()
    return {'data_product_form': form}


@register.inclusion_tag('custom_code/submit_lco_observations.html')
def submit_lco_observations(target):
    phot_initial = {'target_id': target.id,
                    'facility': 'LCO',
                    'observation_type': 'IMAGING',
                    'name': target.name}
    spec_initial = {'target_id': target.id,
                    'facility': 'LCO',
                    'observation_type': 'SPECTRA',
                    'name': target.name}
    phot_form = SnexPhotometricSequenceForm(initial=phot_initial, auto_id='phot_%s')
    spec_form = SnexSpectroscopicSequenceForm(initial=spec_initial, auto_id='spec_%s')
    phot_form.helper.form_action = reverse('tom_observations:create', kwargs={'facility': 'LCO'})
    spec_form.helper.form_action = reverse('tom_observations:create', kwargs={'facility': 'LCO'})
    if not settings.TARGET_PERMISSIONS_ONLY:
        phot_form.fields['groups'].queryset = Group.objects.all()
        spec_form.fields['groups'].queryset = Group.objects.all()
    return {'object': target,
            'phot_form': phot_form,
            'spec_form': spec_form}

@register.inclusion_tag('custom_code/dash_lightcurve.html', takes_context=True)
def dash_lightcurve(context, target, width, height):
    request = context['request']
    
    # Get initial choices and values for some dash elements
    telescopes = []
    reducer_groups = []
    papers_used_in = []
    final_reduction = False
    background_subtracted = False

    datumquery = ReducedDatum.objects.filter(target=target, data_type='photometry')
    for i in datumquery:
        datum_value = i.value
        if datum_value.get('background_subtracted', '') == True:
            background_subtracted = True
            break

    final_background_subtracted = False
    for de in ReducedDatumExtra.objects.filter(target=target, key='upload_extras', data_type='photometry'):
        de_value = de.value
        inst = de_value.get('instrument', '')
        used_in = de_value.get('used_in', '')
        group = de_value.get('reducer_group', '')

        if inst and inst not in telescopes:
            telescopes.append(inst)
        if used_in and used_in not in papers_used_in:
            papers_used_in.append(used_in)
        if group and group not in reducer_groups:
            reducer_groups.append(group)
   
        if de_value.get('final_reduction', '')==True:
            final_reduction = True
            final_reduction_datumid = de_value.get('data_product_id', '')

            datum = ReducedDatum.objects.filter(target=target, data_type='photometry', data_product_id=final_reduction_datumid)
            datum_value = datum.first().value
            if datum_value.get('background_subtracted', '') == True:
                final_background_subtracted = True
    
    reducer_group_options = []
    reducer_group_options.extend([{'label': k, 'value': k} for k in reducer_groups])
    reducer_groups.append('')
    
    paper_options = [{'label': '', 'value': ''}]
    paper_options.extend([{'label': k, 'value': k} for k in papers_used_in])

    dash_context = {'target_id': {'value': target.id},
                    'plot-width': {'value': width},
                    'plot-height': {'value': height},
                    'telescopes-checklist': {'options': [{'label': k, 'value': k} for k in telescopes]},
                    'reducer-group-checklist': {'options': reducer_group_options,
                                                'value': reducer_groups},
                    'papers-dropdown': {'options': paper_options}
    }

    if final_reduction:
        dash_context['final-reduction-checklist'] = {'value': 'Final'}
        dash_context['reduction-type-radio'] = {'value': 'manual'}

        if final_background_subtracted:
            dash_context['subtracted-radio'] = {'value': 'Subtracted'}
        else:
            dash_context['subtracted-radio'] = {'value': 'Unsubtracted'}
            dash_context['telescopes-checklist']['value'] = telescopes

    elif background_subtracted:
        dash_context['subtracted-radio'] = {'value': 'Subtracted'}

    else:
        dash_context['subtracted-radio'] = {'value': 'Unsubtracted'}


    return {'dash_context': dash_context,
            'request': request}

@register.inclusion_tag('custom_code/dataproduct_update.html')
def dataproduct_update(dataproduct):
    group_query = Group.objects.all()
    groups = [i.name for i in group_query]
    return{'dataproduct': dataproduct,
           'groups': groups}

@register.filter
def get_dataproduct_groups(dataproduct):
    # Query all the groups with permission for this dataproduct
    group_query = Group.objects.all()
    groups = ''
    for i in group_query:
        if 'view_dataproduct' in get_perms(i, dataproduct):
            groups += str(i.name) + ','
    return json.dumps(groups)


@register.inclusion_tag('tom_observations/partials/observation_plan.html')
def custom_observation_plan(target, facility, length=1, interval=30, airmass_limit=3.0):
    """
    Displays form and renders plot for visibility calculation. Using this templatetag to render a plot requires that
    the context of the parent view have values for start_time, end_time, and airmass.
    """

    visibility_graph = ''
    start_time = datetime.datetime.now()
    end_time = start_time + datetime.timedelta(days=length)

    visibility_data = get_sidereal_visibility(target, start_time, end_time, interval, airmass_limit)
    i = 0
    plot_data = []
    for site, data in visibility_data.items():
        plot_data.append(go.Scatter(x=data[0], y=data[1], mode='markers+lines', marker={'symbol': i}, name=site))
        i += 1
    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True,title='Date'),
        yaxis=dict(range=[airmass_limit,1.0],gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True,title='Airmass'),
        #xaxis={'title': 'Date'},
        #yaxis={'autorange': 'reversed', 'title': 'Airmass'},
        plot_bgcolor='white'
    )
    visibility_graph = offline.plot(
        go.Figure(data=plot_data, layout=layout), output_type='div', show_link=False
    )

    return {
        'visibility_graph': visibility_graph
    }


@register.inclusion_tag('custom_code/observation_summary.html', takes_context=True)
def observation_summary(context, target=None):
    """
    A modification of the observation_list templatetag 
    to display a summary of the observation records
    for this object.
    """
    if target:
        if settings.TARGET_PERMISSIONS_ONLY:
            observations = target.observationrecord_set.all()
        else:
            observations = get_objects_for_user(
                                context['request'].user,
                                'tom_observations.view_observationrecord',
                                ).filter(target=target)
    else:
        observations = ObservationRecord.objects.all().order_by('-created')

    parameters = []
    for observation in observations:
        parameter = observation.parameters

        # First do LCO observations
        if parameter.get('facility', '') == 'LCO':

            if parameter.get('cadence_strategy', ''):
                parameter_string = str(parameter.get('cadence_frequency', '')) + '-day ' + str(parameter.get('observation_type', '')).lower() + ' cadence of '
            else:
                parameter_string = 'Single ' + str(parameter.get('observation_type', '')).lower() + ' observation of '

            if parameter.get('observation_type', '') == 'IMAGING':
                filters = ['U', 'B', 'V', 'R', 'I', 'up', 'gp', 'rp', 'ip', 'zs', 'w']
                for f in filters:
                    filter_parameters = parameter.get(f, '')
                    if filter_parameters:
                        if filter_parameters[0] != 0.0:
                            filter_string = f + ' (' + str(filter_parameters[0]) + 'x' + str(filter_parameters[1]) + '), '
                            parameter_string += filter_string 
            
            elif parameter.get('observation_type', '') == 'SPECTRA':
                parameter_string += str(parameter.get('exposure_time', ''))
                parameter_string += 's '


            parameter_string += 'with IPP ' + str(parameter.get('ipp_value', ''))
            parameter_string += ' and airmass < ' + str(parameter.get('max_airmass', ''))
            parameter_string += ' starting on ' + str(observation.created).split(' ')[0]
            if parameter.get('end', ''):
                parameter_string += ' and ending on ' + str(observation.modified).split(' ')[0]

            parameters.append({'title': 'LCO Sequence',
                               'summary': parameter_string,
                               'observation': observation.id})

        # Now do Gemini observations
        elif parameter.get('facility', '') == 'Gemini':
            
            if 'SPECTRA' in parameter.get('observation_type', ''):
                parameter_string = 'Gemini spectrum of B exposure time ' + parameter.get('b_exptime', '') + 's and R exposure time ' + parameter.get('r_exptime', '') + 's with airmass <' + str(parameter.get('max_airmass', '')) + ', scheduled on ' + str(observation.created).split(' ')[0]

            else: # Gemini photometry
                parameter_string = 'Gemini photometry of g (' + parameter.get('g_exptime', '') + 's), r (' + parameter.get('r_exptime', '') + 's), i (' + parameter.get('i_exptime', '') + 's), and z (' + parameter.get('z_exptime', '') + 's), with airmass < ' + str(parameter.get('max_airmass', '')) + ', scheduled on ' + str(observation.created).split(' ')[0]

            parameters.append({'title': 'Gemini Sequence',
                               'summary': parameter_string,
                               'observation': observation.id})

    return {
        'observations': observations,
        'parameters': parameters
    }


@register.inclusion_tag('custom_code/scheduling_list.html', takes_context=True)
def scheduling_list(context, observations):
    parameters = []
    for observation in observations:
        facility = observation.facility
        
        # For now, we'll only worry about scheduling for LCO observations
        if facility != 'LCO':
            continue

        observation_id = observation.id
        target = observation.target
        target_names = observation.target.names

        parameter = observation.parameters
        if parameter.get('observation_type', '') == 'IMAGING':
            observation_type = 'Phot'
        elif 'SPEC' in parameter.get('observation_type', ''):
            observation_type = 'Spec'
        else:
            observation_type = ''

        if parameter.get('cadence_strategy', ''):
            cadence = str(parameter.get('cadence_frequency', '')) + ' days'
        else:
            cadence = 'Onetime'
        ipp = parameter.get('ipp_value', '')
        airmass = parameter.get('max_airmass', '')

        exposures = []
        if observation_type == 'Phot':
            if '1M' in parameter.get('instrument_type', ''):
                instrument = 'Sinistro'
            elif 'SBIG' in parameter.get('instrument_type', ''):
                instrument = 'SBIG'
            else:
                instrument = 'MuSCAT'

            filters = ['U', 'B', 'V', 'R', 'I', 'up', 'gp', 'rp', 'ip', 'zs', 'w']
            for f in filters:
                filter_parameters = parameter.get(f, '')
                if filter_parameters and filter_parameters[0] != 0.0:
                    exposures.append({'filter': f, 'number': filter_parameters[1], 'exp_time': int(filter_parameters[0])})

        elif observation_type == 'Spec':
            instrument = 'Floyds'

            exposures.append({'filter': '',
                               'number': parameter.get('exposure_count', ''), 
                               'exp_time': parameter.get('exposure_time', '')})

        #TODO: Finish this for non-LCO facilities
        else: 
            instrument = 'Gemini'

            exposures.append({'filter': '', 'number': '', 'exp_time': ''})

        start = str(observation.created).split('.')[0]
        if parameter.get('end', ''):
            end = str(observation.modified).split('.')[0]

        parameters.append({'observation_id': observation_id,
                           'target': target,
                           'facility': facility,
                           'observation_type': observation_type,
                           'cadence': cadence,
                           'ipp': ipp,
                           'airmass': airmass,
                           'instrument': instrument,
                           'exposures': exposures,
                           'start': start,
                           'end': end,
                           'user_id': context['request'].user.id
                        })
    return {'observations': observations,
            'parameters': parameters
    }


@register.inclusion_tag('custom_code/papers_list.html')
def papers_list(target):

    paper_query = Papers.objects.filter(target=target)
    papers = []
    for i in range(len(paper_query)):
        papers.append(paper_query[i])

    paper_form = PapersForm(initial={'target': target})
    
    return {'object': target,
            'papers': papers,
            'form': paper_form}
