from django.db import models
from tom_dataproducts.models import ReducedDatum
from tom_targets.models import Target

# Create your models here.

STATUS_CHOICES = (
    ('in prep', 'In Prep'),
    ('submitted', 'Submitted'),
    ('published', 'Published')
)


class ReducedDatumExtra(models.Model):
    
    target = models.ForeignKey(
        Target, on_delete=models.CASCADE
    )
    data_type = models.CharField(
        max_length=100, default='', verbose_name='Data Type', 
        help_text='Type of data (either photometry or spectroscopy)'
    )
    key = models.CharField(
        max_length=200, default='', verbose_name='Key',
        help_text='Keyword for information being stored'
    )
    value = models.JSONField(
        blank=True, verbose_name='Value',
        help_text='String value of the information being stored'
    )
    float_value = models.FloatField(
        null=True, blank=True, verbose_name='Float Value',
        help_text='Float value of the information being stored, if applicable'
    )
    bool_value = models.BooleanField(
        null=True, blank=True, verbose_name='Boolean Value',
        help_text='Boolean value of the information being stored, if applicable'
    )

    class Meta:
        get_latest_by = ('id,')
        #unique_together = ['reduced_datum', 'key']

    def __str__(self):
        return f'{self.key}: {self.value}'

    def save(self, *args, **kwargs):
        try:
            self.float_value = float(self.value)
        except (TypeError, ValueError, OverflowError):
            self.float_value = None
        try:
            self.bool_value = bool(self.value)
        except (TypeError, ValueError, OverflowError):
            self.bool_value = None

        super().save(*args, **kwargs)


class ScienceTags(models.Model):

    tag = models.TextField(
        verbose_name='Science Tag', help_text='Science Tag', default=''
    )

    userid = models.CharField(
        max_length=100, default='', verbose_name='User ID', 
        help_text='ID of user who created this tag', blank=True, null=True
    )

    class Meta:
        get_latest_by = ('id',)

    def __str__(self):
        return self.tag


class TargetTags(models.Model):

    target = models.ForeignKey(
        Target, on_delete=models.CASCADE
    )

    tag = models.ForeignKey(
        ScienceTags, on_delete=models.CASCADE
    )


class Papers(models.Model):

    target = models.ForeignKey(
        Target, on_delete=models.CASCADE
    )

    author_first_name = models.CharField(
        max_length=20, default='', 
        verbose_name='First Author First Name', help_text='First name of the first author'
    )

    author_last_name = models.CharField(
        max_length=20, default='',
        verbose_name='First Author Last Name', help_text='Last name of the first author'
    )

    description = models.TextField(
        verbose_name='Description', help_text='Brief description of the contents of the paper', 
        default='', null=True
    )

    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES
    )

    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.author_last_name} et al. ({self.status})'

    class Meta:
        get_latest_by = ('id',)
