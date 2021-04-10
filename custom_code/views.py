from django_filters.views import FilterView
from django.shortcuts import redirect, render
from django.db.models import Q #
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.views.generic.edit import FormView, UpdateView
from django.urls import reverse

from tom_targets.views import TargetListView, TargetDetailView
from custom_code.models import ScienceTags, TargetTags, ReducedDatumExtra, Papers
from custom_code.filters import CustomTargetFilter
from tom_targets.models import TargetList

from tom_targets.models import Target, TargetExtra
from guardian.mixins import PermissionListMixin
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.conf import settings

from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.time import Time
from datetime import datetime
from datetime import timedelta
import json

from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.automap import automap_base
from contextlib import contextmanager
from plotly import offline
import plotly.graph_objs as go
from tom_dataproducts.models import ReducedDatum
from django.utils.safestring import mark_safe
from custom_code.templatetags.custom_code_tags import get_24hr_airmass, airmass_collapse, lightcurve_collapse, spectra_collapse

from .forms import CustomTargetCreateForm, CustomDataProductUploadForm, PapersForm
from tom_targets.views import TargetCreateView
from tom_common.hooks import run_hook
from tom_dataproducts.views import DataProductUploadView, DataProductDeleteView
from tom_dataproducts.models import DataProduct
from tom_dataproducts.exceptions import InvalidFileFormatException
from custom_code.processors.data_processor import run_custom_data_processor
from custom_code.hooks import run_fleet
import threading
from guardian.shortcuts import assign_perm

# Create your views here.

def make_coords(ra, dec):
    coords = SkyCoord(ra, dec, unit=u.deg)
    coords = coords.to_string('hmsdms',sep=':',precision=1,alwayssign=True)
    return coords

def make_lnd(mag, filt, jd, jd_now):
    if not jd:
        return 'Archival'
    diff = jd_now - jd
    lnd = '{mag:.2f} ({filt}: {time:.2f})'.format(
        mag = mag,
        filt = filt,
        time = diff)
    return lnd

def make_magrecent(all_phot, jd_now):
    recent_jd = max([all_phot[obs]['jd'] for obs in all_phot])
    recent_phot = [all_phot[obs] for obs in all_phot if
        all_phot[obs]['jd'] == recent_jd][0]
    mag = float(recent_phot['flux'])
    filt = recent_phot['filters']['name']
    diff = jd_now - float(recent_jd)
    mag_recent = '{mag:.2f} ({filt}: {time:.2f})'.format(
        mag = mag,
        filt = filt,
        time = diff)
    return mag_recent


class TargetListView(PermissionListMixin, FilterView):
    """
    View for listing targets in the TOM. Only shows targets that the user is authorized to view.     Requires authorization.
    """
    template_name = 'custom_code/target_list.html'
    paginate_by = 25
    strict = False
    model = Target
    filterset_class = CustomTargetFilter
    permission_required = 'tom_targets.view_target'
    ordering = ['-id']

    def get_context_data(self, *args, **kwargs):
        """
        Adds the number of targets visible, the available ``TargetList`` objects if the user is a    uthenticated, and
        the query string to the context object.

        :returns: context dictionary
        :rtype: dict
        """
        context = super().get_context_data(*args, **kwargs)
        context['target_count'] = context['paginator'].count
        # hide target grouping list if user not logged in
        context['groupings'] = (TargetList.objects.all()
                                if self.request.user.is_authenticated
                                else TargetList.objects.none())
        context['query_string'] = self.request.META['QUERY_STRING']
        return context

def target_redirect_view(request):
    
    search_entry = request.GET['name']
    
    target_search_coords = None
    for i in [',', ' ']:
        if i in search_entry:
            target_search_coords = search_entry.split(i)
            break 

    if target_search_coords is not None:
        ra = target_search_coords[0]
        dec = target_search_coords[1]
        radius = 1

        if ':' in ra and ':' in dec:
            ra_hms = ra.split(':')
            ra_hour = float(ra_hms[0])
            ra_min = float(ra_hms[1])
            ra_sec = float(ra_hms[2])

            dec_dms = dec.split(':')
            dec_deg = float(dec_dms[0])
            dec_min = float(dec_dms[1])
            dec_sec = float(dec_dms[2])

            # Convert to degree
            ra = (ra_hour*15) + (ra_min*15/60) + (ra_sec*15/3600)
            if dec_deg > 0:
                dec = dec_deg + (dec_min/60) + (dec_sec/3600)
            else:
                dec = dec_deg - (dec_min/60) - (dec_sec/3600)

        else:
            ra = float(ra)
            dec = float(dec)

        target_match_list = Target.objects.filter(ra__gte=ra-1, ra__lte=ra+1, dec__gte=dec-1, dec__lte=dec+1)

        if len(target_match_list) == 1:
            target_id = target_match_list[0].id
            return(redirect('/targets/{}/'.format(target_id)))
        
        else:
            return(redirect('/targets/?cone_search={ra}%2C{dec}%2C1'.format(ra=ra,dec=dec)))

    else:
        target_match_list = Target.objects.filter(Q(name__icontains=search_entry) | Q(aliases__name__icontains=search_entry)).distinct()

        if len(target_match_list) == 1:
            target_id = target_match_list[0].id
            return(redirect('/targets/{}/'.format(target_id)))

        else: 
            return(redirect('/targets/?name={}'.format(search_entry)))


def add_tag_view(request):
    new_tag = request.GET.get('new_tag', None)
    username = request.user.username
    tag, _ = ScienceTags.objects.get_or_create(tag=new_tag, userid=username)
    response_data = {'success': 1}
    return HttpResponse(json.dumps(response_data), content_type='application/json')


def save_target_tag_view(request):
    tag_names = json.loads(request.GET.get('tags', None))
    target_id = request.GET.get('targetid', None)
    TargetTags.objects.all().filter(target_id=target_id).delete()
    for i in range(len(tag_names)):
        tag_id = ScienceTags.objects.filter(tag=tag_names[i]).first().id
        target_tag, _ = TargetTags.objects.get_or_create(tag_id=tag_id, target_id=target_id)
    response_data = {'success': 1}
    return HttpResponse(json.dumps(response_data), content_type='application/json')


def targetlist_collapse_view(request):

    target_id = request.GET.get('target_id', None)
    target = Target.objects.get(id=target_id)
    user_id = request.GET.get('user_id', None)
    user = User.objects.get(id=user_id)

    lightcurve_plot = lightcurve_collapse(target, user)['plot']
    spectra_plot = spectra_collapse(target)['plot']
    airmass_plot = airmass_collapse(target)['figure']

    context = {
        'lightcurve_plot': lightcurve_plot,
        'spectra_plot': spectra_plot,
        'airmass_plot': airmass_plot
    }

    return HttpResponse(json.dumps(context), content_type='application/json')

class CustomTargetCreateView(TargetCreateView):

    def get_form_class(self):
        return CustomTargetCreateForm

    def get_context_data(self, **kwargs):
        context = super(CustomTargetCreateView, self).get_context_data(**kwargs)
        context['type_choices'] = Target.TARGET_TYPES
        return context

    def form_valid(self, form):
        self.object = form.save(commit=True)
        #logger.info('Target post save hook: %s created: %s', self.object, True)
        run_hook('target_post_save', target=self.object, created=True)
        return redirect(self.get_success_url())


class CustomDataProductUploadView(DataProductUploadView):

    form_class = CustomDataProductUploadForm

    def form_valid(self, form):

        target = form.cleaned_data['target']
        if not target:
            observation_record = form.cleaned_data['observation_record']
            target = observation_record.target
        else:
            observation_record = None
        dp_type = form.cleaned_data['data_product_type']
        data_product_files = self.request.FILES.getlist('files')
        successful_uploads = []
        for f in data_product_files:
            dp = DataProduct(
                target=target,
                observation_record=observation_record,
                data=f,
                product_id=None,
                data_product_type=dp_type
            )
            dp.save()
            try:
                #run_hook('data_product_post_upload', dp)

                ### ------------------------------------------------------------------
                ### Create row in ReducedDatumExtras with the extra info
                rdextra_value = {'data_product_id': int(dp.id)}
                if dp_type == 'photometry':
                    extras = {'reduction_type': 'manual'}
                    rdextra_value['photometry_type'] = form.cleaned_data['photometry_type']
                    background_subtracted = form.cleaned_data['background_subtracted']
                    if background_subtracted:
                        extras['background_subtracted'] = True
                        extras['subtraction_algorithm'] = form.cleaned_data['subtraction_algorithm']
                        extras['template_source'] = form.cleaned_data['template_source']

                elif dp_type == 'spectroscopy':
                    extras = {}
                
                rdextra_value['instrument'] = form.cleaned_data['instrument']
                reducer_group = form.cleaned_data['reducer_group']
                if reducer_group != 'LCO':
                    rdextra_value['reducer_group'] = reducer_group

                used_in = form.cleaned_data['used_in']
                if used_in:
                    rdextra_value['used_in'] = str(used_in)
                rdextra_value['final_reduction'] = form.cleaned_data['final_reduction']

                reduced_data = run_custom_data_processor(dp, extras)
                
                reduced_datum_extra = ReducedDatumExtra(
                    target = target,
                    data_type = dp_type,
                    key = 'upload_extras',
                    value = rdextra_value
                )
                reduced_datum_extra.save()

                ### -------------------------------------------------------------------
                
                if not settings.TARGET_PERMISSIONS_ONLY:
                    for group in form.cleaned_data['groups']:
                        assign_perm('tom_dataproducts.view_dataproduct', group, dp)
                        assign_perm('tom_dataproducts.delete_dataproduct', group, dp)
                        assign_perm('tom_dataproducts.view_reduceddatum', group, reduced_data)
                successful_uploads.append(str(dp))
            except InvalidFileFormatException as iffe:
                ReducedDatum.objects.filter(data_product=dp).delete()
                dp.delete()
                ReducedDatumExtra.objects.filter(target=target, value=rdextra_value).delete()
                messages.error(
                    self.request,
                    'File format invalid for file {0} -- error was {1}'.format(str(dp), iffe)
                )
            except Exception as e:
                ReducedDatum.objects.filter(data_product=dp).delete()
                dp.delete()
                ReducedDatumExtra.objects.filter(target=target, value=rdextra_value).delete()
                messages.error(self.request, 'There was a problem processing your file: {0}'.format(str(dp)))
                print(e)
        if successful_uploads:
            messages.success(
                self.request,
                'Successfully uploaded: {0}'.format('\n'.join([p for p in successful_uploads]))
            )

        return redirect(form.cleaned_data.get('referrer', '/'))


class CustomDataProductDeleteView(DataProductDeleteView):

    def delete(self, request, *args, **kwargs):
        ReducedDatum.objects.filter(data_product=self.get_object()).delete()
        # Delete the ReducedDatumExtra row
        reduced_datum_query = ReducedDatumExtra.objects.filter(data_type='photometry', key='upload_extras')
        for row in reduced_datum_query:
            value = row.value
            if value.get('data_product_id', '') == int(self.get_object().id):
                row.delete()
                break
        self.get_object().data.delete()
        return super().delete(request, *args, **kwargs)


def save_dataproduct_groups_view(request):
    group_names = json.loads(request.GET.get('groups', None))
    dataproduct_id = request.GET.get('dataproductid', None)
    dp = DataProduct.objects.get(id=dataproduct_id)
    data = ReducedDatum.objects.filter(data_product=dp)
    successful_groups = ''
    for i in group_names:
        group = Group.objects.get(name=i)
        assign_perm('tom_dataproducts.view_dataproduct', group, dp)
        for datum in data:
            assign_perm('tom_dataproducts.view_reduceddatum', group, datum)
        successful_groups += i
    response_data = {'success': successful_groups}
    return HttpResponse(json.dumps(response_data), content_type='application/json')


class PaperCreateView(FormView):
    
    form_class = PapersForm
    template_name = 'custom_code/papers_list.html'

    def form_valid(self, form):
        target = form.cleaned_data['target']
        first_name = form.cleaned_data['author_first_name']
        last_name = form.cleaned_data['author_last_name']
        status = form.cleaned_data['status']
        description = form.cleaned_data['description']
        paper = Papers(
                target=target,
                author_first_name=first_name,
                author_last_name=last_name,
                status=status,
                description=description
            )
        paper.save()
        
        return HttpResponseRedirect('/targets/{}/'.format(target.id))


class RunFleetView(TargetDetailView):
    def get(self, request, *args, **kwargs):
        target = Target.objects.get(id=kwargs.get('pk', None))
        fleet_thread = threading.Thread(target=run_fleet, args=[target])
        fleet_thread.start()
        return HttpResponseRedirect('/targets/{}/'.format(target.id))
