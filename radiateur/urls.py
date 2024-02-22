from django.urls import path, include

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("planning/", views.planning, name="planning"),
    path("changement_etat/", views.changement_etat, name="changement_etat"),
    path("retourner_etat/", views.retourner_etat, name="retourner_etat"),
    # path("getjson/", views.getjson, name="datajson"),
    path("maj_json", views.maj_json, name="maj_json"),
    # path("get_image_url/", views.get_image_url, name="get_image_url")
]
