"""
Initializes Flask extensions to prevent circular import issues.

This file creates the global, un-initialized extension objects.
- __init__.py imports from here to configure them with the app.
- Blueprints (like auth.py) import from here to use them in routes.
"""
from authlib.integrations.flask_client import OAuth
from flask_cors import CORS

oauth = OAuth()
cors = CORS()