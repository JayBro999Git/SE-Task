import os
import time
import openai
import json
import requests
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, status
from pydantic import BaseModel
from fastapi.responses import JSONResponse

# get the API key
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("missing api key! please set OPENAI_API_KEY")

client = openai.OpenAI(api_key=openai_api_key)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")

app = FastAPI(title="Educational App Server")

# function to send errors to Discord
def send_error_to_discord(error_message: str, request_data: dict = None):
    """Send error details to Discord for logging."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    embed = {
        "username": "FastAPI Error Logger",
        "embeds": [
            {
                "title": "🚨 Error!",
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
        print(f"Couldn't send to Discord: {e}")

# data models
class QuizRequest(BaseModel):
    topic: str
    grade: int
    num_questions: int

class NotesRequest(BaseModel):
    topic: str
    grade: int

# API endpoints
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
    Only provide 1 - 2 word answer questions and not long answers as there can be many variants of answer's provided by the user.
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

# run the server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
