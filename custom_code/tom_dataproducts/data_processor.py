from tom_dataproducts.data_processor import DataProcessor, DEFAULT_FLUX_CONSTANT
from tom_dataproducts.exceptions import InvalidFileFormatException
from datetime import datetime
from astropy.io import fits, ascii
from astropy.time import Time, TimezoneInfo
from astropy.wcs import WCS
from astropy.units import Unit
from specutils import Spectrum1D
import mimetypes

mimetypes.add_type('text/plain', '.table')


class CustomDataProcessor(DataProcessor):

    def _process_spectrum_from_fits(self, data_product):
        flux, header = fits.getdata(data_product.data.path, header=True)

        try:
            flux_constant = Unit(header['BUNIT'])
            flux_constant.to(DEFAULT_FLUX_CONSTANT)
        except:
            flux_constant = DEFAULT_FLUX_CONSTANT
        date_obs = header.get('DATE-OBS', datetime.now())

        header['CUNIT1'] = 'Angstrom'
        wcs = WCS(header=header)
        flux = flux[0].squeeze() * flux_constant

        spectrum = Spectrum1D(flux=flux, wcs=wcs)

        return spectrum, Time(date_obs).to_datetime()

    def _process_photometry_from_plaintext(self, data_product):
        """
        Processes the photometric data from a plaintext file into a dict, which can then be  stored as a ReducedDatum
        for further processing or display. File is read using astropy as specified in the below documentation. The file
        is expected to be a multi-column delimited file, with headers for time, magnitude, filter, and error.
        # http://docs.astropy.org/en/stable/io/ascii/read.html

        :param data_product: Photometric DataProduct which will be processed into a dict
        :type data_product: DataProduct

        :returns: python dict containing the data from the DataProduct
        :rtype: dict
        """
        photometry = {}

        data = ascii.read(data_product.data.path, format='fixed_width')
        if len(data) < 1:
            raise InvalidFileFormatException('Empty table or invalid file type')

        utc = TimezoneInfo(tzname='UTC')
        for datum in data:
            time = Time(datum['MJD'], format='mjd')
            value = {
                'magnitude': datum['mag'],
                'filter': datum['filt'],
                'error': datum['dmag']
            }
            photometry.setdefault(time.to_datetime(timezone=utc), []).append(value)
        return photometry
