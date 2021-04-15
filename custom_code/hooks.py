import logging
from astropy.time import Time
from astropy.coordinates import SkyCoord
from tom_dataproducts.models import DataProduct, ReducedDatum
from custom_code.models import ReducedDatumExtra
import os
import shutil
from django.core.files import File
import matplotlib
matplotlib.use('Agg')  # this must be set before importing FLEET
from FLEET.classify import predict_SLSN
from FLEET.transient import get_transient_info, generate_lightcurve, ignore_data
from spikepipe.spikepipe import load_catalog, PS1_CATALOG_PATH, preprocess_lco_image, extract_photometry
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
            'telescope': datum['Telescope'],
            'filter': datum['Filter'],
            'upperlimit': datum['UL']
        }
        if np.isfinite(datum['MagErr']):  # do not let NaN in the database
            value['error'] = datum['MagErr']
        rd, created = ReducedDatum.objects.get_or_create(
            target=target,
            data_type='photometry',
            timestamp=time.datetime,
            value=value,
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


def multiple_data_products_post_save(dps):
    logger.info(f'Running post save hook for multiple DataProducts: {dps}')

    for dp in dps:
        if dp.data.path.endswith('-e91.fits.fz'):
            logger.info(f'Starting spikepipe on {dp}')
            spikey_thread = threading.Thread(target=run_spikepipe, args=[dp])
            spikey_thread.start()
        elif dp.data.path.endswith('.tar'):
            logger.info(f'Saving extracted spectrum from {dp}')
            # TODO: unpack the tar file and save the extracted spectrum
        else:
            logger.info(f'{dp} has no post save hook')


def run_spikepipe(data_product):
    target_coords = SkyCoord(data_product.target.ra, data_product.target.dec, unit='deg')
    catalog, catalog_coords, target = load_catalog(PS1_CATALOG_PATH, target_coords)
    ccddata = preprocess_lco_image(data_product.data.path, catalog_coords)
    catalog['catalog_mag'] = catalog[ccddata.meta['FILTER'][0] + 'MeanPSFMag']
    datum = extract_photometry(ccddata, catalog, catalog_coords, target)

    time = Time(datum['MJD'], format='mjd')
    value = {
        'magnitude': datum['mag'],
        'error': datum['dmag'],
        'telescope': 'Las Cumbres',
        'filter': datum['filter'][0],
    }
    rd, created = ReducedDatum.objects.get_or_create(
        target=data_product.target,
        data_product=data_product,
        data_type='photometry',
        timestamp=time.datetime,
        value=value,
        source_name='spikepipe'
    )
    rd.save()

    rdextra_value = {
        'data_product_id': data_product.id,
        'photometry_type': 'Aperture',
        'zp': datum['zp'],
        'dzp': datum['dzp'],
        'instrument': datum['telescope'],
    }
    reduced_datum_extra = ReducedDatumExtra(
        target=data_product.target,
        data_type='photometry',
        key='upload_extras',
        value=rdextra_value
    )
    reduced_datum_extra.save()
