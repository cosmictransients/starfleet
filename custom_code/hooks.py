import requests
import logging
from astropy.time import Time, TimezoneInfo
from tom_dataproducts.models import ReducedDatum
import json

logger = logging.getLogger(__name__)


def query_mars(objectId):
    url = 'https://mars.lco.global/'
    request = {'queries': [{'objectId': objectId}]}

    try:
        r = requests.post(url, json=request)
        results = r.json()['results'][0]['results']
        return results

    except Exception as e:
        return [None, 'Error message : \n' + str(e)]


def save_ztf_photometry(target, alerts):
    filters = {1: 'g_ZTF', 2: 'r_ZTF', 3: 'i_ZTF'}
    for alert in alerts:
        if all([key in alert['candidate'] for key in ['jd', 'magpsf', 'fid', 'sigmapsf']]):
            jd = Time(alert['candidate']['jd'], format='jd', scale='utc')
            jd.to_datetime(timezone=TimezoneInfo())
            value = {
                'magnitude': alert['candidate']['magpsf'],
                'filter': filters[alert['candidate']['fid']],
                'error': alert['candidate']['sigmapsf']
            }
            rd, created = ReducedDatum.objects.get_or_create(
                timestamp=jd.to_datetime(timezone=TimezoneInfo()),
                value=json.dumps(value),
                source_name=target.name,
                source_location=alert['lco_id'],
                data_type='photometry',
                target=target)
            rd.save()


def query_gaia(gaia_name):
    base_url = 'http://gsaweb.ast.cam.ac.uk/alerts/alert'
    lightcurve_url = f'{base_url}/{gaia_name}/lightcurve.csv'

    response = requests.get(lightcurve_url)
    data = response._content.decode('utf-8').split('\n')[2:-2]
    return data, lightcurve_url


def save_gaia_photometry(target, data, lightcurve_url):
    jd = [x.split(',')[1] for x in data]
    mag = [x.split(',')[2] for x in data]

    for i in reversed(range(len(mag))):
        try:
            datum_mag = float(mag[i])
            datum_jd = Time(float(jd[i]), format='jd', scale='utc')
            value = {
                'magnitude': datum_mag,
                'filter': 'G_Gaia',
                'error': 0  # for now
            }
            rd, created = ReducedDatum.objects.get_or_create(
                timestamp=datum_jd.to_datetime(timezone=TimezoneInfo()),
                value=json.dumps(value),
                source_name=target.name,
                source_location=lightcurve_url,
                data_type='photometry',
                target=target)
            rd.save()
        except:
            pass


def target_post_save(target, created):
    logger.info('Target post save hook: %s created: %s', target, created)

    ztf_name = next((name for name in target.names if 'ZTF' in name), None)
    if ztf_name:
        ztf_alerts = query_mars(ztf_name)
        save_ztf_photometry(target, ztf_alerts)

    gaia_name = next((name for name in target.names if 'Gaia' in name), None)
    if gaia_name:
        gaia_data, gaia_url = query_gaia(gaia_name)
        save_gaia_photometry(target, gaia_data, gaia_url)
