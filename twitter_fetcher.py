import os
import json
import base64
import hashlib
import requests
import argparse
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
TOKENS_FILE = "tokens.json"

# Twitter OAuth 2.0 Endpoints
AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"

# PKCE Helpers
def create_verifier():
    return base64.urlsafe_b64encode(os.urandom(30)).decode("utf-8").replace("=", "")

def create_challenge(verifier):
    m = hashlib.sha256()
    m.update(verifier.encode("utf-8"))
    return base64.urlsafe_b64encode(m.digest()).decode("utf-8").replace("=", "")

def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f)

def load_tokens():
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE, "r") as f:
        return json.load(f)

def refresh_tokens(tokens):
    payload = {
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
    }
    # Use Basic Auth if CLIENT_SECRET is provided
    auth = (CLIENT_ID, CLIENT_SECRET) if CLIENT_SECRET else None
    response = requests.post(TOKEN_URL, data=payload, auth=auth)
    
    if response.status_code != 200:
        print(f"Error refreshing token: {response.text}")
        return None
    new_tokens = response.json()
    save_tokens(new_tokens)
    return new_tokens

def get_user_me(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.twitter.com/2/users/me", headers=headers)
    if response.status_code != 200:
        print(f"Error fetching /users/me: {response.text}")
        return None
    return response.json()["data"]["id"]

def get_timeline(user_id, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.twitter.com/2/users/{user_id}/timelines/reverse_chronological"
    params = {
        "tweet.fields": "created_at,author_id,text",
        "max_results": 1
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"Error fetching timeline: {response.text}")
        return None
    return response.json()

def save_csv(data, filename):
    import csv
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["created_at", "author_id", "text"])
        for item in data.get("data", []):
            writer.writerow([item["created_at"], item["author_id"], item["text"]])
        
def run_auth():
    print("--- Starting OAuth 2.0 PKCE Authorization ---")
    code_verifier = create_verifier()
    code_challenge = create_challenge(code_verifier)
    
    scopes = ["tweet.read", "users.read", "offline.access"]
    twitter = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=scopes)
    
    authorization_url, state = twitter.authorization_url(
        AUTH_URL, 
        code_challenge=code_challenge, 
        code_challenge_method="S256"
    )
    
    print(f"\n1. Go to this URL to authorize the app:\n{authorization_url}\n")
    redirect_response = input("2. Paste the full redirect URL here: ")
    
    # Extract code from redirect URL
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(redirect_response)
    code = parse_qs(parsed.query).get("code")
    if not code:
        print("Error: Could not find 'code' in the redirect URL.")
        return

    # Exchange code for token
    payload = {
        "code": code[0],
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier
    }
    
    # Use Basic Auth if CLIENT_SECRET is provided
    auth = (CLIENT_ID, CLIENT_SECRET) if CLIENT_SECRET else None
    response = requests.post(TOKEN_URL, data=payload, auth=auth)
    
    if response.status_code != 200:
        print(f"Error fetching token: {response.text}")
        return
        
    tokens = response.json()
    save_tokens(tokens)
    print("\n--- Tokens saved to tokens.json ---")

def run_cron():
    tokens = load_tokens()
    if not tokens:
        print("Error: tokens.json not found. Run --auth first.")
        return
    
    # Refresh token for newest access
    tokens = refresh_tokens(tokens)
    if not tokens:
        return
        
    access_token = tokens["access_token"]
    user_id = get_user_me(access_token)
    if not user_id: return
    
    print(f"Fetching timeline for User ID: {user_id}")
    timeline = get_timeline(user_id, access_token)
    if timeline and "data" in timeline:
        print("\n--- Recent Tweets ---")
        for tweet in timeline["data"]:
            print(f"[{tweet['created_at']}] {tweet['text']}\n")
    else:
        print("No tweets found or error fetching timeline.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", action="store_true", help="Run initial authentication")
    parser.add_argument("--cron", action="store_true", help="Run cron job fetch")
    args = parser.parse_args()
    
    if not CLIENT_ID or CLIENT_ID == "YOUR_CLIENT_ID_HERE":
        print("Error: Please set your CLIENT_ID in .env first.")
        exit(1)

    if args.auth:
        run_auth()
    elif args.cron:
        run_cron()
    else:
        parser.print_help()
