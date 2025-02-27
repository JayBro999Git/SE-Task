import sys
import time
import json
import random
import subprocess
import threading
import os

# trying to import rich for fancy printing, if it doesn't exist let's just install it automatically
try:
    from rich.console import Console
    from rich.markdown import Markdown
except ImportError:
    print("yo, installing 'rich' for cooler output... hang on")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
    from rich.console import Console
    from rich.markdown import Markdown

console = Console()

# also need requests
try:
    import requests
except ImportError:
    print("bruh, 'requests' wasn't installed, let me try installing it now")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        print("all good now!")
    except Exception as e:
        print("ugh... that didn't work. please run 'pip install requests' manually")
        sys.exit(1)

# this is our server url
API_BASE_URL = "https://se-backend-production.up.railway.app"

def meltdown():
    """
    okay so if everything is taking too long, let's clear the screen and freak out a bit,
    then just restart everything. it's basically a meltdown
    """
    os.system('cls' if os.name == 'nt' else 'clear')
    print("bro i’m about to crash this whole thing\n")
    time.sleep(0.03)
    for i in range(30):
        # print random nonsense for dramatic effect
        print(f"!!!!! random meltdown #@(#@(#%--- ??? {random.randint(1000,999999999999999999999)} ??? *** ")
        print(f"!!!!! random meltdown #@(#@(#%--- ??? {random.randint(1000,999999999999999999999999999)} ??? *** ")
        print(f"!!!!! random meltdown #@(#@(#%--- ??? {random.randint(1000,99999999999)} ??? *** ")
        print(f"!!!!! random meltdown #@(#@(#%--- ??? {random.randint(1000,999999999999999999999999)} ??? *** ")
        time.sleep(3)
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\nok let's chill. let's try again.")
    time.sleep(2)
    os.execl(sys.executable, sys.executable, *sys.argv)

def poll_queue(task_id):
    """
    so if the server says 'hey you're in the queue', we keep checking our position
    until it's done or something
    """
    print("\nso yeah, you're in the queue now. let's see what position you're in...")
    while True:
        try:
            resp = requests.get(f"{API_BASE_URL}/check_queue", params={"task_id": task_id}, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"ugh network problem while waiting in queue: {e}")
            print("will try again in 2 seconds...")
            time.sleep(2)
            continue

        if resp.status_code == 404:
            print("hmm, queue task not found. maybe try again later?")
            return None

        if resp.status_code != 200:
            print(f"some error happened while checking queue ({resp.status_code}): {resp.text}")
            print("waiting 2 seconds to try again...")
            time.sleep(2)
            continue

        data = resp.json()
        status_ = data.get("status")
        if status_ == "done":
            print("yay, your request is done!")
            return data.get("result")
        elif status_ == "processing":
            print("server is working on it. hang tight...")
        elif status_ == "queued":
            position = data.get("position")
            print(f"still in queue, looks like your position is: {position}")
        else:
            print("uh, got some unexpected status:", status_)

        time.sleep(2)

def handle_429(resp):
    """
    so if we get a 429 (too many requests), we might need to jump in the queue.
    let's parse whatever the server says and go from there
    """
    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("the server gave a 429 but didn't give us legit json. lame.")
        return None

    task_id = data.get("task_id")
    position = data.get("position")
    message = data.get("message", "you got rate-limited bro.")

    print("\n" + message)
    if task_id:
        print(f"your task id is: {task_id}")
        if position:
            print(f"you're currently at position: {position}")
        return poll_queue(task_id)
    else:
        print("no queue task id found. gotta try later i guess.")
        return None

def fake_loading_bar():
    """
    i made a fake loading bar 'cause i think it's funny.
    it just picks a random time between 15 and 20 seconds to do this bar.
    """
    total_duration = random.randint(15, 20)
    start_time = time.time()
    end_time = start_time + total_duration

    current_progress = 0
    while True:
        now = time.time()
        if now >= end_time:
            current_progress = 100
            print_bar(current_progress)
            break

        inc = random.randint(3, 10)
        current_progress = min(current_progress + inc, 100)
        print_bar(current_progress)
        time.sleep(random.uniform(0.2, 1.5))

        if current_progress >= 100:
            break

    return True

def print_bar(progress):
    """
    helper function to print out the loading bar
    """
    bar_length = 20
    filled_length = int(bar_length * progress // 100)
    bar = "#" * filled_length + "-" * (bar_length - filled_length)
    print(f"\r[{bar}] {progress}%", end="", flush=True)

def do_request_with_bar(request_func, *args, **kwargs):
    """
    so we do an actual request in a background thread,
    but show a fake loading bar in the main thread 'cause it looks cool and fools the consumer, plus the api can take different times for different people depending on wifi and stuff
    """
    resp_data = {"done": False, "result": None}

    def request_thread():
        r = request_func(*args, **kwargs)
        resp_data["done"] = True
        resp_data["result"] = r

    t = threading.Thread(target=request_thread, daemon=True)
    t.start()

    finished_bar = fake_loading_bar()
    print("\n")

    # if the server somehow responded quick, we already have data
    if resp_data["done"]:
        return resp_data["result"]

    print("okay so that bar was totally fake, but the request is still not done... why so slow??")

    # wait a little longer
    start_wait = time.time()
    while time.time() - start_wait < 4:
        if resp_data["done"]:
            print("finally! got something back. let's see what it is.")
            return resp_data["result"]
        time.sleep(0.2)

    # if still not done, meltdown
    if not resp_data["done"]:
        meltdown()

    return None


# quiz and notes calls

def request_quiz(topic, grade, num_questions):
    """
    sends a post request to /generate_quiz with the specified info.
    returns the quiz data or none if it fails. 
    """
    def actual_request():
        payload = {"topic": topic, "grade": grade, "num_questions": num_questions}
        try:
            resp = requests.post(f"{API_BASE_URL}/generate_quiz", json=payload, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"\nnetwork error: {e}")
            return None

        if resp.status_code == 429:
            return handle_429(resp)
        if resp.status_code != 200:
            print(f"ugh error {resp.status_code}: {resp.text}")
            return None

        try:
            return resp.json()
        except json.JSONDecodeError:
            print("server returned something that's not valid json. weird.")
            return None

    return do_request_with_bar(actual_request)

def request_notes(topic, grade):
    """
    sends a request to /generate_notes.
    returns the notes data or none if something fails
    """
    def actual_request():
        payload = {"topic": topic, "grade": grade}
        try:
            resp = requests.post(f"{API_BASE_URL}/generate_notes", json=payload, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"\nnetwork error: {e}")
            return None

        if resp.status_code == 429:
            return handle_429(resp)
        if resp.status_code != 200:
            print(f"server returned error {resp.status_code}: {resp.text}")
            return None

        try:
            data = resp.json()
            if isinstance(data, str):
                data = json.loads(data)
            return data
        except json.JSONDecodeError:
            print("ugh, got something that wasn't valid json.")
            return None

    return do_request_with_bar(actual_request)

def quiz_mode():
    """
    quiz mode: let's ask the user for a topic, grade, and # of questions,
    then fetch a quiz and let them answer
    """
    print("\n--- quiz mode, let's go ---")

    topic = input("so what's the topic (like 'atoms')? ").strip()
    if not topic:
        print("huh, that's not a valid topic. let's bail.")
        return

    try:
        grade = int(input("which grade (1-12)? "))
        if not (1 <= grade <= 12):
            print("that grade is outta range.")
            return
    except ValueError:
        print("that wasn't even a number. cmon.")
        return

    try:
        num_questions = int(input("how many questions (1-20)? "))
        if not (1 <= num_questions <= 20):
            print("that's not within 1-20. no.")
            return
    except ValueError:
        print("bro, not a valid number.")
        return

    quiz_data = request_quiz(topic, grade, num_questions)
    if quiz_data is None:
        print("couldn't get quiz data. sorry.")
        return

    if "questions" not in quiz_data or not isinstance(quiz_data["questions"], list):
        print("the server gave back something weird. maybe try again later.")
        return

    questions_list = quiz_data["questions"]

    import difflib
    score = 0
    for i, question_item in enumerate(questions_list, start=1):
        question = question_item.get("question", "no question")
        correct_answers = question_item.get("correct_answers", [])
        wrong_response = question_item.get("wrong_response", "uh no, that's not right")

        print(f"\nquestion {i}: {question}")
        user_answer = input("your answer: ").strip().lower()

        # do some fuzzy matching
        is_correct = False
        for ans in correct_answers:
            ratio = difflib.SequenceMatcher(None, user_answer, ans.lower()).ratio()
            if ratio > 0.8:
                is_correct = True
                break

        if is_correct:
            print("nice, that's correct!")
            score += 1
        else:
            print(f"nope... {wrong_response}")

    percentage = (score / num_questions) * 100
    print(f"\nyou got {score}/{num_questions} which is {percentage:.2f}%")

    if percentage >= 80:
        print("wow, you crushed it!")
    elif percentage >= 50:
        print("not bad, you did alright. keep it up!")
    else:
        print("dang, looks like you might wanna review more.")

def quick_notes_mode():
    """
    quick notes mode: user inputs a topic + grade, then we fetch some notes
    and display them in a nice markdown style
    """
    print("\n--- quick notes mode ---")

    topic = input("what's the topic you wanna learn about? ").strip()
    if not topic:
        print("yo that's not a valid topic. let's bail.")
        return

    try:
        grade = int(input("which grade (1-12)? "))
        if not (1 <= grade <= 12):
            print("that's not a valid grade number, sorry.")
            return
    except ValueError:
        print("bro, that wasn't a number. aborting.")
        return

    notes_data = request_notes(topic, grade)

    if not isinstance(notes_data, dict):
        print("weird, didn't get a dictionary from the server. might wanna retry later.")
        return

    notes_text = notes_data.get("notes")
    if not notes_text:
        print("no 'notes' in the response, can't show anything.")
        return

    if isinstance(notes_text, dict):
        notes_text = json.dumps(notes_text, indent=2)

    console.print("\n=== here are your notes ===", style="bold green")
    try:
        console.print(Markdown(notes_text))
    except TypeError:
        print("\nuh oh, i couldn't do markdown formatting. here's the raw text instead:\n")
        print(notes_text)

def main():
    print("welcome to this chill educational app!")
    print("we connect to our own backend server to handle rate limiting and requests to external applications.\n")

    while True:
        print("--- main menu ---")
        print("1) quiz mode")
        print("2) quick notes")
        print("3) exit")
        choice = input("what would you like (1-3)? ").strip()

        if choice == "1":
            quiz_mode()
        elif choice == "2":
            quick_notes_mode()
        elif choice == "3":
            print("alr cya!")
            break
        else:
            print("bro that's not 1, 2, or 3. try again.")

if __name__ == "__main__":
    main()
