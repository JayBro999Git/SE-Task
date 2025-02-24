import os
import time
import uuid
import openai
import json
import requests
from typing import Dict, Optional, Deque
from collections import deque
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

# ================================
#   ENV / API KEY SETUP
# ================================
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("Missing OpenAI API Key!")

client = openai.OpenAI(api_key=openai_api_key)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")

# ================================
#   FASTAPI + SLOWAPI INIT
# ================================
app = FastAPI(title="Educational Server with Queue & Rate Limits")

# IP-based rate limiter (e.g., 10 requests per minute per IP)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# ================================
#   GLOBAL RATE LIMIT SETTINGS
# ================================
GLOBAL_REQUEST_LIMIT = 20  # 20 requests max per 60s globally
TIME_WINDOW = 60  # 60 seconds
global_requests: Deque[float] = deque()

# ================================
#   QUEUE TO HANDLE OVERFLOW
# ================================
request_queue: Deque[str] = deque()
tasks: Dict[str, Dict] = {}


# ================================
#   MODELS FOR REQUEST BODY
# ================================
class QuizRequest(BaseModel):
    topic: str
    grade: int
    num_questions: int


class NotesRequest(BaseModel):
    topic: str
    grade: int


# ================================
#   ERROR HANDLING - DISCORD WEBHOOK
# ================================
def send_error_to_discord(error_message: str, request_data: dict = None):
    """Send error details to a Discord webhook for debugging."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    embed = {
        "username": "FastAPI Error Logger",
        "embeds": [
            {
                "title": "🚨 Unexpected Error Occurred!",
                "description": f"**Time:** {timestamp}\n**Error:** {error_message}",
                "color": 15158332,  # Red color
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


# ================================
#   GLOBAL RATE LIMIT MIDDLEWARE
# ================================
@app.middleware("http")
async def global_rate_limit_middleware(request: Request, call_next):
    """Handles global rate limit & queues users when limit is reached."""
    current_time = time.time()

    while global_requests and current_time - global_requests[0] > TIME_WINDOW:
        global_requests.popleft()

    if len(global_requests) < GLOBAL_REQUEST_LIMIT:
        global_requests.append(current_time)
        return await call_next(request)

    task_id = str(uuid.uuid4())
    request_queue.append(task_id)
    tasks[task_id] = {"status": "queued", "created_at": current_time, "request_path": str(request.url.path)}

    return JSONResponse(
        {"status": "queued", "position": len(request_queue), "task_id": task_id, "message": "Added to queue."},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS
    )


# ================================
#   QUIZ GENERATION
# ================================
@limiter.limit("5/minute")
@app.post("/generate_quiz")
def generate_quiz(request: Request, payload: QuizRequest):
    """Generates a quiz JSON via OpenAI."""
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
            response_format={"type": "json_object"}  # ✅ Correct format
        )
        
        # Ensure JSON parsing
        result = json.loads(response.choices[0].message.content)

        # Validate that "questions" key exists and is a list
        if "questions" not in result or not isinstance(result["questions"], list):
            raise ValueError("Invalid response format: Missing or incorrect 'questions' key.")

        return result  # ✅ Return a valid JSON object with a "questions" list

    except Exception as e:
        error_message = f"Quiz generation failed: {str(e)}"
        send_error_to_discord(error_message, payload.dict())
        raise HTTPException(status_code=500, detail="Unexpected error occurred. We've notified developers.")



# ================================
#   NOTES GENERATION
# ================================
@limiter.limit("5/minute")
@app.post("/generate_notes")
def generate_notes(request: Request, payload: NotesRequest):
    """Generates quick study notes JSON via OpenAI."""
    topic, grade = payload.topic, payload.grade

    prompt = f"""
    Create concise, easy-to-understand study notes on {topic} for a grade {grade} student.
    Make it clear, engaging, and suitable for their level.
    Return JSON only:
    {{
        "notes": "Generated study notes here."
    }}
    Make them detailed and informative and engaging and easy to understand and read and using advanced methods and techniques used by professionals to make them really engaging and the user learns lots from them.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}  # ✅ Correct format
        )
        return response.choices[0].message.content
    except Exception as e:
        error_message = f"Notes generation failed: {str(e)}"
        send_error_to_discord(error_message, payload.dict())
        raise HTTPException(status_code=500, detail="Unexpected error occurred. We've notified developers.")


# ================================
#   RUN WITH UVICORN LOCALLY
# ================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
