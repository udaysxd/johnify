import os
import base64
from email.mime.text import MIMEText
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
# Load both repo root .env and backend/.env without overriding existing env
try:
    this_file = Path(__file__).resolve()
    repo_root_env = this_file.parents[3] / '.env'  # C:\johnify\.env
    backend_env = this_file.parents[2] / '.env'    # C:\johnify\backend\.env
    if repo_root_env.exists():
        load_dotenv(dotenv_path=repo_root_env, override=False)
        print(f"[gmail] Loaded .env from {repo_root_env}")
    if backend_env.exists():
        load_dotenv(dotenv_path=backend_env, override=False)
        print(f"[gmail] Loaded .env from {backend_env}")
except Exception:
    pass

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GmailEmailSender:
    """
    Sends emails using Gmail API via OAuth2.

    Required env vars (in any environment where you want sending enabled):
    - GMAIL_CLIENT_ID
    - GMAIL_CLIENT_SECRET
    - GMAIL_REFRESH_TOKEN
    - GMAIL_SENDER (the Gmail address)

    Behavior:
    - If all credentials are present, email sending is enabled.
    - If any credential is missing, email sending is disabled (no-op) and will log a skip message.
    """

    def __init__(self):
        # Read all credentials; enable only if all are present
        self.client_id = os.getenv("GMAIL_CLIENT_ID")
        self.client_secret = os.getenv("GMAIL_CLIENT_SECRET")
        self.refresh_token = os.getenv("GMAIL_REFRESH_TOKEN")
        self.sender = os.getenv("GMAIL_SENDER")
        self._enabled = all([self.client_id, self.client_secret, self.refresh_token, self.sender])
        try:
            # Debug which variables are present to help diagnose config issues
            present = {k: bool(v) for k, v in {
                "GMAIL_CLIENT_ID": self.client_id,
                "GMAIL_CLIENT_SECRET": self.client_secret,
                "GMAIL_REFRESH_TOKEN": self.refresh_token,
                "GMAIL_SENDER": self.sender,
            }.items()}
            missing = [k for k, ok in present.items() if not ok]
            print(f"[gmail] Init: enabled={self._enabled}, present={present}, missing={missing}")
        except Exception:
            pass

    def _build_service(self):
        if not self._enabled:
            raise RuntimeError("GmailEmailSender is disabled (credentials missing)")
        creds = Credentials(
            None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        # Refresh to obtain access token
        if not creds.valid:
            try:
                from google.auth.transport.requests import Request
                request = Request()
                creds.refresh(request)
            except Exception as e:
                raise RuntimeError(f"Failed to refresh Gmail credentials: {e}")
        service = build("gmail", "v1", credentials=creds)
        return service

    def send_email(self, to_email: str, subject: str, body_text: str, body_html: Optional[str] = None, reply_to: Optional[str] = None) -> bool:
        """
        Send an email with optional HTML content.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body_text: Plain text email body
            body_html: Optional HTML email body (if not provided, text will be used)
            reply_to: Optional reply-to email address
            
        Returns:
            bool: True if email was sent or skipped, raises exception on error
        """
        # No-op if credentials are not configured
        if not self._enabled:
            try:
                print("[gmail] Skipping email send: credentials not configured (set GMAIL_* env vars to enable)")
                present = {k: bool(v) for k, v in {
                    "GMAIL_CLIENT_ID": self.client_id,
                    "GMAIL_CLIENT_SECRET": self.client_secret,
                    "GMAIL_REFRESH_TOKEN": self.refresh_token,
                    "GMAIL_SENDER": self.sender,
                }.items()}
                missing = [k for k, ok in present.items() if not ok]
                print(f"[gmail] Skipping email send: present={present}, missing={missing}")
            except Exception:
                pass
            return True
            
        try:
            print(f"[gmail] Sending: from={self.sender}, to={to_email}, subject={subject}")
            service = self._build_service()
            
            # Create message container
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.sender
            msg['To'] = to_email
            if reply_to:
                msg['Reply-To'] = reply_to
                
            # Attach both plain text and HTML versions
            part1 = MIMEText(body_text, 'plain')
            msg.attach(part1)
            
            if body_html:
                part2 = MIMEText(body_html, 'html')
                msg.attach(part2)
            
            # Encode and send
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return True
            
        except Exception as e:
            print(f"[gmail] Error sending email: {str(e)}")
            raise RuntimeError(f"Failed to send email: {str(e)}")
    
    # Backward compatibility
    def send_text_email(self, to_email: str, subject: str, body_text: str, reply_to: Optional[str] = None) -> bool:
        return self.send_email(to_email, subject, body_text, None, reply_to)
