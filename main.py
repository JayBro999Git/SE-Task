import sys
import time
import json
import random
import subprocess
import threading
import os

# trying to install the stuff we need
try:
    from rich.console import Console
    from rich.markdown import Markdown
except ImportError:
    print("oops, installing 'rich' for cooler output... wait a sec")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
    from rich.console import Console
    from rich.markdown import Markdown

console = Console()

# also need requests
try:
    import requests
except ImportError:
    print("oh wait, 'requests' isn't installed, let me install it")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        print("cool, it works now!")
    except Exception as e:
        print("uh oh... that didn't work. can you run 'pip install requests' yourself?")
        sys.exit(1)

# our server url
API_BASE_URL = "https://se-backend-production.up.railway.app"

def restart_program():
    # this just restarts the program when something goes wrong
    os.execl(sys.executable, sys.executable, *sys.argv)

def show_fake_loading():
    """
    this makes a fake loading bar because it looks cool
    """
    how_long = random.randint(15, 20)
    start_time = time.time()
    end_time = start_time + how_long

    progress = 0
    while True:
        now = time.time()
        if now >= end_time:
            progress = 100
            draw_progress_bar(progress)
            break

        progress = progress + random.randint(3, 10)
        if progress > 100:
            progress = 100
        draw_progress_bar(progress)
        time.sleep(random.uniform(0.2, 1.5))

        if progress >= 100:
            break

    return True

def draw_progress_bar(progress):
    """
    this draws the loading bar
    """
    bar_length = 20
    filled_length = int(bar_length * progress // 100)
    bar = "#" * filled_length + "-" * (bar_length - filled_length)
    print(f"\r[{bar}] {progress}%", end="", flush=True)

def do_request_with_loading(request_function, *args, **kwargs):
    """
    this does the actual request but shows a loading bar
    """
    result_data = {"done": False, "result": None}

    def request_thread():
        r = request_function(*args, **kwargs)
        result_data["done"] = True
        result_data["result"] = r

    t = threading.Thread(target=request_thread, daemon=True)
    t.start()

    finished_bar = show_fake_loading()
    print("\n")

    # check if we have data
    if result_data["done"]:
        return result_data["result"]

    print("oops the loading bar finished but the request is still going... weird")

    # wait a bit longer
    start_wait = time.time()
    while time.time() - start_wait < 4:
        if result_data["done"]:
            print("finally got something back!")
            return result_data["result"]
        time.sleep(0.2)

    # if still not done, restart
    if not result_data["done"]:
        restart_program()

    return None


# quiz and notes functions

def get_quiz(topic, grade, num_questions):
    """
    sends request to get a quiz
    """
    def actual_request():
        data = {"topic": topic, "grade": grade, "num_questions": num_questions}
        try:
            response = requests.post(f"{API_BASE_URL}/generate_quiz", json=data, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"\noops, network error: {e}")
            return None

        if response.status_code != 200:
            print(f"error {response.status_code}: {response.text}")
            return None

        try:
            return response.json()
        except json.JSONDecodeError:
            print("got something weird from the server")
            return None

    return do_request_with_loading(actual_request)

def get_notes(topic, grade):
    """
    sends request to get notes
    """
    def actual_request():
        data = {"topic": topic, "grade": grade}
        try:
            response = requests.post(f"{API_BASE_URL}/generate_notes", json=data, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"\noops, network error: {e}")
            return None

        if response.status_code != 200:
            print(f"error {response.status_code}: {response.text}")
            return None

        try:
            data = response.json()
            if isinstance(data, str):
                data = json.loads(data)
            return data
        except json.JSONDecodeError:
            print("got something weird from the server")
            return None

    return do_request_with_loading(actual_request)

def do_quiz():
    """
    this lets you take a quiz
    """
    print("\n--- QUIZ TIME! ---")

    topic = input("what topic do you want to learn about? ").strip()
    if not topic:
        print("you didn't type anything. can't continue.")
        return

    try:
        grade = int(input("what grade are you in (1-12)? "))
        if not (1 <= grade <= 12):
            print("that's not a grade between 1 and 12")
            return
    except ValueError:
        print("that's not a number")
        return

    try:
        num_questions = int(input("how many questions do you want (1-20)? "))
        if not (1 <= num_questions <= 20):
            print("that's not between 1 and 20")
            return
    except ValueError:
        print("that's not a number")
        return

    quiz_data = get_quiz(topic, grade, num_questions)
    if quiz_data is None:
        print("couldn't get a quiz. sorry.")
        return

    if "questions" not in quiz_data or not isinstance(quiz_data["questions"], list):
        print("got something weird from the server. try again?")
        return

    questions_list = quiz_data["questions"]

    import difflib
    score = 0
    for i, question_item in enumerate(questions_list, start=1):
        question = question_item.get("question", "no question")
        correct_answers = question_item.get("correct_answers", [])
        wrong_response = question_item.get("wrong_response", "that's not right")

        print(f"\nquestion {i}: {question}")
        user_answer = input("your answer: ").strip().lower()

        # check if answer is close enough
        is_correct = False
        for ans in correct_answers:
            ratio = difflib.SequenceMatcher(None, user_answer, ans.lower()).ratio()
            if ratio > 0.8:
                is_correct = True
                break

        if is_correct:
            print("that's right!")
            score += 1
        else:
            print(f"nope... {wrong_response}")

    percentage = (score / num_questions) * 100
    print(f"\nyou got {score}/{num_questions} which is {percentage:.2f}%")

    if percentage >= 80:
        print("awesome job!")
    elif percentage >= 50:
        print("pretty good, keep practicing!")
    else:
        print("might need to study more...")

def show_notes():
    """
    this shows notes on a topic
    """
    print("\n--- STUDY NOTES ---")

    topic = input("what topic do you want notes on? ").strip()
    if not topic:
        print("you didn't type anything")
        return

    try:
        grade = int(input("what grade are you in (1-12)? "))
        if not (1 <= grade <= 12):
            print("that's not between 1 and 12")
            return
    except ValueError:
        print("that's not a number")
        return

    notes_data = get_notes(topic, grade)

    if not isinstance(notes_data, dict):
        print("got something weird from the server. try again?")
        return

    notes_text = notes_data.get("notes")
    if not notes_text:
        print("no notes in the response")
        return

    if isinstance(notes_text, dict):
        notes_text = json.dumps(notes_text, indent=2)

    console.print("\n=== YOUR NOTES ===", style="bold green")
    try:
        console.print(Markdown(notes_text))
    except TypeError:
        print("\ncan't show fancy formatting. here's the text:\n")
        print(notes_text)

def main():
    print("welcome to my cool education app!")
    print("this connects to a server to get educational stuff\n")

    while True:
        print("--- MENU ---")
        print("1) take a quiz")
        print("2) get study notes")
        print("3) exit")
        choice = input("what do you want to do (1-3)? ").strip()

        if choice == "1":
            do_quiz()
        elif choice == "2":
            show_notes()
        elif choice == "3":
            print("bye!")
            break
        else:
            print("that's not 1, 2, or 3. try again.")

if __name__ == "__main__":
    main()
