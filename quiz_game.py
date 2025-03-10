# This code runs the newest version of main.py
print("Hey! Trying to get main.py...")
try:
    import main  # try to import the main file
    print("Yay! Got main.py successfully!")
except ImportError as e:
    print("Uh oh! Couldn't find main.py... Make sure you downloaded it!")
    print(f"Here's what went wrong: {e}")
    sys.exit(1)  # exit the program if we can't find main.py

import os
import sys
import requests
import subprocess

# Check if we have the packages we need 
print("Let me check if we have everything we need...")
try:
    from rich.console import Console  # this makes our text look cool!
    print("Cool, we already have the rich package!")
except ImportError:
    print("Oops, we need to install the rich package...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
    from rich.console import Console
    print("Sweet! Just installed the rich package!")

console = Console()  # this lets us make colorful text!

def get_newest_main():
    """
    This function gets the newest version of main.py from GitHub
    (It's like downloading the latest update!)
    """
    print("\nOk, let's try to get the newest main.py...")
    try:
        # Try to download main.py from GitHub
        print("Getting the file from GitHub...")
        response = requests.get("https://raw.githubusercontent.com/JayBro999Git/SE-Task/main/main.py")
        
        print(f"GitHub said: {response.status_code}")  # 200 means it worked!
        
        if response.status_code == 200:
            # Save the new main.py file
            print("Saving the new file...")
            with open("main.py", "w") as f:
                f.write(response.text)
            print("Awesome! Saved the file!")
            
            # Clear the screen to make it look nice
            print("Cleaning up the screen...")
            os.system('cls' if os.name == 'nt' else 'clear')
            console.print("[green]Successfully got the latest version of the quiz game![/green]")
        else:
            console.print(f"[red]Oops! Couldn't get main.py (Error code: {response.status_code})[/red]")
            print("Here's what GitHub said:", response.text)
    except Exception as e:
        console.print(f"[red]Something went wrong getting main.py: {str(e)}[/red]")
        print(f"The error was a: {type(e).__name__}")

# This is where the program starts!
if __name__ == "__main__":
    print("\n=== Starting the Quiz Game Updater! ===\n")
    get_newest_main()  # run our function to get the newest version
