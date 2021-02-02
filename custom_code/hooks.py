import requests
import logging
from astropy.time import Time, TimezoneInfo
from astropy.coordinates import SkyCoord
from tom_dataproducts.models import DataProduct, ReducedDatum
import json
import os
from django.core.files import File
import matplotlib
matplotlib.use('Agg')  # this must be set before importing FLEET
from FLEET.data import main_assess
from FLEET.imported import generate_lightcurve
import numpy as np
import threading

from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.automap import automap_base
from contextlib import contextmanager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def run_fleet(target):
    output_filename = f'{target.name}_FLEET.svg'
    t_assess = main_assess(target.name, target.ra, target.dec, output_filename=output_filename,
                           catalog_filename='', lightcurve_filename='', ztf_filename='', image_filename='')
    if os.path.exists(output_filename):
        logger.info(f'FLEET pipeline finished for {target}.')
        dp, created = DataProduct.objects.get_or_create(
            target=target,
            data_product_type='image_file',
            product_id=f'{target.name}_FLEET'
        )
        if created:
            dp.data = File(open(output_filename, 'rb'))
            os.remove(output_filename)
            logger.info(f'{output_filename} saved')
        else:
            os.replace(output_filename, dp.data.path)
            logger.info(f'{output_filename} replaced')
        dp.save()

        extras = {
            'crowdiness': t_assess['crowdiness'][0],
            'deltamag_closest': t_assess['deltamag'][0],
            'deltamag_best': t_assess['deltamag'][1],
            'deltamag_second': t_assess['deltamag'][2],
            'separation_closest': t_assess['separation'][0],
            'separation_best': t_assess['separation'][1],
            'separation_second': t_assess['separation'][2],
        }
        target.save(extras=extras)
    else:
        logger.warning(f'FLEET pipeline failed. Is {target} in PS1 3π?')


def fleet_lightcurve(target):
    lc, tns_name, ztf_name, redshift, snclass, discoverer = generate_lightcurve(target.name, target.ra, target.dec,
                                                                                output_filename='', ztf_filename='')
    names = []
    if tns_name != '--' and tns_name not in target.names and tns_name.replace('AT', 'SN') not in target.names:
        names.append(tns_name)
    if ztf_name != '--' and ztf_name not in target.names:
        names.append(ztf_name)
    extras = {}
    if not np.isnan(redshift) and not target.extra_fields.get('redshift'):
        extras['redshift'] = redshift
    if snclass != '--' and not target.extra_fields.get('classification'):
        extras['classification'] = snclass
    target.save(names=names, extras=extras)

    for datum in lc:
        time = Time(datum['MJD'], format='mjd')
        value = {
            'magnitude': datum['Mag'],
            'error': datum['MagErr'],
            'telescope': datum['Telescope'],
            'filter': datum['Filter'],
            'upperlimit': datum['UL']
        }
        rd, created = ReducedDatum.objects.get_or_create(
            target=target,
            data_type='photometry',
            timestamp=time.datetime,
            value=json.dumps(value),
            source_name=datum['Source']
        )
        rd.save()


@contextmanager
def _get_session(db_address):
    Base = automap_base()
    engine = create_engine(db_address, poolclass=pool.NullPool)
    Base.metadata.bind = engine

    db_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = db_session()

    try:
        yield session
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def _load_table(tablename, db_address):
    Base = automap_base()
    engine = create_engine(db_address, poolclass=pool.NullPool)
    Base.prepare(engine, reflect=True)

    table = getattr(Base.classes, tablename)
    return(table)
 

def target_post_save(target, created):
  def get(objectId):
    url = 'https://mars.lco.global/'
    request = {'queries':
      [
        {'objectId': objectId}
      ]
      }
  
    try:
      r = requests.post(url, json=request)
      results = r.json()['results'][0]['results']
      return results
    
    except Exception as e:
      return [None,'Error message : \n'+str(e)]
 
  logger.info('Target post save hook: %s created: %s', target, created)

  ztf_name = next((name for name in target.names if 'ZTF' in name), None)
  if ztf_name:
    alerts = get(ztf_name)

  #if 'ZTF' in target.name:
  #  objectId = target.name 
  #  alerts = get(objectId)
    
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


def target_post_save(target, created):
    logger.info('Target post save hook: %s created: %s', target, created)

    coords = SkyCoord(target.ra, target.dec, unit='deg')
    target.galactic_lng = coords.galactic.l.deg
    target.galactic_lat = coords.galactic.b.deg
    target.save_base()

    if created:
        fleet_lightcurve(target)
        fleet_thread = threading.Thread(target=run_fleet, args=[target])
        fleet_thread.start()
