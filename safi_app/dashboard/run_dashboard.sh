#!/bin/bash

# 1. Activate the Python virtual environment
source /var/www/safi/venv/bin/activate

# 2. Set the project's root directory as an environment variable
#    The Python script will use this to find the 'logs' folder.
export SAFI_PROJECT_ROOT="/var/www/safi"
export FLASK_ENV="production"
export FLASK_SECRET_KEY="69928764834209457830418816255427"

echo "============================================="
echo "SAFi Dashboard Runner"
echo "Project Root set to: $SAFI_PROJECT_ROOT"
echo "Starting Streamlit on port 8501..."
echo "============================================="

# 3. Run the Streamlit dashboard with your specific settings
#    Using an absolute path to the script is robust.
streamlit run /var/www/safi/safi_app/dashboard/safi_dashboard.py \
  --server.port 8501 \
  --server.headless true \
  --server.fileWatcherType none \
  --global.developmentMode false