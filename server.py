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

# ================================
#   ENV / API KEY SETUP
# ================================
# In production, set OPENAI_API_KEY as an environment variable on your server.
openai.api_key = os.getenv("OPENAI_API_KEY", "sk-REPLACE_WITH_REAL_KEY")


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
GLOBAL_REQUEST_LIMIT = 20  # e.g. 20 requests max in 60s globally
TIME_WINDOW = 60           # 60 seconds
global_requests: Deque[float] = deque()

# ================================
#   QUEUE TO HANDLE OVERFLOW
# ================================
# If global limit is reached, we queue requests in memory
request_queue: Deque[str] = deque()  # storing request IDs

# We'll store the 'task' details in a dictionary
# key: request_id (UUID), value: request + status
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

    # Remove old requests from the global_requests deque
    while global_requests and current_time - global_requests[0] > TIME_WINDOW:
        global_requests.popleft()

    # If under global limit, proceed immediately
    if len(global_requests) < GLOBAL_REQUEST_LIMIT:
        global_requests.append(current_time)
        response = await call_next(request)
        return response

    # Otherwise, we're at capacity => place user in queue
    # We'll create a 'task_id' to represent the queued request
    task_id = str(uuid.uuid4())
    request_queue.append(task_id)

    # We store the task details so we can process it later
    # status: "queued" | "processing" | "done"
    tasks[task_id] = {
        "status": "queued",
        "created_at": current_time,
        "request_path": str(request.url.path)
    }

    # Return a 429 with queue info. (Alternatively, you could return 200 and instruct the client to poll.)
    content = {
        "status": "queued",
        "position": len(request_queue),
        "task_id": task_id,
        "message": "Global limit reached. You have been added to the queue."
    }
    return JSONResponseQueue(content, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


# We'll define a custom JSONResponseQueue to ensure a valid JSON response:
from fastapi.responses import JSONResponse
class JSONResponseQueue(JSONResponse):
    media_type = "application/json"


# ================================
#   BACKGROUND PROCESS (SIMPLIFIED)
# ================================
# In real life, you'd have a background worker to process queued requests
# once capacity frees up, store results, etc.
# For demonstration, let's show a naive approach: 
#   We'll just expose an endpoint for the client to poll /check_queue
#   If the request is at the front of the queue and capacity is available, 
#   we process it right then.

def process_queued_task(task_id: str):
    """Pretend to process the queued request.
       For simplicity, let's just set its status to 'done' after 'global_requests' frees up."""
    if task_id not in tasks:
        return

    tasks[task_id]["status"] = "processing"
    # do some 'fake' processing or wait for capacity
    time.sleep(1)  # simulate processing
    tasks[task_id]["status"] = "done"
    tasks[task_id]["result"] = {
        "fakeData": "Your request was processed once capacity freed up!"
    }


@app.get("/check_queue")
def check_queue(task_id: str):
    """Client polls this endpoint to see if their queued request is done or to see their position."""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    status_ = tasks[task_id]["status"]
    if status_ == "done":
        # Return the final result
        return {
            "status": "done",
            "result": tasks[task_id]["result"]
        }
    elif status_ == "processing":
        # It's not done yet
        return {
            "status": "processing",
            "message": "Your request is being processed. Please wait."
        }
    elif status_ == "queued":
        # Return queue position
        position = 0
        for i, tid in enumerate(request_queue):
            if tid == task_id:
                position = i + 1
                break

        # Check if capacity is available => process the request
        current_time = time.time()
        # Remove old items from global_requests
        while global_requests and current_time - global_requests[0] > TIME_WINDOW:
            global_requests.popleft()

        if len(global_requests) < GLOBAL_REQUEST_LIMIT and request_queue[0] == task_id:
            # We can process it now
            global_requests.append(current_time)
            request_queue.popleft()
            process_queued_task(task_id)  # changes status to done
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
def generate_quiz(payload: QuizRequest):
    """
    Generates quiz JSON via OpenAI if capacity is available (or user is not queued).
    """
    topic = payload.topic
    grade = payload.grade
    num_questions = payload.num_questions

    if num_questions < 1 or num_questions > 20:
        raise HTTPException(
            status_code=400,
            detail="Number of questions must be between 1 and 20."
        )

    prompt = f"""
    Generate a quiz on {topic} for a grade {grade} student. Create {num_questions} questions.
    Return only JSON with this format for each question:
    {{
        "question": "The quiz question",
        "correct_answers": ["variation1", "variation2", "variation3"],
        "wrong_response": "Explanation why a wrong answer is incorrect, including the correct answer."
    }}
    Ensure the wrong_response is slightly formal and clearly explains the correct answer.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@limiter.limit("5/minute")  
@app.post("/generate_notes")
def generate_notes(payload: NotesRequest):
    """
    Generates quick study notes JSON via OpenAI if capacity is available.
    """
    topic = payload.topic
    grade = payload.grade

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
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================================
#   RUN WITH UVICORN LOCALLY
# ================================
# In Vercel, you'll define an entrypoint, or use a serverless config.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
