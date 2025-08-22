import os
from safi_app import create_app

app = create_app()

if __name__ == '__main__':
    # Note: For production, use a WSGI server like Gunicorn instead of app.run()
    # Example: gunicorn --workers 3 --bind 0.0.0.0:5001 "safi_app:create_app()"
    app.run(host='0.0.0.0', port=5001, debug=True)
