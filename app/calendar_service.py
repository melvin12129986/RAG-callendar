import os
import re
import json
import datetime
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def ensure_iso_tz(dt_str: Optional[str], default_hour_offset: int = 0) -> str:
    """Ensures an ISO datetime string has a valid timezone offset (+HH:MM or Z) for Google Calendar."""
    if not dt_str:
        now_dt = datetime.datetime.now().astimezone() + datetime.timedelta(hours=default_hour_offset)
        return now_dt.isoformat()
    dt_str = str(dt_str).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", dt_str):
        time_part = "23:59:59" if default_hour_offset > 0 else "00:00:00"
        dt_str = f"{dt_str}T{time_part}"
    if re.search(r"(Z|[+-]\d{2}:?\d{2})$", dt_str):
        m = re.search(r"([+-])(\d{2})(\d{2})$", dt_str)
        if m:
            dt_str = dt_str[:m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
        return dt_str
    local_offset = datetime.datetime.now().astimezone().strftime("%z")
    if local_offset:
        formatted_offset = f"{local_offset[:3]}:{local_offset[3:]}"
        return f"{dt_str}{formatted_offset}"
    return f"{dt_str}+00:00"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events"
]

class CalendarService:
    """
    Service wrapper for Google Calendar API.
    Supports real Google Calendar OAuth2 authentication,
    with an intelligent in-memory fallback store seeded with realistic events
    so the application works out-of-the-box before Google OAuth credentials are added.
    """
    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.is_connected_to_google = False
        self.user_email = ""
        
        # Local fallback/in-memory storage
        self._mock_events: Dict[str, Dict[str, Any]] = {}
        self._init_mock_events()
        self._try_init_google_service()

    def _init_mock_events(self):
        """Seed realistic calendar events spanning today and upcoming weeks."""
        now = datetime.datetime.now()
        
        sample_events = [
            {
                "id": "evt-101",
                "summary": "AI & RAG Architecture Review",
                "description": "Discuss BERT embedding forward pass, vector indexing, and Groq AI reasoning.",
                "location": "Room 402 / Google Meet",
                "start": {"dateTime": (now + datetime.timedelta(days=1, hours=2)).isoformat()},
                "end": {"dateTime": (now + datetime.timedelta(days=1, hours=3)).isoformat()},
                "status": "confirmed",
                "priority": "high"
            },
            {
                "id": "evt-102",
                "summary": "Weekly Engineering Sprint Planning",
                "description": "Plan tasks for next week: model deployment, latency optimization, and QA.",
                "location": "Engineering Discord / Meet",
                "start": {"dateTime": (now + datetime.timedelta(days=3, hours=1)).isoformat()},
                "end": {"dateTime": (now + datetime.timedelta(days=3, hours=2)).isoformat()},
                "status": "confirmed",
                "priority": "high"
            },
            {
                "id": "evt-103",
                "summary": "Dentist Appointment",
                "description": "Routine dental checkup and teeth cleaning.",
                "location": "Downtown Dental Clinic",
                "start": {"dateTime": (now + datetime.timedelta(days=5, hours=4)).isoformat()},
                "end": {"dateTime": (now + datetime.timedelta(days=5, hours=5)).isoformat()},
                "status": "confirmed",
                "priority": "medium"
            },
            {
                "id": "evt-104",
                "summary": "Project Demo with Stakeholders",
                "description": "Demonstrate the Google Calendar intelligent assistant with Groq AI reasoning.",
                "location": "Auditorium / Zoom",
                "start": {"dateTime": (now + datetime.timedelta(days=8, hours=2)).isoformat()},
                "end": {"dateTime": (now + datetime.timedelta(days=8, hours=3)).isoformat()},
                "status": "confirmed",
                "priority": "high"
            },
            {
                "id": "evt-105",
                "summary": "Team Lunch & Casual Catchup",
                "description": "Social gathering with team members at the Italian restaurant.",
                "location": "Trattoria Bella",
                "start": {"dateTime": (now + datetime.timedelta(days=10, hours=3)).isoformat()},
                "end": {"dateTime": (now + datetime.timedelta(days=10, hours=4, minutes=30)).isoformat()},
                "status": "confirmed",
                "priority": "low"
            }
        ]
        
        for ev in sample_events:
            self._mock_events[ev["id"]] = ev

    def _try_init_google_service(self) -> bool:
        """Attempts to load existing token or initialize Google Calendar client."""
        if not os.path.exists(self.token_path) and not os.path.exists(self.credentials_path):
            self.is_connected_to_google = False
            return False

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if os.path.exists(self.token_path):
                try:
                    with open(self.token_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("token"):
                        creds = Credentials(
                            token=data.get("token"),
                            refresh_token=data.get("refresh_token"),
                            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                            client_id=data.get("client_id")
                        )
                except Exception:
                    creds = None
                if not creds:
                    try:
                        creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
                    except Exception as e:
                        logger.warning(f"Could not load authorized user file: {e}")
                        creds = None
                
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    with open(self.token_path, "w", encoding="utf-8") as token_file:
                        token_file.write(creds.to_json())
                except Exception as e:
                    logger.warning(f"Could not refresh token: {e}")
                    creds = None

            if creds and creds.valid:
                try:
                    self.service = build("calendar", "v3", credentials=creds)
                    cal = self.service.calendars().get(calendarId="primary").execute()
                    self.user_email = cal.get("id", "Primary Account")
                    self.is_connected_to_google = True
                    logger.info(f"Connected to Google Calendar API ({self.user_email}).")
                    return True
                except Exception as e:
                    logger.warning(f"Could not verify saved Google Calendar credentials: {e}")
                    self.is_connected_to_google = False
                    self.service = None
                    return False
        except Exception as e:
            logger.warning(f"Google Calendar init: {e}")
            self.is_connected_to_google = False

        return False

    def init_from_token(self, access_token: str, refresh_token: Optional[str] = None) -> bool:
        """
        Initializes Google Calendar API service directly from a user's OAuth access token.
        Uses direct Google Calendar REST API v3 verification.
        """
        import requests
        self._last_auth_error = ""
        self.access_token = access_token
        self.refresh_token = refresh_token

        if not access_token:
            self._last_auth_error = "No access token provided."
            self.is_connected_to_google = False
            return False

        try:
            # Direct verification ping to Google Calendar primary calendar
            r = requests.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
            logger.info(f"Google Calendar primary check HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 200:
                cal_data = r.json()
                self.is_connected_to_google = True
                self.user_email = cal_data.get("id") or "Primary Account"

                # Try to build googleapiclient service for compatibility
                try:
                    from google.oauth2.credentials import Credentials
                    from googleapiclient.discovery import build
                    self.service = build("calendar", "v3", credentials=Credentials(token=access_token))
                except Exception as be:
                    logger.warning(f"Could not build googleapiclient service (using direct REST): {be}")
                    self.service = None

                # Save token.json so session is persisted across server restarts
                token_data = {
                    "token": access_token,
                    "refresh_token": refresh_token,
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": "588474445972-kgi08nnkf2lqm161cfa4d3srurm4k9dh.apps.googleusercontent.com"
                }
                try:
                    with open(self.token_path, "w", encoding="utf-8") as f:
                        json.dump(token_data, f, indent=2)
                except Exception as fe:
                    logger.warning(f"Could not persist token.json: {fe}")

                logger.info(f"Initialized Google Calendar API via OAuth token for {self.user_email}!")
                return True
            else:
                self._last_auth_error = f"HTTP {r.status_code}: {r.text}"
                logger.error(f"Google Calendar verification failed: {self._last_auth_error}")
                self.is_connected_to_google = False
                self.service = None
                return False
        except Exception as e:
            self._last_auth_error = str(e)
            logger.error(f"Failed to init Google Calendar from token: {e}", exc_info=True)
            self.is_connected_to_google = False
            self.service = None
            return False

    def trigger_oauth_flow(self) -> Dict[str, Any]:
        """
        Launches Google OAuth 2.0 flow in a local browser window to authorize calendar access.
        """
        if not os.path.exists(self.credentials_path):
            return {
                "success": False,
                "message": f"No {self.credentials_path} found. Please upload credentials.json first."
            }

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
            
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

            self.service = build("calendar", "v3", credentials=creds)
            self.is_connected_to_google = True
            
            try:
                cal = self.service.calendars().get(calendarId="primary").execute()
                self.user_email = cal.get("id", "Primary Account")
            except Exception:
                self.user_email = "Connected Google Account"

            return {
                "success": True,
                "email": self.user_email,
                "message": f"Successfully connected to Google Calendar for {self.user_email}!"
            }
        except Exception as e:
            logger.error(f"OAuth flow error: {e}")
            return {"success": False, "message": f"OAuth failed: {str(e)}"}

    def disconnect_google(self) -> bool:
        """Removes local token and switches back to local mode."""
        self.is_connected_to_google = False
        self.service = None
        self.user_email = ""
        if os.path.exists(self.token_path):
            try:
                os.remove(self.token_path)
            except Exception:
                pass
        return True

    def list_events(self, max_results: int = 250) -> List[Dict[str, Any]]:
        """Fetches events from Google Calendar API or the in-memory store."""
        if self.is_connected_to_google:
            try:
                # Time range: past 1 year to include all historical, current and future events
                past_window = (datetime.datetime.utcnow() - datetime.timedelta(days=365)).isoformat() + "Z"
                items = []
                if self.service:
                    events_result = self.service.events().list(
                        calendarId="primary",
                        timeMin=past_window,
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime"
                    ).execute()
                    items = events_result.get("items", [])
                elif getattr(self, "access_token", None):
                    import requests
                    r = requests.get(
                        f"https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin={past_window}&maxResults={max_results}&singleEvents=true&orderBy=startTime",
                        headers={"Authorization": f"Bearer {self.access_token}"},
                        timeout=10
                    )
                    if r.status_code == 200:
                        items = r.json().get("items", [])

                for item in items:
                    p = item.get("extendedProperties", {}).get("private", {}).get("priority")
                    if not p:
                        desc = (item.get("description") or "").lower()
                        if "urgent" in desc or "high priority" in desc:
                            p = "high"
                        elif "low priority" in desc or "optional" in desc:
                            p = "low"
                        else:
                            p = "medium"
                    item["priority"] = p
                    st = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
                    et = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date") or st
                    if st:
                        item["start_time"] = st
                        item["date_time"] = st
                    if et:
                        item["end_time"] = et
                return items
            except Exception as e:
                logger.error(f"Error fetching from Google Calendar: {e}")
                events = list(self._mock_events.values())
                for ev in events:
                    if "priority" not in ev:
                        ev["priority"] = "medium"
                return events
        else:
            sorted_events = sorted(
                self._mock_events.values(),
                key=lambda x: x.get("start", {}).get("dateTime", x.get("start", {}).get("date", ""))
            )
            for ev in sorted_events:
                if "priority" not in ev:
                    ev["priority"] = "medium"
            return sorted_events

    def create_event(self, summary: str,
                     date_time: Optional[str] = None,
                     start_time: Optional[str] = None, end_time: Optional[str] = None,
                     description: str = "", location: str = "", priority: Optional[str] = "medium",
                     event_date: Optional[str] = None) -> Dict[str, Any]:
        """Creates a new event on Google Calendar or local store."""
        priority = (priority or "medium").lower()
        if priority not in ("high", "medium", "low"):
            priority = "medium"

        raw_dt = (date_time or start_time or event_date or "").strip()
        if not raw_dt:
            raw_dt = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        is_all_day = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", raw_dt)) or raw_dt.endswith("T00:00:00")

        if is_all_day:
            date_str = raw_dt[:10]
            event_body = {
                "summary": summary,
                "description": description,
                "location": location,
                "date_time": date_str,
                "start": {"date": date_str},
                "end": {"date": date_str},
                "priority": priority,
                "extendedProperties": {
                    "private": {"priority": priority}
                }
            }
        else:
            dt_iso = ensure_iso_tz(raw_dt)
            event_body = {
                "summary": summary,
                "description": description,
                "location": location,
                "date_time": dt_iso,
                "start": {"dateTime": dt_iso},
                "end": {"dateTime": dt_iso},
                "priority": priority,
                "extendedProperties": {
                    "private": {"priority": priority}
                }
            }

        if self.is_connected_to_google:
            try:
                if self.service:
                    created_event = self.service.events().insert(
                        calendarId="primary",
                        body=event_body
                    ).execute()
                    created_event["priority"] = priority
                    return created_event
                elif getattr(self, "access_token", None):
                    import requests
                    r = requests.post(
                        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                        headers={
                            "Authorization": f"Bearer {self.access_token}",
                            "Content-Type": "application/json"
                        },
                        json=event_body,
                        timeout=10
                    )
                    if r.status_code in (200, 201):
                        created = r.json()
                        created["priority"] = priority
                        return created
                    else:
                        raise Exception(f"HTTP {r.status_code}: {r.text}")
            except Exception as e:
                logger.error(f"Failed to create Google Calendar event: {e}")
                raise e
        else:
            new_id = f"evt-{int(datetime.datetime.now().timestamp())}"
            event_body["id"] = new_id
            event_body["status"] = "confirmed"
            self._mock_events[new_id] = event_body
            return event_body

    def update_event(self, event_id: str, summary: Optional[str] = None,
                     date_time: Optional[str] = None,
                     start_time: Optional[str] = None, end_time: Optional[str] = None,
                     description: Optional[str] = None, location: Optional[str] = None,
                     priority: Optional[str] = None) -> Dict[str, Any]:
        """Updates an existing event on Google Calendar or local store."""
        if priority is not None:
            priority = priority.lower()
            if priority not in ("high", "medium", "low"):
                priority = "medium"

        start_date_obj = None
        end_date_obj = None

        raw_dt = (date_time or start_time or "").strip()
        if raw_dt:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_dt) or raw_dt.endswith("T00:00:00"):
                start_date_obj = {"date": raw_dt[:10]}
                end_date_obj = {"date": raw_dt[:10]}
            else:
                iso_val = ensure_iso_tz(raw_dt)
                start_date_obj = {"dateTime": iso_val}
                end_date_obj = {"dateTime": iso_val}
        elif end_time:
            e_clean = end_time.strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", e_clean):
                end_date_obj = {"date": e_clean}
            else:
                end_date_obj = {"dateTime": ensure_iso_tz(e_clean)}

        if self.is_connected_to_google and self.service:
            try:
                event = self.service.events().get(calendarId="primary", eventId=event_id).execute()
                if summary is not None:
                    event["summary"] = summary
                if description is not None:
                    event["description"] = description
                if location is not None:
                    event["location"] = location
                if start_date_obj is not None:
                    event["start"] = start_date_obj
                if end_date_obj is not None:
                    event["end"] = end_date_obj
                if priority is not None:
                    event["priority"] = priority
                    if "extendedProperties" not in event:
                        event["extendedProperties"] = {}
                    if "private" not in event["extendedProperties"]:
                        event["extendedProperties"]["private"] = {}
                    event["extendedProperties"]["private"]["priority"] = priority
                    
                updated_event = self.service.events().update(
                    calendarId="primary",
                    eventId=event_id,
                    body=event
                ).execute()
                updated_event["priority"] = priority or event.get("priority", "medium")
                return updated_event
            except Exception as e:
                logger.error(f"Failed to update Google Calendar event: {e}")
                raise e
        else:
            if event_id not in self._mock_events:
                self._mock_events[event_id] = {
                    "id": event_id,
                    "summary": summary or "Event",
                    "status": "confirmed"
                }
            event = self._mock_events[event_id]
            if summary is not None:
                event["summary"] = summary
            if description is not None:
                event["description"] = description
            if location is not None:
                event["location"] = location
            if start_date_obj is not None:
                event["start"] = start_date_obj
            if end_date_obj is not None:
                event["end"] = end_date_obj
            if priority is not None:
                event["priority"] = priority
            return event

    def delete_event(self, event_id: str) -> bool:
        """Deletes an event from Google Calendar or local store."""
        if self.is_connected_to_google and self.service:
            try:
                self.service.events().delete(calendarId="primary", eventId=event_id).execute()
                return True
            except Exception as e:
                logger.error(f"Failed to delete Google Calendar event: {e}")
                return False
        else:
            if event_id in self._mock_events:
                del self._mock_events[event_id]
                return True
            return False
