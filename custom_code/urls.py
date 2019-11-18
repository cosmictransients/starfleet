from django.urls import path

from custom_code.views import TNSTargets, MyTargetListView

app_name = 'custom_code'

urlpatterns = [
    path('tnstargets/', TNSTargets.as_view(), name='tns-targets'),
    path('targets/', MyTargetListView.as_view(), name='targets')
]
