"""Un-initialized Flask extension objects, created here so that blueprints
(routes) and create_app can both import them without an import cycle. Nothing
in this module may import the app or any blueprint.
"""
from authlib.integrations.flask_client import OAuth
from flask_cors import CORS

oauth = OAuth()
cors = CORS()