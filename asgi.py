from asgiref.wsgi import WsgiToAsgi
from wsgi import app as flask_app  # Imports your existing 'app' from wsgi.py

# This wraps the WSGI Flask app to make it speak ASGI
app = WsgiToAsgi(flask_app)