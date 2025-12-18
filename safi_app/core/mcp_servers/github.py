"""
GitHub MCP Server
Exposes GitHub data tools using PyGithub.
"""
import os
import json
import logging
from typing import Dict, Any, Optional
from ...persistence import database as db

# Try importing, fallback gracefully if not installed
try:
    from github import Github, GithubException
except ImportError:
    Github = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("github_mcp")

def _get_client(user_id: Optional[str] = None):
    token = None
    
    # Priority 1: User-specific OAuth Token
    if user_id:
        try:
            # DEBUG
            logger.info(f"DEBUG: Fetching token for {user_id}")
            oauth_record = db.get_oauth_token(user_id, 'github')
            logger.info(f"DEBUG: DB Record found? {bool(oauth_record)}")
            
            if oauth_record and oauth_record.get('access_token'):
                token = oauth_record['access_token']
                logger.info("DEBUG: Using OAuth token.")
        except Exception as e:
            logger.error(f"DEBUG: Failed to fetch token: {e}", exc_info=True)
            pass # Fallback
            
    # Priority 2: System Environment Variable
    if not token:
        token = os.getenv("GITHUB_TOKEN")
        if token: logger.info("DEBUG: Using System Env Token")

    if not token:
        logger.error("DEBUG: No token found from DB or Env.")
        return None
        
    if not Github:
        logger.error("DEBUG: PyGithub not installed.")
        return None
        
    return Github(token)

async def search_repositories(query: str, user_id: Optional[str] = None) -> str:
    """
    Searches for repositories matching the query.
    """
    logger.info(f"GitHub MCP: Searching repos for query '{query}' (User: {user_id})")
    g = _get_client(user_id)
    if not g:
        return json.dumps({"error": "GitHub client not initialized. Connect your account."})
    
    try:
        repos = g.search_repositories(query=query, sort="stars", order="desc")
        
        # Check total count if possible to avoid iteration if empty
        if repos.totalCount == 0:
            return json.dumps([])
            
        results = []
        # Safe iteration instead of slicing PaginatedList
        for i, repo in enumerate(repos):
            if i >= 5: break
            results.append({
                "full_name": repo.full_name,
                "description": repo.description,
                "stars": repo.stargazers_count,
                "url": repo.html_url
            })
        return json.dumps(results)
    except Exception as e:
        logger.error(f"GitHub Search Error: {e}", exc_info=True)
        return json.dumps({"error": str(e)})

async def get_repository_details(repo_name: str, user_id: Optional[str] = None) -> str:
    """
    Gets details (readme, basic stats) for a specific repo (e.g. 'owner/repo').
    """
    logger.info(f"GitHub MCP: Getting details for '{repo_name}' (User: {user_id})")
    g = _get_client(user_id)
    if not g:
        return json.dumps({"error": "GitHub client not initialized. Connect your account."})

    try:
        repo = g.get_repo(repo_name)
        
        # Try to get README
        readme_content = "No README found."
        try:
             readme = repo.get_readme()
             readme_content = readme.decoded_content.decode("utf-8")[:1000] + "... (truncated)"
        except: pass

        data = {
            "name": repo.full_name,
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "language": repo.language,
            "open_issues": repo.open_issues_count,
            "readme_snippet": readme_content
        }
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

async def list_issues(repo_name: str, user_id: Optional[str] = None) -> str:
    """
    Lists distinct open issues for a repo.
    """
    logger.info(f"GitHub MCP: Listing issues for '{repo_name}' (User: {user_id})")
    g = _get_client(user_id)
    if not g:
        return json.dumps({"error": "GitHub client not initialized. Connect your account."})

    try:
        repo = g.get_repo(repo_name)
        issues = repo.get_issues(state='open')
        results = []
        for issue in issues[:5]:
             results.append({
                 "number": issue.number,
                 "title": issue.title,
                 "url": issue.html_url,
                 "created_at": str(issue.created_at)
             })
        return json.dumps(results)
    except Exception as e:
        return json.dumps({"error": str(e)})

async def read_file_content(repo_name: str, file_path: str, user_id: Optional[str] = None) -> str:
    """
    Reads the content of a specific file in a repository.
    """
    logger.info(f"GitHub MCP: Reading file '{file_path}' in '{repo_name}' (User: {user_id})")
    g = _get_client(user_id)
    if not g:
        return json.dumps({"error": "GitHub client not initialized. Connect your account."})

    try:
        repo = g.get_repo(repo_name)
        file_content = repo.get_contents(file_path)
        
        # Ensure it's a file, not a directory
        if isinstance(file_content, list):
            return json.dumps({"error": "Path points to a directory, not a file."})
            
        decoded = file_content.decoded_content.decode("utf-8")
        # Limit size to avoid context overflow (e.g. 20KB)
        if len(decoded) > 20000:
            decoded = decoded[:20000] + "\n... (File truncated due to size)"
            
        return json.dumps({"path": file_path, "content": decoded})
    except Exception as e:
        return json.dumps({"error": str(e)})
