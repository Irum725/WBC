# -*- coding: utf-8 -*-
"""
WSGI Entry Point for WBC Screen Baseball System
Used by PythonAnywhere, Gunicorn, and other WSGI application servers.
"""
import sys
import os

project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from app import app as application
