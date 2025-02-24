import os
import time
import uuid
import openai
import json
from typing import Dict, Optional, Deque
from collections import deque

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
openai.api_key = os.getenv("OPENAI_API_KEY")


# ================================
#   FASTAPI + SLOWAPI INIT
# ================================
app = FastAPI(title="Educational Server with Queues & Rate Limits")

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
#   GLOBAL RATE LIMIT MIDDLEWARE
# ================================
@app.middleware("http")
async def global_rate_limit_middleware(request: Request, call_next):
    """Global limit: only X requests can proceed in last 60 seconds.
       If limit is reached, the request is placed in the queue."""
    current_time = time.time()

    # Remove old requests outside the time window
    while global_requests and current_time - global_requests[0] > TIME_WINDOW:
        global_requests.popleft()

    # If under global limit, proceed immediately
    if len(global_requests) < GLOBAL_REQUEST_LIMIT:
        global_requests.append(current_time)
        response = await call_next(request)
        return response

    # Otherwise, we're at capacity => place user in queue
    task_id = str(uuid.uuid4())
    request_queue.append(task_id)
    tasks[task_id] = {
        "status": "queued",
        "created_at": current_time,
        "request_path": str(request.url.path)
    }

    return JSONResponse(
        {
            "status": "queued",
            "position": len(request_queue),
            "task_id": task_id,
            "message": "Global limit reached. You have been added to the queue."
        },
        status_code=status.HTTP_429_TOO_MANY_REQUESTS
    )


# ================================
#   BACKGROUND PROCESS (SIMPLIFIED)
# ================================
def process_queued_task(task_id: str):
    """Simulate processing of a queued request."""
    if task_id not in tasks:
        return

    tasks[task_id]["status"] = "processing"
    time.sleep(1)  # simulate processing
    tasks[task_id]["status"] = "done"
    tasks[task_id]["result"] = {
        "message": "Your request was processed once capacity freed up!"
    }


@app.get("/check_queue")
def check_queue(task_id: str):
    """Client polls this endpoint to see their queue status."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    status_ = tasks[task_id]["status"]
    if status_ == "done":
        return {"status": "done", "result": tasks[task_id]["result"]}

    elif status_ == "processing":
        return {"status": "processing", "message": "Your request is being processed. Please wait."}

    elif status_ == "queued":
        if task_id in request_queue:
            position = list(request_queue).index(task_id) + 1
        else:
            position = None  # If for some reason, it's missing

        # Check if capacity is available => process the request
        current_time = time.time()
        while global_requests and current_time - global_requests[0] > TIME_WINDOW:
            global_requests.popleft()

        if len(global_requests) < GLOBAL_REQUEST_LIMIT and request_queue and request_queue[0] == task_id:
            global_requests.append(current_time)
            request_queue.popleft()
            process_queued_task(task_id)
            return {"status": "done", "result": tasks[task_id]["result"]}

        return {
            "status": "queued",
            "position": position,
            "message": "Still waiting for capacity..."
        }


# ================================
#   IP-BASED RATE LIMITS (SlowAPI)
# ================================
@limiter.limit("5/minute")
@app.post("/generate_quiz")
def generate_quiz(request: Request, payload: QuizRequest):
    """Generates quiz JSON via OpenAI if capacity is available."""
    topic, grade, num_questions = payload.topic, payload.grade, payload.num_questions

    if not (1 <= num_questions <= 20):
        raise HTTPException(
            status_code=400,
            detail="Number of questions must be between 1 and 20."
        )

    prompt = f"""
    Generate a quiz on {topic} for a grade {grade} student. Create {num_questions} questions.
    Return only JSON with this format:
    {{
        "question": "Quiz question",
        "correct_answers": ["variation1", "variation2", "variation3"],
        "wrong_response": "Explanation why a wrong answer is incorrect, including the correct answer."
    }}
    """

    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="chatgpt-4o-latest",
            messages=[{"role": "user", "content": prompt}]
        )

        response_json = json.loads(response["choices"][0]["message"]["content"])
        return response_json
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@limiter.limit("5/minute")
@app.post("/generate_notes")
def generate_notes(request: Request, payload: NotesRequest):
    """Generates quick study notes JSON via OpenAI."""
    topic, grade = payload.topic, payload.grade

    prompt = f"""
    Create concise, easy-to-understand study notes on {topic} for a grade {grade} student.
    Make it clear, engaging, and suitable for their level.
    Return only JSON with this format:
    {{
        "notes": "The study notes here."
    }}
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        response_json = json.loads(response["choices"][0]["message"]["content"])
        return response_json
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================================
#   RUN WITH UVICORN LOCALLY
# ================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
