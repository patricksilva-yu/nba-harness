#!/usr/bin/env python3
"""Compatibility entrypoint for the local web app."""

from api.app import app, create_app

__all__ = ["app", "create_app"]
