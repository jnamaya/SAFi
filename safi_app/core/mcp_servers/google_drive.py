import os
import json
import logging
from flask import session, current_app
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
from ...persistence.database import get_oauth_token, upsert_oauth_token

logger = logging.getLogger("google_drive_mcp")

def get_creds():
    user_id = session.get('user_id')
    if not user_id:
        raise Exception("User not logged in.")
        
    token_data = get_oauth_token(user_id, 'google')
    if not token_data:
        raise Exception("Google Drive not connected. Please connect in Settings.")
        
    creds = Credentials(
        token=token_data['access_token'],
        refresh_token=token_data['refresh_token'],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=current_app.config['GOOGLE_CLIENT_ID'],
        client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
        scopes=token_data.get('scope', '').split()
    )
    return creds

async def list_files(query: str = None) -> str:
    try:
        creds = get_creds()
        service = build('drive', 'v3', credentials=creds)
        
        # Default query for files
        q = "trashed = false"
        if query:
            # Check if query is already an OData filter string
            if any(substring in query for substring in ["contains", "=", " and ", " or "]):
                 q += f" and ({query})"
            else:
                 # Assume simple fuzzy search on name
                 q += f" and name contains '{query}'"
            
        results = service.files().list(
            q=q,
            pageSize=10, 
            fields="nextPageToken, files(id, name, mimeType, webViewLink)"
        ).execute()
        
        items = results.get('files', [])
        return json.dumps(items)
    except Exception as e:
        logger.error(f"Drive List Error: {e}")
        return json.dumps({"error": str(e)})

async def read_file(file_id: str) -> str:
    try:
        creds = get_creds()
        service = build('drive', 'v3', credentials=creds)
        
        # Get metadata to check type
        file_meta = service.files().get(fileId=file_id).execute()
        mime_type = file_meta.get('mimeType')
        
        if "google-apps" in mime_type:
            # Export Google Docs/Sheets to plain text/PDF/CSV
            if "document" in mime_type:
                request = service.files().export_media(fileId=file_id, mimeType='text/plain')
            elif "spreadsheet" in mime_type:
                request = service.files().export_media(fileId=file_id, mimeType='text/csv')
            else:
                return json.dumps({"error": f"Export not supported for {mime_type}"})
        else:
            # Download binary/text file
            request = service.files().get_media(fileId=file_id)
            
        fh = io.BytesIO()
        downloader = request  # Simplified, usually MediaIoBaseDownload
        # For small files, execute() returns content on export_media?
        # Check library usage. export_media returns an httpRequest.
        
        content = request.execute()
        # content is bytes
        try:
            return content.decode('utf-8')
        except:
             return f"[Binary Content: {len(content)} bytes]"

    except Exception as e:
        logger.error(f"Drive Read Error: {e}")
        return json.dumps({"error": str(e)})

async def upload_file(name: str, content: str) -> str:
    try:
        creds = get_creds()
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': name}
        media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype='text/plain')
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return json.dumps({"id": file.get('id'), "status": "uploaded"})
    except Exception as e:
        logger.error(f"Drive Upload Error: {e}")
        return json.dumps({"error": str(e)})
