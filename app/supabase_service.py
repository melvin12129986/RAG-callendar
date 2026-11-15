import os
import re
import json
import uuid
import logging
import hashlib
import secrets
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

def ensure_iso_tz(dt_str: Optional[str], default_hour_offset: int = 0) -> str:
    """Ensures an ISO datetime string has a valid timezone offset for Postgres without generating random hours."""
    if not dt_str:
        today = datetime.now().astimezone().date().isoformat()
        return f"{today}T00:00:00+00:00"
    dt_str = str(dt_str).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", dt_str):
        dt_str = f"{dt_str}T00:00:00"
    if re.search(r"(Z|[+-]\d{2}:?\d{2})$", dt_str):
        m = re.search(r"([+-])(\d{2})(\d{2})$", dt_str)
        if m:
            dt_str = dt_str[:m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
        return dt_str
    local_offset = datetime.now().astimezone().strftime("%z")
    if local_offset:
        formatted_offset = f"{local_offset[:3]}:{local_offset[3:]}"
        return f"{dt_str}{formatted_offset}"
    return f"{dt_str}+00:00"

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return salt + ":" + hashed.hex()

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        if not stored_hash or ":" not in stored_hash:
            return False
        salt, hashed = stored_hash.split(":", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return secrets.compare_digest(check.hex(), hashed)
    except Exception:
        return False

class SupabaseService:
    """
    Direct Supabase Database connector supporting multi-user isolation.
    Uses HTTPS REST API with connection pooling and retry logic.
    Supports calendar_events, hashed_vectors, and chat_messages per user_id.
    """
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        load_dotenv(override=True)
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = (key or os.getenv("SUPABASE_KEY", "")).strip()
        
        self.session = requests.Session()
        self.is_connected = False
        self.has_user_id_col = True # will auto-detect on first query
        self.has_date_time_col = True # will auto-detect or fallback on query
        self._init_connection()

    def _get_headers(self) -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def _init_connection(self):
        if not self.url or not self.key:
            self.is_connected = False
            return

        try:
            # Quick health check query
            headers = self._get_headers()
            r = self.session.get(f"{self.url}/rest/v1/calendar_events?select=*&limit=1", headers=headers, timeout=6)
            if r.status_code in (200, 206):
                self.is_connected = True
                logger.info("Successfully connected to Supabase REST API!")
                # Detect if user_id or date_time column is present
                data = r.json()
                if data and isinstance(data, list) and len(data) > 0:
                    self.has_user_id_col = "user_id" in data[0]
                    self.has_date_time_col = "date_time" in data[0]
                self.sync_local_users_to_supabase()
                return
            else:
                logger.warning(f"Supabase REST ping returned status {r.status_code}: {r.text[:120]}")
                self.is_connected = False
        except Exception as e:
            logger.warning(f"Could not connect to Supabase REST: {e}")
            self.is_connected = False

    def configure(self, url: str, key: str) -> bool:
        self.url = url.strip().rstrip("/")
        self.key = key.strip()
        self._init_connection()
        return self.is_connected

    # ==========================================
    # Multi-User Calendar Events Operations
    # ==========================================
    def list_events(self, user_id: Optional[str] = "guest") -> Optional[List[Dict[str, Any]]]:
        if not self.is_connected:
            return None

        headers = self._get_headers()
        try:
            # Query strictly scoped to user_id or all if user_id is None / "all"
            if self.has_user_id_col and user_id and user_id != "all":
                query_url = f"{self.url}/rest/v1/calendar_events?select=*&user_id=eq.{user_id}&order=start_time.asc"
            else:
                query_url = f"{self.url}/rest/v1/calendar_events?select=*&order=start_time.asc"

            r = self.session.get(query_url, headers=headers, timeout=6)
            if r.status_code in (200, 206):
                rows = r.json()
                events = []
                for row in rows:
                    row_uid = row.get("user_id") or "guest"
                    dt = row.get("date_time") or row.get("start_time") or ""
                    st = row.get("start_time") or dt
                    et = row.get("end_time") or dt
                    dt_clean = str(dt).strip()
                    is_date = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", dt_clean)) or dt_clean.endswith("T00:00:00") or dt_clean.endswith("T00:00:00+00:00") or dt_clean.endswith("T00:00:00Z")
                    start_dict = {"date": dt_clean[:10]} if is_date else {"dateTime": dt}
                    end_dict = {"date": dt_clean[:10]} if is_date else {"dateTime": et}
                    events.append({
                        "id": row.get("id"),
                        "summary": row.get("summary", "Untitled"),
                        "description": row.get("description", ""),
                        "location": row.get("location", ""),
                        "priority": row.get("priority", "medium"),
                        "status": row.get("status", "confirmed"),
                        "user_id": row_uid,
                        "date_time": dt,
                        "start_time": st,
                        "end_time": et,
                        "start": start_dict,
                        "end": end_dict,
                        "source": "supabase"
                    })
                return events
            elif r.status_code == 400 and "user_id" in r.text:
                self.has_user_id_col = False
                fallback_url = f"{self.url}/rest/v1/calendar_events?select=*&order=start_time.asc"
                rf = self.session.get(fallback_url, headers=headers, timeout=6)
                if rf.status_code in (200, 206):
                    return rf.json()
            return None
        except Exception as e:
            logger.error(f"Error querying Supabase calendar_events: {e}")
            return None

    def create_event(self, event: Dict[str, Any], user_id: str = "guest") -> Optional[Dict[str, Any]]:
        if not self.is_connected:
            return None

        dt_raw = ""
        if isinstance(event.get("date_time"), str) and event.get("date_time"):
            dt_raw = event.get("date_time")
        elif isinstance(event.get("start"), dict):
            dt_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date") or ""
        elif isinstance(event.get("start"), str):
            dt_raw = event.get("start")
        if not dt_raw:
            dt_raw = event.get("start_time") or event.get("event_date") or ""

        dt_iso = ensure_iso_tz(dt_raw)
        ev_id = event.get("id")
        summary = event.get("summary", "Untitled Event")
        description = event.get("description", "")
        location = event.get("location", "")
        priority = (event.get("priority") or "medium").lower()
        status = event.get("status", "confirmed")

        payload = {
            "id": ev_id,
            "summary": summary,
            "description": description,
            "location": location,
            "priority": priority,
            "start_time": dt_iso,
            "end_time": dt_iso,
            "status": status,
            "source": "app"
        }
        if self.has_date_time_col:
            payload["date_time"] = dt_iso
        if self.has_user_id_col:
            payload["user_id"] = user_id

        headers = self._get_headers()
        # Postgrest upsert using merge-duplicates
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"

        try:
            r = self.session.post(f"{self.url}/rest/v1/calendar_events", headers=headers, json=payload, timeout=6)
            if r.status_code in (200, 201, 204):
                return payload
            elif r.status_code == 400:
                retry = False
                if "date_time" in r.text and "date_time" in payload:
                    self.has_date_time_col = False
                    payload.pop("date_time", None)
                    retry = True
                if "user_id" in r.text and "user_id" in payload:
                    self.has_user_id_col = False
                    payload.pop("user_id", None)
                    retry = True
                if retry:
                    r2 = self.session.post(f"{self.url}/rest/v1/calendar_events", headers=headers, json=payload, timeout=6)
                    if r2.status_code in (200, 201, 204):
                        return payload
            logger.error(f"Supabase create_event failed: {r.status_code} {r.text}")
            return None
        except Exception as e:
            logger.error(f"Supabase create_event error: {e}")
            return None

    def update_event(self, event_id: str, updates: Dict[str, Any], user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.is_connected:
            return None

        payload = {}
        for key in ["summary", "description", "location", "priority", "status"]:
            if key in updates and updates[key] is not None:
                payload[key] = str(updates[key]).lower() if key == "priority" else updates[key]

        raw_dt = updates.get("date_time") or updates.get("start_time")
        if not raw_dt and "start" in updates and isinstance(updates["start"], dict):
            raw_dt = updates["start"].get("dateTime") or updates["start"].get("date")

        if raw_dt:
            dt_iso = ensure_iso_tz(raw_dt)
            if self.has_date_time_col:
                payload["date_time"] = dt_iso
            payload["start_time"] = dt_iso
            payload["end_time"] = dt_iso

        headers = self._get_headers()
        try:
            url = f"{self.url}/rest/v1/calendar_events?id=eq.{event_id}"
            if user_id and self.has_user_id_col:
                url += f"&user_id=eq.{user_id}"

            r = self.session.patch(url, headers=headers, json=payload, timeout=6)
            if r.status_code in (200, 204):
                return updates
            elif r.status_code == 400 and "date_time" in r.text and "date_time" in payload:
                self.has_date_time_col = False
                payload.pop("date_time", None)
                r2 = self.session.patch(url, headers=headers, json=payload, timeout=6)
                if r2.status_code in (200, 204):
                    return updates
            logger.error(f"Supabase update_event error: {r.status_code} {r.text}")
            return None
        except Exception as e:
            logger.error(f"Supabase update_event exception: {e}")
            return None

    def delete_event(self, event_id: str, user_id: Optional[str] = None) -> bool:
        if not self.is_connected:
            return False

        headers = self._get_headers()
        try:
            url = f"{self.url}/rest/v1/calendar_events?id=eq.{event_id}"
            if user_id and self.has_user_id_col:
                url += f"&user_id=eq.{user_id}"

            r = self.session.delete(url, headers=headers, timeout=6)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Supabase delete_event exception: {e}")
            return False

    def sync_events(self, events: List[Dict[str, Any]], user_id: str = "guest") -> int:
        count = 0
        for ev in events:
            if self.create_event(ev, user_id=user_id):
                count += 1
        return count

    # ==========================================
    # Multi-User BERT Hashed Vectors Storage
    # ==========================================
    def save_hashed_record(self, record: Dict[str, Any], user_id: str = "guest") -> bool:
        """Stores BERT 128-dim dense vector and 64-bit SimHash in Supabase."""
        if not self.is_connected:
            return False

        try:
            vector_preview = record.get("vector_preview")
            if vector_preview is None and "vector" in record:
                vector_preview = [round(float(v), 4) for v in record["vector"][:8]]

            payload = {
                "id": record["id"],
                "user_id": user_id,
                "raw_text": record.get("raw_text", ""),
                "dimension": record.get("dimension", 128),
                "semantic_hash": record.get("semantic_hash", ""),
                "vector_preview": vector_preview
            }
            headers = self._get_headers()
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
            r = self.session.post(f"{self.url}/rest/v1/hashed_vectors", headers=headers, json=payload, timeout=6)
            return r.status_code in (200, 201, 204)
        except Exception as e:
            logger.warning(f"Note: hashed_vectors save warning: {e}")
            return False

    def list_hashed_records(self, user_id: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        if not self.is_connected:
            return None
        try:
            url = f"{self.url}/rest/v1/hashed_vectors?select=*"
            if user_id:
                url += f"&user_id=eq.{user_id}"
            headers = self._get_headers()
            r = self.session.get(url, headers=headers, timeout=6)
            if r.status_code in (200, 206):
                return r.json()
            return None
        except Exception as e:
            return None

    def delete_hashed_record(self, record_id: str, user_id: Optional[str] = None) -> bool:
        if not self.is_connected:
            return False
        try:
            url = f"{self.url}/rest/v1/hashed_vectors?id=eq.{record_id}"
            if user_id:
                url += f"&user_id=eq.{user_id}"
            headers = self._get_headers()
            r = self.session.delete(url, headers=headers, timeout=6)
            return r.status_code in (200, 204)
        except Exception as e:
            return False

    # ==========================================
    # Multi-User Chat History Persistence
    # ==========================================
    def _get_local_chat_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        dir_path = os.path.join(os.path.dirname(__file__), "data", "chats")
        file_path = os.path.join(dir_path, f"{user_id}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    msgs = json.load(f)
                    return msgs[-limit:]
            except Exception:
                return []
        return []

    def _save_local_chat_message(self, user_id: str, payload: Dict[str, Any]):
        dir_path = os.path.join(os.path.dirname(__file__), "data", "chats")
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, f"{user_id}.json")
        msgs = self._get_local_chat_history(user_id, 200)
        msgs.append(payload)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(msgs, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save local chat: {e}")

    def save_chat_message(self, user_id: str, sender: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Persists user and AI chat interactions scoped to user_id."""
        msg_id = f"msg-{int(datetime.utcnow().timestamp() * 1000)}-{str(uuid.uuid4())[:8]}"
        payload = {
            "id": msg_id,
            "user_id": user_id,
            "sender": sender,
            "message": message,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat()
        }
        # Always persist locally for immediate fast retrieval
        self._save_local_chat_message(user_id, payload)

        if not self.is_connected:
            return True

        try:
            headers = self._get_headers()
            headers["Prefer"] = "return=representation"
            r = self.session.post(f"{self.url}/rest/v1/chat_messages", headers=headers, json=payload, timeout=6)
            return r.status_code in (200, 201, 204)
        except Exception as e:
            logger.warning(f"Could not persist chat message to Supabase: {e}")
            return False

    def get_chat_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves past conversation turns for this specific user."""
        if self.is_connected:
            try:
                headers = self._get_headers()
                url = f"{self.url}/rest/v1/chat_messages?select=*&user_id=eq.{user_id}&order=created_at.asc&limit={limit}"
                r = self.session.get(url, headers=headers, timeout=6)
                if r.status_code in (200, 206):
                    data = r.json()
                    if data:
                        return data
            except Exception as e:
                logger.warning(f"Could not load chat history from Supabase: {e}")

        # Fallback to local storage
        return self._get_local_chat_history(user_id, limit)

    def clear_chat_history(self, user_id: str) -> bool:
        """Deletes chat messages for this user."""
        # Clear local
        dir_path = os.path.join(os.path.dirname(__file__), "data", "chats")
        file_path = os.path.join(dir_path, f"{user_id}.json")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

        if not self.is_connected:
            return True

        try:
            headers = self._get_headers()
            url = f"{self.url}/rest/v1/chat_messages?user_id=eq.{user_id}"
            r = self.session.delete(url, headers=headers, timeout=6)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Could not clear chat history: {e}")
            return False

    def sign_up_user(self, email: str, password: str, full_name: str = "") -> Dict[str, Any]:
        """
        Creates a new user via Supabase Auth Admin API (with email_confirm=True).
        Then immediately signs them in to return active session token.
        """
        if not self.is_connected or not self.key:
            raise ValueError("Supabase database connection is not active.")

        headers = self._get_headers()
        payload = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": full_name or email.split("@")[0]
            }
        }
        res = self.session.post(f"{self.url}/auth/v1/admin/users", headers=headers, json=payload, timeout=8)
        if res.status_code not in (200, 201):
            err_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            msg = err_data.get("msg") or err_data.get("message") or res.text
            raise ValueError(msg)

        # Immediate login to retrieve access_token and session
        return self.sign_in_user(email, password)

    def sign_in_user(self, email: str, password: str) -> Dict[str, Any]:
        """
        Authenticates a user via Supabase Auth password grant.
        """
        if not self.is_connected or not self.key:
            raise ValueError("Supabase database connection is not active.")

        headers = self._get_headers()
        payload = {
            "email": email,
            "password": password
        }
        res = self.session.post(f"{self.url}/auth/v1/token?grant_type=password", headers=headers, json=payload, timeout=8)
        if res.status_code != 200:
            err_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            msg = err_data.get("msg") or err_data.get("error_description") or err_data.get("message") or res.text
            raise ValueError(msg)

        return res.json()

    # ==========================================
    # Dedicated Users Table & Multi-User Auth
    # ==========================================
    def _get_local_users(self) -> Dict[str, Dict[str, Any]]:
        path = os.path.join(os.path.dirname(__file__), "data", "users.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_local_user(self, user_record: Dict[str, Any]):
        dir_path = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, "users.json")
        users = self._get_local_users()
        users[user_record["email"]] = user_record
        with open(path, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

    def sync_local_users_to_supabase(self) -> int:
        """Uploads any local users into Supabase public.users table if the table exists."""
        if not self.is_connected:
            return 0
        local_users = self._get_local_users()
        synced = 0
        headers = self._get_headers()
        for email, user_record in local_users.items():
            try:
                r = self.session.get(f"{self.url}/rest/v1/users?email=eq.{email}&limit=1", headers=headers, timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    if data and len(data) > 0:
                        continue
                self.session.post(f"{self.url}/rest/v1/users", headers=headers, json=user_record, timeout=4)
                synced += 1
            except Exception:
                pass
        return synced

    def get_user(self, email: str) -> Optional[Dict[str, Any]]:
        email = email.strip().lower()
        # 1. Query Supabase public.users if table exists
        if self.is_connected:
            try:
                headers = self._get_headers()
                r = self.session.get(f"{self.url}/rest/v1/users?email=eq.{email}&limit=1", headers=headers, timeout=6)
                if r.status_code in (200, 206):
                    data = r.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        return data[0]
            except Exception:
                pass

        # 2. Check local users repository
        local_users = self._get_local_users()
        return local_users.get(email)

    def create_app_user(self, email: str, password: str, full_name: str = "") -> Dict[str, Any]:
        """
        Creates a new user record in the dedicated users table with PBKDF2-SHA256 password hash.
        """
        email = email.strip().lower()
        existing = self.get_user(email)
        if existing:
            raise ValueError("A user with this email address has already been registered. Please switch to the Log In tab.")

        user_id = str(uuid.uuid4())
        pwd_hash = hash_password(password)
        now_iso = datetime.now().isoformat()
        user_record = {
            "id": user_id,
            "email": email,
            "password_hash": pwd_hash,
            "full_name": full_name or email.split("@")[0],
            "avatar_url": "",
            "auth_provider": "email",
            "created_at": now_iso
        }

        # 1. Always save to local user store
        self._save_local_user(user_record)

        # 2. Save to Supabase public.users table if created
        if self.is_connected:
            try:
                headers = self._get_headers()
                self.session.post(f"{self.url}/rest/v1/users", headers=headers, json=user_record, timeout=6)
            except Exception as e:
                logger.warning(f"Note on Supabase public.users sync: {e}")

        # 3. Also register in Supabase Auth as secondary integration
        try:
            self.sign_up_user(email, password, full_name)
        except Exception:
            pass

        return {
            "access_token": f"token_{user_id}_{secrets.token_hex(16)}",
            "token_type": "bearer",
            "user": {
                "id": user_id,
                "email": email,
                "user_metadata": {
                    "full_name": user_record["full_name"],
                    "avatar_url": ""
                }
            }
        }

    def authenticate_app_user(self, email: str, password: str) -> Dict[str, Any]:
        """
        Authenticates a user via dedicated users table password hash verification.
        """
        email = email.strip().lower()
        user = self.get_user(email)

        if user and user.get("password_hash"):
            if verify_password(password, user["password_hash"]):
                user_id = user.get("id") or str(uuid.uuid4())
                return {
                    "access_token": f"token_{user_id}_{secrets.token_hex(16)}",
                    "token_type": "bearer",
                    "user": {
                        "id": user_id,
                        "email": user["email"],
                        "user_metadata": {
                            "full_name": user.get("full_name") or email.split("@")[0],
                            "avatar_url": user.get("avatar_url", "")
                        }
                    }
                }
            else:
                raise ValueError("Invalid password. Please check your credentials.")

        # If not in dedicated table, try Supabase Auth grant
        if self.is_connected:
            try:
                return self.sign_in_user(email, password)
            except Exception:
                pass

        raise ValueError("User not found or invalid password.")

    def change_user_password(self, email: str, current_password: str, new_password: str) -> Dict[str, Any]:
        """
        Validates current password and updates to new password hash in dedicated table.
        """
        email = email.strip().lower()
        if not new_password or len(new_password) < 6:
            raise ValueError("New password must be at least 6 characters.")

        user = self.get_user(email)
        if not user:
            raise ValueError("User account not found.")

        stored_hash = user.get("password_hash")
        if stored_hash:
            if not verify_password(current_password, stored_hash):
                raise ValueError("Current password is incorrect.")
        elif self.is_connected:
            # If stored only in Supabase Auth, verify via sign_in
            try:
                self.sign_in_user(email, current_password)
            except Exception:
                raise ValueError("Current password is incorrect.")

        new_hash = hash_password(new_password)
        user["password_hash"] = new_hash
        user["updated_at"] = datetime.now().isoformat()

        # 1. Update local store
        self._save_local_user(user)

        # 2. Update Supabase public.users
        if self.is_connected:
            try:
                headers = self._get_headers()
                self.session.patch(
                    f"{self.url}/rest/v1/users?email=eq.{email}",
                    headers=headers,
                    json={"password_hash": new_hash, "updated_at": user["updated_at"]},
                    timeout=6
                )
            except Exception as e:
                logger.warning(f"Note on Supabase users password update: {e}")

            # 3. Also update Supabase Auth user password if available
            try:
                uid = user.get("id")
                if uid:
                    self.session.put(
                        f"{self.url}/auth/v1/admin/users/{uid}",
                        headers=headers,
                        json={"password": new_password},
                        timeout=6
                    )
            except Exception:
                pass

        return {"status": "success", "message": "Password changed successfully!"}
