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

# my api key secured in the backend so no one can access it and abuse it
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("missing api key bruh")

client = openai.OpenAI(api_key=openai_api_key)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")

# fast api
app = FastAPI(title="Educational App Server")

# IP-based rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# global rate limit configuration
GLOBAL_REQUEST_LIMIT = 7  # 20 requests max per 60s globally
TIME_WINDOW = 60  # 60 seconds
global_requests: Deque[float] = deque()

# handling server overload
request_queue: Deque[str] = deque()
tasks: Dict[str, Dict] = {}


# structure for request body
class QuizRequest(BaseModel):
    topic: str
    grade: int
    num_questions: int


class NotesRequest(BaseModel):
    topic: str
    grade: int


# error logging to an external source for investigation
def send_error_to_discord(error_message: str, request_data: dict = None):
    """send error details to a discord webhook"""
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


# global rate limit middleware
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


# quiz generation
@limiter.limit("5/minute")
@app.post("/generate_quiz")
def generate_quiz(request: Request, payload: QuizRequest):
    """this will generate a quiz and return in json format"""
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
    Only giving short answer questions and answers are only short answers. If you are unsure of what the user is saying, have your best guess of what the user is talking about.  Never return anything about not knowing that they mean. Always return something. Make the questions creative and engaging so the user feels good about what they are doing and not find it boring or not engaging.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}  
        )
        
        # ensure jason parsing
        result = json.loads(response.choices[0].message.content)

        # make sure 'questions' is a list
        if "questions" not in result or not isinstance(result["questions"], list):
            raise ValueError("Invalid response format: Missing or incorrect 'questions' key.")

        return result

    except Exception as e:
        error_message = f"Quiz generation failed: {str(e)}"
        send_error_to_discord(error_message, payload.dict())
        raise HTTPException(status_code=500, detail="Unexpected error occurred. We've notified developers.")



# quiz generation
@limiter.limit("5/minute")
@app.post("/generate_notes")
def generate_notes(request: Request, payload: NotesRequest):
    """generate quick study notes and ensure json return"""
    topic, grade = payload.topic, payload.grade

    prompt = f"""
    Create concise, easy-to-understand, and engaging study notes on {topic} for a grade {grade} student.
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
            response_format={"type": "json_object"} 
        )
        return response.choices[0].message.content
    except Exception as e:
        error_message = f"Notes generation failed: {str(e)}"
        send_error_to_discord(error_message, payload.dict())
        raise HTTPException(status_code=500, detail="Unexpected error occurred. We've notified developers.")

# run
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
