import os
import json
import re
import datetime
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class AIService:
    """
    Reasoning layer powered by Groq (ultra-fast, 14,400 free requests/day)
    with speech recognition via Groq Whisper and robust local heuristics fallback.
    """
    def __init__(self,
                 groq_api_key: Optional[str] = None,
                 groq_model: str = "openai/gpt-oss-120b"):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.active_provider = "groq"

        self.groq_client = None
        self._init_groq()

    def _init_groq(self):
        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key)
                logger.info(f"Initialized Groq client with model: {self.groq_model}")
            except Exception as e:
                logger.error(f"Failed to initialize Groq: {e}")
                self.groq_client = None

    def set_groq_key(self, key: str):
        self.groq_api_key = key
        self._init_groq()

    def chat_regular(self,
                     user_query: str,
                     retrieved_events: List[Dict[str, Any]] = None,
                     chat_history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Regular conversational chat. Uses ONLY context retrieved via BERT semantic hashing.
        """
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S (Day: %A)")

        context_block = ""
        if retrieved_events:
            retrieved_list = []
            for item in retrieved_events:
                ev = item.get("event", item)
                s = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or "TBD"
                h = item.get("semantic_hash", "")
                hash_tag = f" [Hash: {h[:8]}..]" if h else ""
                sim = item.get("similarity_score")
                sim_tag = f" [Sim: {sim:.3f}]" if sim is not None else ""
                retrieved_list.append(f"• {ev.get('summary', 'Untitled')} (Scheduled: {s}){sim_tag}{hash_tag}")
            if retrieved_list:
                context_block = f"RELEVANT CALENDAR CONTEXT RETRIEVED VIA BERT SEMANTIC HASHING:\n" + "\n".join(retrieved_list) + "\n\n"

        system_msg = (
            f"You are an intelligent, friendly AI Calendar Assistant.\n"
            f"Current DateTime: {current_time_str}\n\n"
            f"{context_block}"
            f"GREETINGS & SOCIAL PLEASANTRIES:\n"
            f"Always warmly and naturally respond to greetings, testing, and social pleasantries "
            f"(such as 'hello', 'hi', 'hey', 'good morning', 'how are you', 'test', 'ping', 'thanks'). "
            f"Reply with a cheerful greeting and invite them to view, manage, or schedule their events.\n\n"
            f"DOMAIN BOUNDARY POLICY (FOR TOPICAL QUESTIONS):\n"
            f"You are specialized exclusively as a Calendar and Schedule Assistant. "
            f"If the user wants to talk just answer them but dont do any action unless told to. " 
            f"If the user asks questions completely unrelated to calendar management, schedules, meetings, events, appointments, or time planning "
            f"you MUST decline politely: "
            f"'I am specialized exclusively as your Calendar and Schedule Assistant. I can only assist with your calendar events, meetings, and schedule planning. How can I help with your schedule today?'\n\n"
            f"Keep your answers concise, helpful, and natural."
        )

        messages = [{"role": "system", "content": system_msg}]
        if chat_history:
            for msg in chat_history[-6:]:
                sender = msg.get("sender")
                role = "user" if sender == "user" else "assistant"
                content = (msg.get("message") or "").strip()
                if content and content != user_query:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_query})

        if self.groq_client:
            try:
                t0 = datetime.datetime.now()
                res = self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=messages,
                    max_tokens=600,
                    temperature=0.1
                )
                elapsed = (datetime.datetime.now() - t0).total_seconds()
                text = res.choices[0].message.content.strip()
                return {
                    "action": "NONE",
                    "action_params": None,
                    "reasoning": f"Processed via Groq ({self.groq_model}) in {elapsed:.2f}s with BERT semantic hashing context.",
                    "response_text": text,
                    "is_calendar_task": False,
                    "ai_powered": True,
                    "ai_provider": "Groq",
                    "ai_model": self.groq_model
                }
            except Exception as e:
                logger.warning(f"Groq chat failed: {e}")

        return self._local_conversational_reply(user_query, retrieved_events)

    def reason(self,
               user_query: str,
               retrieved_events: List[Dict[str, Any]],
               chat_history: List[Dict[str, Any]] = None,
               all_events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Executes reasoning over user prompt, conversation history, and BERT semantic hashing retrieval results.
        Only the context retrieved from BERT hashing is passed to the LLM (no full calendar dumps).
        Returns reasoning explanation, suggested action (create/update/delete/none), and action parameters.
        """
        now = datetime.datetime.now()
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S (Day: %A)")
        
        history_lines = []
        if chat_history:
            for msg in chat_history[-8:]:
                sender = "User" if msg.get("sender") == "user" else "Assistant"
                m_text = (msg.get("message") or "").strip()
                if m_text and m_text != user_query:
                    history_lines.append(f"{sender}: {m_text}")
        history_str = "\n".join(history_lines) if history_lines else "None (first turn)"

        retrieved_context = []
        for i, item in enumerate(retrieved_events):
            ev = item.get("event", {})
            retrieved_context.append(
                f"- [Rank {i+1} | Cosine Sim: {item.get('similarity_score', 0):.4f} | Hash: {item.get('semantic_hash', '')[:12]}...]\n"
                f"  ID: {item.get('id')}\n"
                f"  Summary: {ev.get('summary', 'Untitled')}\n"
                f"  Start: {ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')}\n"
                f"  End: {ev.get('end', {}).get('dateTime') or ev.get('end', {}).get('date')}\n"
                f"  Location: {ev.get('location', 'N/A')}\n"
                f"  Description: {ev.get('description', 'N/A')}"
            )
        retrieved_str = "\n".join(retrieved_context) if retrieved_context else "No close semantic hash matches found."

        prompt = f"""You are an intelligent Calendar Assistant AI with access to Google Calendar data indexed via BERT forward-pass embeddings and semantic hashing.

CURRENT DATETIME: {current_time_str}

RECENT CONVERSATION CONTEXT:
{history_str}

RELEVANT CALENDAR CONTEXT RETRIEVED VIA BERT SEMANTIC HASHING & COSINE SIMILARITY:
{retrieved_str}

USER REQUEST:
"{user_query}"

INSTRUCTIONS:
1. CONTEXT MEMORY & PRONOUN RESOLUTION: Use the RECENT CONVERSATION CONTEXT above to resolve pronouns, follow-ups, and references (e.g. 'that', 'it', 'her', 'the meeting', 'reschedule to 3pm', 'same time as yesterday', 'cancel that'). If the user refers to an event, locate its exact ID in the RELEVANT CALENDAR CONTEXT above and execute the requested action on that event.
2. GREETINGS & DOMAIN BOUNDARY POLICY:
   - For greetings, testing, or social pleasantries (e.g., 'hello', 'hi', 'hey', 'test', 'ping', 'how are you', 'good morning', 'thanks'):
     - Set "action": "NONE"
     - Set "action_params": null
     - Set "reasoning": "User sent a friendly greeting or system check."
     - Set "response_text": Friendly, welcoming reply offering to help manage their calendar, view upcoming meetings, or plan events.
   - For completely unrelated non-calendar requests (e.g., asking to write software code, solve math, homework, recipes, essays, politics, or trivia):
     - Set "action": "NONE"
     - Set "action_params": null
     - Set "reasoning": "Unrelated non-calendar request rejected per domain policy."
     - Set "response_text": "I am specialized exclusively as your Calendar and Schedule Assistant. I can only assist with your calendar events, meetings, and schedule planning. How can I help with your schedule today?"
3. EVENT ACTION HANDLING:
   - CREATE_EVENT: When the user asks to schedule, add, create, or book an event or meeting:
     - Set "action": "CREATE_EVENT"
     - Populate "action_params":
       - "summary": Clear title of the event (MANDATORY).
       - "date_time": Event date or datetime string (MANDATORY).
         * If NO specific time was mentioned: Format STRICTLY as date only "YYYY-MM-DD" (e.g., "2026-11-20"). NEVER invent, guess, or assign any hours or minutes!
         * If a specific time was mentioned: Format as "YYYY-MM-DDTHH:MM:SS" (e.g., "2026-11-20T14:30:00").
         * If no date was specified, use tomorrow relative to CURRENT DATETIME.
       - "priority": "high", "medium", or "low" if mentioned, otherwise null (OPTIONAL, defaults to medium).
       - "description": Description or notes if provided, else null (OPTIONAL).
       - "location": Location if provided, else null (OPTIONAL).
   - UPDATE_EVENT: When the user asks to reschedule, move, edit, update, rename, or change an existing event:
     - Locate the exact event from the RELEVANT CALENDAR CONTEXT or RECENT CONVERSATION CONTEXT.
     - Set "action": "UPDATE_EVENT"
     - Populate "action_params":
       - "event_id": The exact event ID (e.g. "evt-103").
       - "summary": Updated title or existing title.
       - "date_time": New date ("YYYY-MM-DD") or datetime ("YYYY-MM-DDTHH:MM:SS") if changed, else null.
       - "description": Updated description if changed, else null.
       - "location": Updated location if changed, else null.
       - "priority": "high", "medium", or "low" if changed, else null.
   - DELETE_EVENT: When the user asks to delete, cancel, remove, or drop an event:
     - Locate the exact event from the RELEVANT CALENDAR CONTEXT or RECENT CONVERSATION CONTEXT.
     - Set "action": "DELETE_EVENT"
     - Populate "action_params":
       - "event_id": The exact event ID to delete (e.g. "evt-103").
       - "summary": The title of the event being deleted.
   - NONE: When the user is simply inquiring about their schedule or checking free slots without requesting any change.
4. Return STRICTLY a valid JSON object matching:
{{
    "action": "CREATE_EVENT" | "UPDATE_EVENT" | "DELETE_EVENT" | "NONE",
    "action_params": {{
        "event_id": "target event id if updating or deleting, else null",
        "summary": "Title of event (Mandatory)",
        "date_time": "YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS (Mandatory)",
        "description": "event description or null",
        "location": "location or null",
        "priority": "high" | "medium" | "low" | null
    }},
    "reasoning": "Step-by-step reasoning explaining which BERT semantic hashing retrieved events were matched, dates calculated, and logic applied",
    "response_text": "A friendly, conversational answer explaining the schedule or confirming the requested action"
}}
"""
        if self.groq_client:
            try:
                t0 = datetime.datetime.now()
                res = self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": "You are a Calendar AI assistant. Output JSON only. Strictly refuse any non-calendar requests."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1
                )
                elapsed = (datetime.datetime.now() - t0).total_seconds()
                raw_text = res.choices[0].message.content.strip()
                parsed = json.loads(raw_text)
                parsed["ai_powered"] = True
                parsed["ai_provider"] = "Groq"
                parsed["ai_model"] = self.groq_model
                parsed["is_calendar_task"] = True
                parsed["reasoning"] += f" (Reasoned via Groq {self.groq_model} in {elapsed:.2f}s)"
                return parsed
            except Exception as e:
                logger.warning(f"Groq reasoning call failed: {e}. Trying fallback...")

        fallback_res = self._heuristic_reasoning(user_query, retrieved_events, now)
        fallback_res["ai_powered"] = False
        fallback_res["is_calendar_task"] = True
        return fallback_res

    def _local_conversational_reply(self, query: str, retrieved_events: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        q = query.lower().strip()
        if "database" in q or "data" in q:
            count = len(retrieved_events or [])
            reply = f"Yes, I have your calendar database with {count} relevant events retrieved via BERT hashing! What would you like to review or schedule?"
        elif any(w in q for w in ["hi", "hello", "hey", "good morning", "good evening", "howdy"]):
            reply = "Hello there! I'm your AI Calendar Assistant. How can I help you with your schedule or tasks today?"
        elif any(w in q for w in ["how are you", "how's it going", "how r u"]):
            reply = "I'm doing great, thank you! Ready to help you view, create, or update your calendar events."
        elif any(w in q for w in ["test", "ping", "testing"]):
            reply = "I'm online and ready! How can I assist you with your schedule or meetings today?"
        elif any(w in q for w in ["thanks", "thank you", "thx"]):
            reply = "You're very welcome! Let me know if you need to schedule or adjust anything else."
        elif "who are you" in q or "what can you do" in q:
            reply = "I'm your intelligent Calendar Assistant. I use a BERT forward-pass embedding layer to index calendar events into a semantic hashed table, match your queries with cosine similarity, and reason about your schedule."
        else:
            reply = "I am specialized exclusively as your Calendar and Schedule Assistant. I can only assist with your calendar events, meetings, and schedule planning. How can I help with your schedule today?"

        return {
            "action": "NONE",
            "action_params": None,
            "reasoning": "Conversational reply generated by local engine.",
            "response_text": reply,
            "is_calendar_task": False,
            "ai_powered": False
        }

    def _heuristic_reasoning(self, query: str, retrieved_events: List[Dict[str, Any]],
                             now: datetime.datetime) -> Dict[str, Any]:
        q_lower = query.lower()
        is_delete = any(k in q_lower for k in ["delete", "cancel", "remove", "drop", "erase", "clear"])
        is_create = any(k in q_lower for k in ["make a new event", "create event", "schedule", "book", "add event", "new meeting"])
        is_update = any(k in q_lower for k in ["update", "reschedule", "move", "change", "postpone", "shift"])

        if is_delete and retrieved_events:
            target = retrieved_events[0]
            target_ev = target.get("event", {})
            event_id = target.get("id") or target_ev.get("id")
            title = target_ev.get("summary", "Event")
            return {
                "action": "DELETE_EVENT",
                "action_params": {
                    "event_id": event_id,
                    "summary": title
                },
                "reasoning": f"Identified deletion request for event '{title}' (ID: {event_id}) from BERT hashing matches. Executing cancellation.",
                "response_text": f"I have cancelled and removed **{title}** from your schedule."
            }
        elif is_create and not is_update:
            start_dt = now + datetime.timedelta(days=7, hours=2)
            end_dt = start_dt + datetime.timedelta(hours=1)
            title = query.replace("schedule", "").replace("make a new event", "").replace("create event", "").strip(" :\"'")
            if not title:
                title = "New Calendar Event"
            return {
                "action": "CREATE_EVENT",
                "action_params": {
                    "event_id": None,
                    "summary": title.title(),
                    "start_time": start_dt.strftime("%Y-%m-%dT%H:00:00"),
                    "end_time": end_dt.strftime("%Y-%m-%dT%H:00:00"),
                    "description": f"Created via BERT Calendar assistant for query: '{query}'",
                    "location": "Online / Meeting Room"
                },
                "reasoning": f"Identified creation request for '{title}'. Scheduled default slot for next week at {start_dt.strftime('%A, %b %d at %H:%M')}.",
                "response_text": f"I've prepared a new event: **{title.title()}** for {start_dt.strftime('%A, %B %d at %I:%M %p')}."
            }
        elif is_update and retrieved_events:
            top_match = retrieved_events[0]
            top_ev = top_match.get("event", {})
            event_id = top_match.get("id")
            title = top_ev.get("summary", "Event")
            new_start = now + datetime.timedelta(days=2, hours=3)
            new_end = new_start + datetime.timedelta(hours=1)
            return {
                "action": "UPDATE_EVENT",
                "action_params": {
                    "event_id": event_id,
                    "summary": title,
                    "start_time": new_start.strftime("%Y-%m-%dT%H:00:00"),
                    "end_time": new_end.strftime("%Y-%m-%dT%H:00:00"),
                    "description": top_ev.get("description", "") + " (Rescheduled via Assistant)",
                    "location": top_ev.get("location", "")
                },
                "reasoning": f"BERT cosine similarity matched query '{query}' to '{title}' (similarity score: {top_match.get('similarity_score', 0):.4f}, semantic hash: {top_match.get('semantic_hash', '')[:10]}). Executing requested update.",
                "response_text": f"I matched your query to **{title}** with cosine similarity of {top_match.get('similarity_score', 0):.4f}. Updated the scheduled time to {new_start.strftime('%A, %b %d at %I:%M %p')}!"
            }
        else:
            matched_summaries = []
            for item in retrieved_events[:4]:
                ev = item.get("event", {})
                s = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or "Upcoming"
                score = item.get("similarity_score", 0.0)
                matched_summaries.append(f"• **{ev.get('summary')}** ({s}) - *Cosine Similarity: {score:.3f}*")

            summary_list = "\n".join(matched_summaries) if matched_summaries else "No upcoming events found."
            return {
                "action": "NONE",
                "action_params": None,
                "reasoning": f"BERT forward pass vectorized the question and matched {len(retrieved_events)} events by cosine similarity in the hashed table.",
                "response_text": f"Here are the most relevant events retrieved from your calendar via BERT embedding & cosine similarity:\n\n{summary_list}"
            }

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """
        Transcribes speech audio into text using Groq Whisper (whisper-large-v3-turbo).
        """
        if not self.groq_client:
            raise ValueError("Groq client not initialized for Whisper speech recognition.")
        
        try:
            transcription = self.groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=(filename, audio_bytes),
                response_format="text"
            )
            return str(transcription).strip()
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            raise
