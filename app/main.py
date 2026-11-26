import os
import re
import json
import asyncio
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from app.config import settings
from app.bert_engine import BertEmbeddingEngine, BertHashedCalendarTable
from app.calendar_service import CalendarService
from app.ai_service import AIService
from app.supabase_service import SupabaseService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BERT-Calendar-RAG")

app = FastAPI(
    title="Google Calendar RAG with BERT Forward Pass & Groq AI Reasoning",
    description="Intelligent Google Calendar Assistant with BERT embedding layer and Groq reasoning",
    version="1.0.0"
)

# Enable CORS for flexible cross-origin deployment (e.g. Vercel frontend + Render backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize core services
bert_engine = BertEmbeddingEngine(model_name=settings.BERT_MODEL_NAME)
hashed_table = BertHashedCalendarTable(bert_engine=bert_engine)
calendar_service = CalendarService(
    credentials_path=settings.GOOGLE_CREDENTIALS_FILE,
    token_path=settings.GOOGLE_TOKEN_FILE
)
ai_service = AIService(
    groq_api_key=settings.GROQ_API_KEY,
    groq_model=settings.GROQ_MODEL
)
# Supabase Cloud Database connector with multi-user isolation
supabase_service = SupabaseService()

def get_user_id(request: Request) -> str:
    """Extracts user_id from headers (from Supabase Auth or client guest session)."""
    user_id = request.headers.get("X-User-Id", "").strip()
    if not user_id:
        user_id = request.headers.get("X-User-Email", "").strip()
    if not user_id:
        user_id = request.query_params.get("user_id", "").strip()
    return user_id if user_id else "guest"

def sync_events_to_hashed_table(user_id: Optional[str] = None):
    """Fetches events from Supabase and Google Calendar and indexes them into BERT Hashed Table."""
    logger.info(f"Synchronizing calendar events into BERT Hashed Table (user_id={user_id or 'all'})...")
    events = []
    if supabase_service.is_connected:
        events = supabase_service.list_events(user_id=user_id or "all") or []
    if not events:
        events = calendar_service.list_events()

    if events:
        for ev in events:
            if ev and "id" in ev:
                ev_uid = ev.get("user_id", user_id or "guest")
                rec = hashed_table.insert_or_update(ev, user_id=ev_uid)
                if supabase_service.is_connected:
                    try:
                        supabase_service.save_hashed_record(rec, user_id=ev_uid)
                    except Exception:
                        pass
    logger.info(f"Hashed table total records: {len(hashed_table.table)}")

# Initial sync
try:
    sync_events_to_hashed_table()
except Exception as e:
    logger.warning(f"Initial sync warning: {e}")

# Request Models
class ChatRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5

class CreateEventRequest(BaseModel):
    summary: str
    date_time: Optional[str] = None
    event_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = ""
    location: Optional[str] = ""
    priority: Optional[str] = "medium"

class UpdateEventRequest(BaseModel):
    summary: Optional[str] = None
    date_time: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    priority: Optional[str] = None

class CredentialsUploadRequest(BaseModel):
    content: str

class ApiKeysUpdateRequest(BaseModel):
    groq_api_key: Optional[str] = None

class GoogleImportRequest(BaseModel):
    events: List[Dict[str, Any]]

# Authentication & Config Endpoints
@app.post("/api/calendar/auth/upload_credentials")
async def upload_credentials(req: CredentialsUploadRequest):
    """Saves user's uploaded credentials.json file."""
    try:
        parsed = json.loads(req.content)
        with open("credentials.json", "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2)
        calendar_service._try_init_google_service()
        return {"status": "success", "message": "credentials.json saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid credentials JSON: {str(e)}")

@app.post("/api/calendar/auth/connect")
async def connect_google_calendar():
    """Triggers Google Calendar OAuth2 flow."""
    res = await asyncio.to_thread(calendar_service.trigger_oauth_flow)
    if res.get("success"):
        sync_events_to_hashed_table()
    return res

@app.post("/api/calendar/auth/disconnect")
async def disconnect_google_calendar():
    """Disconnects Google Calendar and switches to local mode."""
    calendar_service.disconnect_google()
    sync_events_to_hashed_table()
    return {"status": "success", "message": "Disconnected from Google Calendar."}

class GoogleTokenAuthRequest(BaseModel):
    provider_token: str
    user_email: Optional[str] = ""
    refresh_token: Optional[str] = None

@app.post("/api/calendar/auth/google_token")
async def connect_google_via_token(req: GoogleTokenAuthRequest):
    """
    Connects Google Calendar API using the OAuth provider token received from Google Sign-In.
    Immediately fetches all live events from Google Calendar and synchronizes them to DB and BERT index.
    """
    token_preview = f"{req.provider_token[:10]}... (len={len(req.provider_token)})" if req.provider_token else "NONE"
    logger.info(f"Connecting Google Calendar with token={token_preview}, email={req.user_email}")
    
    try:
        success = calendar_service.init_from_token(req.provider_token, req.refresh_token)
        if success:
            if req.user_email and not calendar_service.user_email:
                calendar_service.user_email = req.user_email
            
            uid = req.user_email or "guest"
            logger.info(f"Google Calendar connected! Fetching live events for {uid}...")
            
            # Fetch all live events from Google Calendar immediately on every connect
            gcal_events = calendar_service.list_events(max_results=100)
            imported_count = 0
            for ev in gcal_events:
                ev["user_id"] = uid
                if supabase_service.is_connected:
                    try:
                        supabase_service.create_event(ev, user_id=uid)
                    except Exception:
                        pass
                rec = hashed_table.insert_or_update(ev, user_id=uid)
                if supabase_service.is_connected:
                    try:
                        supabase_service.save_hashed_record(rec, user_id=uid)
                    except Exception:
                        pass
                imported_count += 1
                
            logger.info(f"Successfully fetched and indexed {imported_count} events from Google Calendar for {uid}.")
            return {
                "status": "success",
                "message": f"Connected to Google Calendar for {calendar_service.user_email}! Fetched and indexed {imported_count} live events.",
                "email": calendar_service.user_email,
                "imported_count": imported_count,
                "events": gcal_events
            }
    except Exception as exc:
        logger.error(f"Error inside connect_google_via_token: {exc}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Google API Error: {str(exc)}")

    # If init_from_token returned False, get the last error details
    err_detail = getattr(calendar_service, "_last_auth_error", "Token was rejected or expired by Google Calendar.")
    logger.error(f"Google Calendar connection failed: {err_detail}")
    
    if "Google Calendar API has not been used" in err_detail or "calendar-json.googleapis.com" in err_detail:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar API is not enabled in Google Cloud Project 588474445972. Enable it here: https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=588474445972"
        )
        
    raise HTTPException(
        status_code=400,
        detail=f"Google Calendar Error: {err_detail}"
    )

@app.post("/api/config/keys")
async def update_api_keys(req: ApiKeysUpdateRequest):
    """Updates Groq API key."""
    if req.groq_api_key:
        ai_service.set_groq_key(req.groq_api_key)
    return {
        "status": "success",
        "groq_configured": bool(ai_service.groq_api_key)
    }

class SupabaseConfigRequest(BaseModel):
    supabase_url: str
    supabase_key: str

@app.post("/api/config/supabase")
async def update_supabase_config(req: SupabaseConfigRequest):
    connected = supabase_service.configure(req.supabase_url, req.supabase_key)
    if connected:
        try:
            with open(".env", "a", encoding="utf-8") as f:
                f.write(f"\nSUPABASE_URL={req.supabase_url}\nSUPABASE_KEY={req.supabase_key}\n")
        except Exception:
            pass
        events = calendar_service.list_events()
        supabase_service.sync_events(events)
    return {
        "status": "success" if connected else "failed",
        "supabase_connected": connected,
        "message": "Connected to Supabase PostgreSQL database!" if connected else "Failed to connect to Supabase. Check URL and Key."
    }

class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = ""

class AuthLoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/auth/register")
async def api_auth_register(req: AuthRegisterRequest):
    """
    Registers a new user in the dedicated users table with PBKDF2 password hashing.
    """
    try:
        session_data = supabase_service.create_app_user(
            email=req.email.strip().lower(),
            password=req.password,
            full_name=req.full_name or ""
        )
        return {"status": "success", "session": session_data}
    except Exception as e:
        logger.warning(f"Registration error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
async def api_auth_login(req: AuthLoginRequest):
    """
    Authenticates email + password via dedicated users table and returns an active session.
    """
    try:
        session_data = supabase_service.authenticate_app_user(
            email=req.email.strip().lower(),
            password=req.password
        )
        return {"status": "success", "session": session_data}
    except Exception as e:
        logger.warning(f"Login error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@app.post("/api/auth/change_password")
async def api_auth_change_password(req: ChangePasswordRequest, request: Request):
    """
    Changes password for the currently logged-in user.
    """
    email = request.headers.get("X-User-Email", "").strip() or request.headers.get("X-User-Id", "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=401, detail="You must be logged in to change your password.")

    try:
        res = supabase_service.change_user_password(
            email=email,
            current_password=req.current_password,
            new_password=req.new_password
        )
        return res
    except Exception as e:
        logger.warning(f"Change password error for {email}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/status")
async def get_system_status(request: Request):
    user_id = get_user_id(request)
    user_events = hashed_table.get_all_records(user_id=user_id)
    # Never expose secret service role key to the browser
    safe_client_key = "" if supabase_service.key.startswith("sb_secret_") else supabase_service.key
    gcal_email = getattr(calendar_service, "user_email", "").strip().lower()
    is_user_gcal = bool(calendar_service.is_connected_to_google and gcal_email and user_id.lower() == gcal_email)
    return {
        "bert_ready": bert_engine._is_ready,
        "bert_model": bert_engine.model_name,
        "indexed_events_count": len(user_events),
        "total_indexed_all_users": len(hashed_table.table),
        "current_user_id": user_id,
        "google_calendar_connected": is_user_gcal,
        "google_user_email": gcal_email if is_user_gcal else "",
        "supabase_connected": supabase_service.is_connected,
        "supabase_url": supabase_service.url,
        "supabase_key": safe_client_key,
        "groq_configured": bool(ai_service.groq_api_key),
        "active_ai_provider": "Groq",
        "active_model": ai_service.groq_model
    }

# ==========================================
# Multi-User Calendar CRUD Endpoints
# ==========================================
@app.get("/api/calendar/events")
async def list_calendar_events(request: Request):
    user_id = get_user_id(request)
    events_map = {}

    # 1. Fetch from Supabase strictly for this user
    if supabase_service.is_connected:
        try:
            sb_events = supabase_service.list_events(user_id=user_id) or []
            for ev in sb_events:
                ev_uid = ev.get("user_id") or "guest"
                if ev_uid == user_id:
                    events_map[ev["id"]] = ev
        except Exception as se:
            logger.warning(f"Supabase list_events error: {se}")

    # 2. Only merge Google Calendar events if the connected Google account belongs to this user!
    if calendar_service.is_connected_to_google:
        gcal_email = getattr(calendar_service, "user_email", "").strip().lower()
        current_email = (user_id or "").strip().lower()
        if gcal_email and current_email == gcal_email:
            try:
                gcal_events = calendar_service.list_events()
                for ev in gcal_events:
                    ev_id = ev.get("id")
                    if ev_id not in events_map:
                        ev["user_id"] = user_id
                        events_map[ev_id] = ev
            except Exception as ge:
                logger.warning(f"Live Google Calendar fetch notice: {ge}")

    # 3. Fallback to local store ONLY if neither Supabase nor Google is connected
    if not events_map and not supabase_service.is_connected and not calendar_service.is_connected_to_google:
        for ev in calendar_service.list_events():
            if ev.get("user_id", "guest") == user_id:
                events_map[ev["id"]] = ev

    all_events = list(events_map.values())

    # Sort events by start date/time
    def get_sort_key(e):
        return e.get("start", {}).get("dateTime") or e.get("start", {}).get("date") or e.get("start_time") or ""

    all_events.sort(key=get_sort_key)

    # Sync to in-memory BERT hashed table for this user
    for ev in all_events:
        hashed_table.insert_or_update(ev, user_id=user_id)

    return {
        "events": all_events,
        "total": len(all_events),
        "source": "supabase_and_google" if (supabase_service.is_connected and calendar_service.is_connected_to_google and getattr(calendar_service, "user_email", "").strip().lower() == user_id.lower()) else ("supabase" if supabase_service.is_connected else "google_or_local"),
        "user_id": user_id
    }

@app.post("/api/calendar/events")
async def create_calendar_event(req: CreateEventRequest, request: Request):
    user_id = get_user_id(request)
    try:
        raw_dt = req.date_time or req.start_time or req.event_date

        gcal_email = getattr(calendar_service, "user_email", "").strip().lower()
        is_user_gcal = bool(calendar_service.is_connected_to_google and gcal_email and user_id.lower() == gcal_email)

        if is_user_gcal:
            new_event = calendar_service.create_event(
                summary=req.summary,
                date_time=raw_dt,
                description=req.description or "",
                location=req.location or "",
                priority=req.priority or "medium",
                event_date=req.event_date
            )
        else:
            new_id = f"evt-{int(datetime.datetime.now().timestamp())}"
            is_all_day = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", raw_dt.strip())) or raw_dt.endswith("T00:00:00")
            dt_iso = ensure_iso_tz(raw_dt)
            date_dict = {"date": raw_dt[:10]} if is_all_day else {"dateTime": dt_iso}
            new_event = {
                "id": new_id,
                "summary": req.summary,
                "date_time": raw_dt[:10] if is_all_day else dt_iso,
                "start": date_dict,
                "end": date_dict,
                "description": req.description or "",
                "location": req.location or "",
                "priority": req.priority or "medium",
                "status": "confirmed",
                "source": "app"
            }
        new_event["user_id"] = user_id

        if supabase_service.is_connected:
            supabase_service.create_event(new_event, user_id=user_id)

        # Immediately perform BERT forward pass & index in hashed table
        rec = hashed_table.insert_or_update(new_event, user_id=user_id)
        if supabase_service.is_connected:
            supabase_service.save_hashed_record(rec, user_id=user_id)

        return {"status": "success", "event": new_event, "hash": rec["semantic_hash"], "user_id": user_id}
    except Exception as e:
        logger.error(f"Failed to create event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/calendar/events/{event_id}")
async def update_calendar_event(event_id: str, req: UpdateEventRequest, request: Request):
    user_id = get_user_id(request)
    try:
        raw_dt = req.date_time or req.start_time
        gcal_email = getattr(calendar_service, "user_email", "").strip().lower()
        is_user_gcal = bool(calendar_service.is_connected_to_google and gcal_email and user_id.lower() == gcal_email)

        if is_user_gcal:
            updated = calendar_service.update_event(
                event_id=event_id,
                summary=req.summary,
                date_time=raw_dt,
                description=req.description,
                location=req.location,
                priority=req.priority
            )
        else:
            updated = {"id": event_id}
            if req.summary: updated["summary"] = req.summary
            if raw_dt:
                is_d = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", raw_dt.strip()))
                updated["start"] = {"date": raw_dt[:10]} if is_d else {"dateTime": raw_dt}
                updated["end"] = updated["start"]
            if req.description: updated["description"] = req.description
            if req.location: updated["location"] = req.location
            if req.priority: updated["priority"] = req.priority

        updated["user_id"] = user_id

        if supabase_service.is_connected:
            supabase_service.update_event(event_id, req.dict(exclude_unset=True), user_id=user_id)

        rec = hashed_table.insert_or_update(updated, user_id=user_id)
        if supabase_service.is_connected:
            supabase_service.save_hashed_record(rec, user_id=user_id)

        return {"status": "success", "event": updated, "hash": rec["semantic_hash"], "user_id": user_id}
    except Exception as e:
        logger.error(f"Failed to update event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/calendar/events/{event_id}")
async def delete_calendar_event(event_id: str, request: Request):
    user_id = get_user_id(request)
    gcal_email = getattr(calendar_service, "user_email", "").strip().lower()
    is_user_gcal = bool(calendar_service.is_connected_to_google and gcal_email and user_id.lower() == gcal_email)
    if is_user_gcal:
        calendar_service.delete_event(event_id)
    if supabase_service.is_connected:
        supabase_service.delete_event(event_id, user_id=user_id)
        supabase_service.delete_hashed_record(event_id, user_id=user_id)
    
    hashed_table.remove(event_id, user_id=user_id)
    return {"status": "success", "deleted_id": event_id, "user_id": user_id}

@app.post("/api/calendar/sync")
async def sync_calendar(request: Request):
    user_id = get_user_id(request)
    sync_events_to_hashed_table(user_id=user_id)
    records = hashed_table.get_all_records(user_id=user_id)
    return {
        "status": "success",
        "user_id": user_id,
        "total_indexed": len(records),
        "events": [r["event"] for r in records if "event" in r]
    }

@app.post("/api/calendar/google_import")
async def import_google_events(req: GoogleImportRequest, request: Request):
    """Imports an array of Google Calendar events into Supabase under the signed-in user_id."""
    user_id = get_user_id(request)
    imported = 0
    for ev in req.events:
        if not ev.get("id"):
            ev["id"] = f"gcal-{int(asyncio.get_event_loop().time() * 1000)}-{imported}"
        ev["user_id"] = user_id
        if supabase_service.is_connected:
            supabase_service.create_event(ev, user_id=user_id)
        rec = hashed_table.insert_or_update(ev, user_id=user_id)
        if supabase_service.is_connected:
            supabase_service.save_hashed_record(rec, user_id=user_id)
        imported += 1
    return {"status": "success", "imported_count": imported, "user_id": user_id}

@app.get("/api/embeddings/table")
async def get_hashed_table(request: Request):
    """Returns the full hashed table with BERT embedding vectors and semantic hashes for this user."""
    user_id = get_user_id(request)
    records = hashed_table.get_all_records(user_id=user_id)
    return {
        "total": len(records),
        "user_id": user_id,
        "bert_model": bert_engine.model_name,
        "records": records
    }

# ==========================================
# Multi-User Chat History Endpoints
# ==========================================
@app.get("/api/chat/history")
async def get_chat_history(request: Request):
    user_id = get_user_id(request)
    messages = supabase_service.get_chat_history(user_id=user_id)
    return {"user_id": user_id, "messages": messages}

@app.delete("/api/chat/history")
async def clear_chat_history(request: Request):
    user_id = get_user_id(request)
    success = supabase_service.clear_chat_history(user_id=user_id)
    return {"status": "success" if success else "failed", "user_id": user_id}

# ==========================================
# Multi-User AI Chat & Reasoning
# ==========================================
def determine_intent(query: str, chat_history: List[Dict[str, Any]] = None) -> str:
    """
    Classifies user intent into:
    - 'CREATE': User explicitly wants to create/schedule a new event
    - 'DATA_RELATED': Query or action that depends on looking up existing calendar events
    - 'GENERAL': Conversational, greeting, or non-data related chat
    """
    q = query.lower().strip()
    
    # 1. CREATE intent: user wants to schedule/create/add a new event
    create_patterns = [
        r"\b(schedule|book|add|create|make|set up|insert)\b.*\b(event|meeting|appointment|call|session|lunch|dinner|breakfast|reminder|task|slot|date)\b",
        r"\b(schedule|book|add|create)\b.*\b(tomorrow|today|tonight|next\s+\w+|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}(:\d{2})?\s*(am|pm))\b",
        r"\bi want to (add|schedule|book|create|make)\b",
        r"\bcan you (add|schedule|book|create|make)\b",
        r"\bplease (add|schedule|book|create|make)\b"
    ]
    if any(re.search(pat, q) for pat in create_patterns):
        return "CREATE"

    # 2. DATA_RELATED intent: query about existing calendar data or update/delete existing events
    data_patterns = [
        r"\b(what('?s| do i have| is on my| are my)|when is|when do i|do i have|any events|any meetings|list my|show my|check my|my schedule|agenda|free time|conflicts?|upcoming|calendar)\b",
        r"\b(did you schedule|is it scheduled|you didn'?t schedule[ds]?|not scheduled|not added|wasn'?t scheduled|wasn'?t added|scheduled it)\b",
        r"\b(search|find|lookup|retrieve)\b",
        r"\b(events?|meetings?|appointments?)\b",
        r"\b(reschedule|postpone|move|shift|change|edit|update|delay)\b",
        r"\b(delete|cancel|remove|drop|clear|erase)\b",
        r"\b(cancel that|delete that|reschedule that|move that|change that)\b"
    ]
    if any(re.search(pat, q) for pat in data_patterns):
        return "DATA_RELATED"

    # 3. Default: GENERAL (casual talk, greetings, questions not requiring calendar context)
    return "GENERAL"

@app.post("/api/chat")
async def chat_and_reason(req: ChatRequest, request: Request):
    user_id = get_user_id(request)
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    # Retrieve past conversation turns for this user before saving current query
    chat_history = supabase_service.get_chat_history(user_id=user_id, limit=12)

    # 1. Persist user query to chat history
    supabase_service.save_chat_message(user_id=user_id, sender="user", message=req.query)

    # Determine intent: determine first if the model needs context or not
    intent = determine_intent(req.query, chat_history)
    logger.info(f"[{user_id}] Query: '{req.query}' -> Classified intent: {intent}")

    # Fetch user-scoped calendar events (used only for backend action execution, NOT passed to the model)
    if supabase_service.is_connected:
        user_events = supabase_service.list_events(user_id=user_id) or []
    else:
        user_events = calendar_service.list_events()

    # Flow 1: GENERAL (not data related -> pass directly to model, NO BERT retrieval)
    if intent == "GENERAL":
        reasoning_result = await asyncio.to_thread(
            ai_service.chat_regular,
            req.query,
            None,
            chat_history
        )
        response_text = reasoning_result.get("response_text", "")
        supabase_service.save_chat_message(
            user_id=user_id,
            sender="ai",
            message=response_text,
            metadata={"action": "NONE"}
        )
        return {
            "query": req.query,
            "user_id": user_id,
            "is_calendar_task": False,
            "retrieved_matches": [],
            "reasoning": reasoning_result.get("reasoning", "Direct conversational reply without calendar retrieval."),
            "response": response_text,
            "ai_powered": reasoning_result.get("ai_powered", False),
            "ai_provider": reasoning_result.get("ai_provider", "Groq"),
            "ai_model": reasoning_result.get("ai_model", settings.GROQ_MODEL),
            "action": "NONE",
            "executed_action": None
        }

    # Flow 2: DATA_RELATED (run BERT retrieval; if no match, respond "sorry no data")
    elif intent == "DATA_RELATED":
        retrieval_query = req.query
        if chat_history:
            last_msg = chat_history[-1].get("message", "")
            if last_msg:
                retrieval_query = f"{req.query} {last_msg[:100]}"

        logger.info(f"[{user_id}] BERT retrieval for data-related query: '{retrieval_query}'")
        raw_matches = hashed_table.query_similarity(retrieval_query, user_id=user_id, top_k=req.top_k or 4)

        # Filter matches that have a meaningful similarity score (>= 0.28)
        meaningful_matches = [m for m in raw_matches if m.get("similarity_score", 0) >= 0.28]

        # Broad schedule inquiry (e.g. "what do I have?", "show my schedule") allows any indexed events
        is_broad_schedule_inquiry = any(re.search(pat, req.query.lower()) for pat in [
            r"\b(show|list|what|check|all)\b.*\b(schedule|calendar|upcoming|agenda|everything)\b",
            r"\bwhat do i have\b", r"\bmy schedule\b", r"\ball events\b"
        ])
        if is_broad_schedule_inquiry and raw_matches:
            meaningful_matches = raw_matches

        # If no matching data found in the calendar
        if not meaningful_matches:
            no_data_reply = "Sorry, there is no available data or matching events in your calendar for that."
            supabase_service.save_chat_message(
                user_id=user_id,
                sender="ai",
                message=no_data_reply,
                metadata={"action": "NONE"}
            )
            return {
                "query": req.query,
                "user_id": user_id,
                "is_calendar_task": True,
                "retrieved_matches": [],
                "reasoning": "BERT forward pass found no matching calendar records for the query.",
                "response": no_data_reply,
                "ai_powered": True,
                "ai_provider": "Groq",
                "ai_model": settings.GROQ_MODEL,
                "action": "NONE",
                "executed_action": None
            }

        top_matches = meaningful_matches
        reasoning_result = await asyncio.to_thread(
            ai_service.reason,
            req.query,
            top_matches,
            chat_history
        )

    # Flow 3: CREATE (scheduling a new event -> model parses details, then backend creates)
    else: # intent == "CREATE"
        top_matches = []
        reasoning_result = await asyncio.to_thread(
            ai_service.reason,
            req.query,
            [],
            chat_history
        )

    action = reasoning_result.get("action", "NONE")
    action_params = reasoning_result.get("action_params") or {}
    executed_action = None
    response_text = reasoning_result.get("response_text", "")

    # Step 3: Execute actions scoped to this user
    if action == "CREATE_EVENT" and action_params.get("summary"):
        try:
            summary = action_params.get("summary")
            date_time = action_params.get("date_time") or action_params.get("start_time") or action_params.get("event_date")

            # Default date if no date_time provided
            if not date_time:
                default_dt = datetime.datetime.now().astimezone() + datetime.timedelta(days=1)
                date_time = default_dt.strftime("%Y-%m-%d")

            pri = action_params.get("priority") or "medium"
            q_lower = req.query.lower()
            if "high priority" in q_lower or "urgent" in q_lower or "asap" in q_lower:
                pri = "high"
            elif "low priority" in q_lower or "flexible" in q_lower or "casual" in q_lower:
                pri = "low"

            gcal_email = getattr(calendar_service, "user_email", "").strip().lower()
            is_user_gcal = bool(calendar_service.is_connected_to_google and gcal_email and user_id.lower() == gcal_email)

            if is_user_gcal:
                new_event = calendar_service.create_event(
                    summary=summary,
                    date_time=date_time,
                    description=action_params.get("description", ""),
                    location=action_params.get("location", ""),
                    priority=pri
                )
            else:
                new_id = f"evt-{int(datetime.datetime.now().timestamp())}"
                is_all_day = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_time.strip())) or date_time.endswith("T00:00:00")
                dt_iso = ensure_iso_tz(date_time)
                date_dict = {"date": date_time[:10]} if is_all_day else {"dateTime": dt_iso}
                new_event = {
                    "id": new_id,
                    "summary": summary,
                    "date_time": date_time[:10] if is_all_day else dt_iso,
                    "start": date_dict,
                    "end": date_dict,
                    "description": action_params.get("description", ""),
                    "location": action_params.get("location", ""),
                    "priority": pri,
                    "status": "confirmed",
                    "source": "app"
                }
            new_event["user_id"] = user_id

            if supabase_service.is_connected:
                supabase_service.create_event(new_event, user_id=user_id)

            rec = hashed_table.insert_or_update(new_event, user_id=user_id)
            if supabase_service.is_connected:
                supabase_service.save_hashed_record(rec, user_id=user_id)

            executed_action = {
                "type": "CREATED",
                "event": new_event,
                "summary": summary,
                "semantic_hash": rec["semantic_hash"]
            }
            s_display = new_event.get("start", {}).get("dateTime") or new_event.get("start", {}).get("date") or date_time
            response_text = f"Got it! I have scheduled **{summary}** for {s_display}."
        except Exception as e:
            logger.error(f"Error executing CREATE_EVENT action: {e}", exc_info=True)
            executed_action = {"type": "ERROR", "error": str(e)}
            response_text = f"Sorry, I encountered an error scheduling the event: {str(e)}"

    elif action == "UPDATE_EVENT":
        try:
            target_id = action_params.get("event_id")
            matched_ev = None
            if target_id:
                matched_ev = next((e for e in user_events if e.get("id") == target_id), None)

            if not matched_ev:
                sum_target = (action_params.get("summary") or "").lower().strip()
                if sum_target:
                    matched_ev = next((e for e in user_events if sum_target in (e.get("summary") or "").lower()), None)

            if not matched_ev and top_matches:
                matched_ev = top_matches[0].get("event")
                if matched_ev:
                    target_id = matched_ev.get("id")

            if matched_ev and not target_id:
                target_id = matched_ev.get("id")

            if target_id:
                pri = action_params.get("priority")
                q_lower = req.query.lower()
                if "high priority" in q_lower or "urgent" in q_lower:
                    pri = "high"
                elif "low priority" in q_lower:
                    pri = "low"

                dt_update = action_params.get("date_time") or action_params.get("start_time")
                updated = calendar_service.update_event(
                    event_id=target_id,
                    summary=action_params.get("summary") or (matched_ev.get("summary") if matched_ev else None),
                    date_time=dt_update,
                    description=action_params.get("description"),
                    location=action_params.get("location"),
                    priority=pri
                )
                if not updated:
                    updated = {**(matched_ev or {}), "id": target_id}
                    if action_params.get("summary"):
                        updated["summary"] = action_params["summary"]
                    if dt_update:
                        is_d = bool(re.match(r"^\d{4}-\d{2}-\d{2}$", dt_update.strip()))
                        updated["start"] = {"date": dt_update[:10]} if is_d else {"dateTime": dt_update}
                        updated["end"] = updated["start"]
                    if action_params.get("description"):
                        updated["description"] = action_params["description"]
                    if action_params.get("location"):
                        updated["location"] = action_params["location"]
                    if pri:
                        updated["priority"] = pri

                updated["user_id"] = user_id

                if supabase_service.is_connected:
                    supabase_service.update_event(target_id, action_params, user_id=user_id)

                rec = hashed_table.insert_or_update(updated, user_id=user_id)
                if supabase_service.is_connected:
                    supabase_service.save_hashed_record(rec, user_id=user_id)

                executed_action = {
                    "type": "UPDATED",
                    "event": updated,
                    "summary": updated.get("summary") or "Event",
                    "semantic_hash": rec["semantic_hash"]
                }
                response_text = f"Successfully updated **{updated.get('summary', 'the event')}** in your calendar."
            else:
                executed_action = {"type": "ERROR", "error": "Could not identify target event to update."}
                response_text = "Sorry, I couldn't find that event in your calendar to update."
        except Exception as e:
            logger.error(f"Error executing UPDATE_EVENT action: {e}", exc_info=True)
            executed_action = {"type": "ERROR", "error": str(e)}
            response_text = f"Sorry, I encountered an error updating the event: {str(e)}"

    elif action == "DELETE_EVENT":
        try:
            target_id = action_params.get("event_id")
            matched_ev = None
            if target_id:
                matched_ev = next((e for e in user_events if e.get("id") == target_id), None)

            if not matched_ev:
                sum_target = (action_params.get("summary") or "").lower().strip()
                if sum_target:
                    matched_ev = next((e for e in user_events if sum_target in (e.get("summary") or "").lower()), None)

            if not matched_ev and top_matches:
                matched_ev = top_matches[0].get("event")
                if matched_ev:
                    target_id = matched_ev.get("id")

            if matched_ev and not target_id:
                target_id = matched_ev.get("id")

            if target_id:
                target_summary = (matched_ev.get("summary") if matched_ev else action_params.get("summary")) or "Event"
                calendar_service.delete_event(target_id)
                if supabase_service.is_connected:
                    supabase_service.delete_event(target_id, user_id=user_id)
                    supabase_service.delete_hashed_record(target_id, user_id=user_id)
                hashed_table.remove(target_id, user_id=user_id)
                executed_action = {
                    "type": "DELETED",
                    "event_id": target_id,
                    "summary": target_summary,
                    "event": matched_ev or {"id": target_id, "summary": target_summary}
                }
                response_text = f"I have cancelled and removed **{target_summary}** from your calendar."
            else:
                executed_action = {"type": "ERROR", "error": "Could not identify target event to delete."}
                response_text = "Sorry, I couldn't find that event in your calendar to cancel."
        except Exception as e:
            logger.error(f"Error executing DELETE_EVENT action: {e}", exc_info=True)
            executed_action = {"type": "ERROR", "error": str(e)}
            response_text = f"Sorry, I encountered an error deleting the event: {str(e)}"

    # 2. Persist AI response to Supabase chat_messages
    supabase_service.save_chat_message(
        user_id=user_id,
        sender="ai",
        message=response_text,
        metadata={"action": action, "executed_action": executed_action}
    )

    return {
        "query": req.query,
        "user_id": user_id,
        "is_calendar_task": intent != "GENERAL",
        "retrieved_matches": top_matches,
        "reasoning": reasoning_result.get("reasoning", ""),
        "response": response_text,
        "ai_powered": reasoning_result.get("ai_powered", False),
        "ai_provider": reasoning_result.get("ai_provider", "Groq"),
        "ai_model": reasoning_result.get("ai_model", settings.GROQ_MODEL),
        "action": action,
        "executed_action": executed_action
    }

# ==========================================
# Speech Recognition & Audio Transcription
# ==========================================
@app.post("/api/audio/transcribe")
async def transcribe_audio_endpoint(file: UploadFile = File(...)):
    """
    Transcribes audio payload using Groq Whisper model (whisper-large-v3-turbo).
    """
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty audio recording.")
        
        filename = file.filename or "recording.webm"
        text = await asyncio.to_thread(ai_service.transcribe_audio, content, filename)
        return {"text": text, "status": "success"}
    except Exception as e:
        logger.error(f"Speech transcription endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"Speech transcription failed: {str(e)}")

# Mount static files directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return {"message": "BERT Calendar RAG API running."}

if __name__ == "__main__":
    import uvicorn
    from app.config import settings
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT)
