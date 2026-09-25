from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("banco", views.banco, name="banco"),
    path("canal", views.canal, name="canal"),
    path("api/catalogo", views.api_catalogo),
    path("api/roteiro", views.api_roteiro),
    path("api/gerar", views.api_gerar),
    path("api/jobs/<str:job_id>", views.api_job),
    path("api/canal", views.api_canal),
    path("api/canal/acao", views.api_canal_acao),
    path("api/voz/previa", views.api_voz_previa),
]
