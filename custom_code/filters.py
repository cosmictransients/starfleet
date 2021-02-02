from custom_code.models import ScienceTags, TargetTags
from tom_targets.models import Target, TargetList
from tom_targets.filters import filter_for_field, TargetFilter
from django.conf import settings
import django_filters
from django.db.models.functions import Lower


class CustomTargetFilter(TargetFilter):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in settings.EXTRA_FIELDS:
            new_filter = filter_for_field(field)
            new_filter.parent = self
            self.filters[field['name']] = new_filter
        self.filters['sciencetags'].field.label_from_instance = lambda obj: obj.tag

    key = None
    value = None

    sciencetags = django_filters.ModelChoiceFilter(queryset=ScienceTags.objects.all().order_by(Lower('tag')), label="Science Tag", method='filter_sciencetags')

    def filter_sciencetags(self, queryset, name, value):
        return queryset.filter(targettags__tag=value).distinct()

    class Meta:
        model = Target
        fields = ['name', 'cone_search', 'targetlist__name', 'sciencetags']
