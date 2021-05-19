from datetime import datetime, timedelta
from dateutil.parser import parse
import logging

from tom_observations.cadences import resume_cadence_after_failure

logger = logging.getLogger(__name__)


class ResumeCadenceAfterFailureStrategy(resume_cadence_after_failure.ResumeCadenceAfterFailureStrategy):
    """Same as built-in ResumeCadenceAfterFailureStrategy, but where cadence_frequency has units of days (not hours)"""

    def advance_window(self, observation_payload, start_keyword='start', end_keyword='end'):
        cadence_frequency = self.dynamic_cadence.cadence_parameters.get('cadence_frequency')
        if not cadence_frequency:
            raise Exception(f'The {self.name} strategy requires a cadence_frequency cadence_parameter.')
        window_length = parse(observation_payload[end_keyword]) - parse(observation_payload[start_keyword])

        new_start = parse(observation_payload[start_keyword]) + timedelta(days=cadence_frequency)
        if new_start < datetime.now():  # Ensure that the new window isn't in the past
            new_start = datetime.now()
        new_end = new_start + window_length
        observation_payload[start_keyword] = new_start.isoformat()
        observation_payload[end_keyword] = new_end.isoformat()

        return observation_payload
