from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/catalogo", views.api_catalogo),
    path("api/roteiro", views.api_roteiro),
    path("api/gerar", views.api_gerar),
    path("api/jobs/<str:job_id>", views.api_job),
]
