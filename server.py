import os
import time
import uuid
import openai
import json
import requests
from typing import Dict, Deque
from collections import deque, defaultdict
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from fastapi.responses import JSONResponse

# Secure your API keys
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("missing api key bruh")

client = openai.OpenAI(api_key=openai_api_key)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")

app = FastAPI(title="Educational App Server")

# Initialize rate limiter (SlowAPI) for per-route limits
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Global rate limiting settings (for overall server load)
GLOBAL_REQUEST_LIMIT = 7  # maximum requests per TIME_WINDOW
TIME_WINDOW = 60  # seconds
global_requests: Deque[float] = deque()

# Queue for requests when global limit is exceeded
request_queue: Deque[str] = deque()
tasks: Dict[str, Dict] = {}

# --- NEW: IP Abuse Tracking ---
# Track recent request timestamps per IP (for 3-second window)
ip_request_history: Dict[str, Deque[float]] = defaultdict(deque)
# Dictionary for blocked IPs with expiration timestamps
blocked_ips: Dict[str, float] = {}

# --- Enhanced Logging Functions ---
def send_error_to_discord(error_message: str, request_data: dict = None):
    """Send error details to Discord for logging."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    embed = {
        "username": "FastAPI Error Logger",
        "embeds": [
            {
                "title": "🚨 Unexpected Error Occurred!",
                "description": f"**Time:** {timestamp}\n**Error:** {error_message}",
                "color": 15158332,
                "fields": [],
            }
        ],
    }
    if request_data:
        embed["embeds"][0]["fields"].append(
            {"name": "Request Data", "value": json.dumps(request_data, indent=2)}
        )
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=embed, timeout=5)
    except Exception as e:
        print(f"Failed to send error to Discord: {e}")

def send_ddos_alert_to_discord(client_ip: str, count: int):
    """Send a detailed DDoS alert to Discord."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    rps = count / 3.0  # requests per second over 3 seconds
    embed = {
        "username": "DDoS Alert Bot",
        "embeds": [
            {
                "title": "🚨 DDoS Attack Detected!",
                "description": f"IP **{client_ip}** made **{count}** requests in 3 seconds (≈ {rps:.2f} req/s) and has been blocked for 12 hours.",
                "color": 15158332,
                "fields": [
                    {"name": "Timestamp (UTC)", "value": timestamp},
                    {"name": "Block Duration", "value": "12 hours"}
                ],
            }
        ],
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=embed, timeout=5)
    except Exception as e:
        print(f"Failed to send DDoS alert to Discord: {e}")

# --- Models ---
class QuizRequest(BaseModel):
    topic: str
    grade: int
    num_questions: int

class NotesRequest(BaseModel):
    topic: str
    grade: int

# --- Middleware for Global Rate Limit and IP Blocking ---
@app.middleware("http")
@app.middleware("http")
async def custom_rate_limit_middleware(request: Request, call_next):
    current_time = time.time()
    client_ip = get_remote_address(request)

    # 🚨 Check if IP is blocked
    if client_ip in blocked_ips:
        if current_time < blocked_ips[client_ip]:
            return JSONResponse(
                {"detail": "Too many requests. Your IP is temporarily blocked."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )
        else:
            # Unblock IP after expiration
            del blocked_ips[client_ip]
            ip_request_history[client_ip].clear()

    # 📌 Track IP requests in the last 3 seconds
    history = ip_request_history[client_ip]
    while history and current_time - history[0] > 3:
        history.popleft()
    history.append(current_time)

    # 🚫 **If more than 2 requests in 3 sec → block IP & STOP processing**
    if len(history) > 2:
        block_until = current_time + 12 * 3600  # 12 hours
        blocked_ips[client_ip] = block_until
        
        # 🔴 **Log DDoS attack to Discord**
        attack_details = {
            "username": "FastAPI Security",
            "embeds": [
                {
                    "title": "🚨 DDoS Attack Detected!",
                    "description": f"IP `{client_ip}` made **{len(history)}** requests in 3 seconds and has been blocked.",
                    "color": 15158332,  # Red color
                    "fields": [
                        {"name": "Timestamp (UTC)", "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")},
                        {"name": "Block Duration", "value": "12 hours"},
                        {"name": "Requests Per Second", "value": f"{len(history) / 3:.2f} req/s"},
                    ]
                }
            ]
        }
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=attack_details, timeout=5)
        except Exception as e:
            print(f"Failed to send DDoS alert to Discord: {e}")

        # ❌ **Immediately return error response → NO queueing, NO processing**
        return JSONResponse(
            {"detail": "Too many requests in a short period. Your IP has been blocked for 12 hours."},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )

    # 🌍 **Global rate limiting (for all users)**
    while global_requests and current_time - global_requests[0] > TIME_WINDOW:
        global_requests.popleft()
    
    if len(global_requests) < GLOBAL_REQUEST_LIMIT:
        global_requests.append(current_time)
        return await call_next(request)

    # 🕒 **If global limit is exceeded → queue request**
    task_id = str(uuid.uuid4())
    request_queue.append(task_id)
    tasks[task_id] = {"status": "queued", "created_at": current_time, "request_path": str(request.url.path)}

    return JSONResponse(
        {"status": "queued", "position": len(request_queue), "task_id": task_id, "message": "Added to queue."},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS
    )


# --- Endpoints ---

@limiter.limit("5/minute")
@app.post("/generate_quiz")
def generate_quiz(request: Request, payload: QuizRequest):
    """Generate a quiz and return JSON."""
    topic, grade, num_questions = payload.topic, payload.grade, payload.num_questions
    if not (1 <= num_questions <= 20):
        raise HTTPException(status_code=400, detail="Number of questions must be between 1 and 20.")

    prompt = f"""
    Generate a quiz on {topic} for a grade {grade} student. Create {num_questions} questions.
    Return a JSON object with a key called 'questions', which contains a list of questions.
    Each question should have:
    - 'question' (the question text)
    - 'correct_answers' (a list of 3 possible correct answers)
    - 'wrong_response' (an explanation if the answer is wrong)
    
    Example response format:
    {{
        "questions": [
            {{
                "question": "What is the smallest unit of an element?",
                "correct_answers": ["atom", "an atom", "atoms"],
                "wrong_response": "Incorrect. The smallest unit of an element is an atom."
            }},
            {{
                "question": "How many electrons can the first shell of an atom hold?",
                "correct_answers": ["2", "two", "2 electrons"],
                "wrong_response": "Incorrect. The first shell of an atom can hold only 2 electrons."
            }}
        ]
    }}
    Only giving short answer questions and answers are only short answers.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        if "questions" not in result or not isinstance(result["questions"], list):
            raise ValueError("Invalid response format: Missing or incorrect 'questions' key.")
        return result
    except Exception as e:
        error_message = f"Quiz generation failed: {str(e)}"
        send_error_to_discord(error_message, payload.dict())
        raise HTTPException(status_code=500, detail="Unexpected error occurred. We've notified developers.")

@limiter.limit("5/minute")
@app.post("/generate_notes")
def generate_notes(request: Request, payload: NotesRequest):
    """Generate study notes and return JSON."""
    topic, grade = payload.topic, payload.grade
    prompt = f"""
    Create concise, easy-to-understand, and engaging study notes on {topic} for a grade {grade} student.
    Make it clear, engaging, and suitable for their level.
    Return JSON only:
    {{
        "notes": "Generated study notes here."
    }}
    Make them detailed and informative.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        error_message = f"Notes generation failed: {str(e)}"
        send_error_to_discord(error_message, payload.dict())
        raise HTTPException(status_code=500, detail="Unexpected error occurred. We've notified developers.")

# --- Background Queue Processing ---
# In production, use a robust system (e.g., Celery with Redis).
import asyncio

async def process_queue():
    while True:
        if request_queue:
            task_id = request_queue.popleft()
            if task_id in tasks:
                tasks[task_id]["status"] = "processing"
                # Insert real processing logic here (or trigger asynchronous processing)
                await asyncio.sleep(2)  # Simulated processing delay
                tasks[task_id]["status"] = "done"
                tasks[task_id]["result"] = "Processed successfully."
                # Optionally, send a summary log for this queued task
                send_error_to_discord(f"Queued task {task_id} processed successfully.", tasks[task_id])
        await asyncio.sleep(1)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(process_queue())

# --- Run the server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
