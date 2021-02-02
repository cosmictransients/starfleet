from django.urls import path

from custom_code.views import TargetListView, PaperCreateView

app_name = 'custom_code'

urlpatterns = [
    path('targets/', TargetListView.as_view(), name='targets'),
    path('create-paper/', PaperCreateView.as_view(), name='create-paper')
]
