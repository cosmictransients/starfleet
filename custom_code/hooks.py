import requests
import logging
from astropy.time import Time, TimezoneInfo
from astropy.coordinates import SkyCoord
from tom_dataproducts.models import DataProduct, ReducedDatum
import json
import os
import shutil
from django.core.files import File
import matplotlib
matplotlib.use('Agg')  # this must be set before importing FLEET
from FLEET.classify import predict_SLSN
from FLEET.transient import get_transient_info, generate_lightcurve, ignore_data
import numpy as np
import threading

from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.automap import automap_base
from contextlib import contextmanager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def run_fleet(target, import_ZTF=True, import_OSC=True, import_lightcurve=True, reimport_catalog=False):
    if target.dec <= -32.:
        logger.info(f'{target} is too far south for FLEET')
        return
    t_assess = predict_SLSN(target.name, target.ra, target.dec, target.extra_fields.get('redshift', np.nan),
                            import_ZTF=import_ZTF, import_OSC=import_OSC, import_local=False,
                            import_lightcurve=import_lightcurve, reimport_catalog=reimport_catalog,
                            classifier='all', plot_lightcurve=True, do_observability=True)
    output_filename = f'plots/{t_assess["object_name"][0]}_output.pdf'
    if os.path.exists(output_filename):
        logger.info(f'FLEET pipeline finished for {target}.')
        dp, created = DataProduct.objects.get_or_create(
            target=target,
            data_product_type='image_file',
            product_id=f'{target.name}_FLEET'
        )
        if created:
            dp.data = File(open(output_filename, 'rb'), name=os.path.basename(output_filename))
            logger.info(f'{output_filename} saved')
        else:
            shutil.copy2(output_filename, dp.data.path)
            logger.info(f'{output_filename} replaced')
        os.remove(output_filename)
        dp.save()
        target.save(extras=dict(t_assess[0]))
        logger.info(f'FLEET pipeline finished on {target}')
    else:
        logger.warning(f'FLEET pipeline failed on {target}')


def fleet_lightcurve(target):
    _, _, _, object_name, ztf_data, ztf_name, tns_name, snclass, osc_data = get_transient_info(target.name, target.ra,
                                                                                               target.dec)
    output_table = generate_lightcurve(ztf_data, osc_data, object_name, ztf_name, tns_name)
    lc = ignore_data(object_name, output_table)

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
    logger.info('Target post save hook: %s created: %s', target, created)

    coords = SkyCoord(target.ra, target.dec, unit='deg')
    target.galactic_lng = coords.galactic.l.deg
    target.galactic_lat = coords.galactic.b.deg
    target.save_base()

    if created:
        fleet_lightcurve(target)
        fleet_thread = threading.Thread(target=run_fleet, args=[target, False, False, False, False])
        fleet_thread.start()
