from django.urls import path

from custom_code.views import TargetListView, PaperCreateView, RunFleetView

app_name = 'custom_code'

urlpatterns = [
    path('targets/', TargetListView.as_view(), name='targets'),
    path('create-paper/', PaperCreateView.as_view(), name='create-paper'),
    path('run-fleet/<int:pk>/', RunFleetView.as_view(), name='run-fleet'),
]
