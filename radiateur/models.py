"""Database models for the radiator application."""

from __future__ import annotations

from django.db import models


class RadiatorDevice(models.Model):
    """Additional ESP8266 device declared from the web interface."""

    name = models.CharField(
        max_length=64,
        unique=True,
        help_text="Nom utilisé pour communiquer avec le radiateur via MQTT.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Adresse IP locale de l'appareil lorsque connue.",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover - helper for admin/debug
        return self.name
