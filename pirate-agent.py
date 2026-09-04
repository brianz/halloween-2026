import time

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    DefaultAudioInterface,
)

# from gpiozero import Button

# Initialize ElevenLabs Client
client = ElevenLabs(api_key="ELEVEN_LABS_API_KEY")
AGENT_ID = "ELEVEN_LABS_AGENT_ID"

# Setup the physical button on GPIO Pin 2
# (Assumes button is wired between GPIO 2 and GND)
# button = Button(2, pull_up=True)

conversation = None


def start_agent_session():
    global conversation
    print("Button pressed! Starting session...")

    # Initialize the conversation session
    conversation = Conversation(
        client,
        AGENT_ID,
        requires_auth=True,
        audio_interface=DefaultAudioInterface(),
        callback_agent_response=lambda resp: print(f"Agent: {resp}"),
        callback_user_transcript=lambda text: print(f"User: {text}"),
    )

    conversation.start_session()


def stop_agent_session():
    global conversation
    if conversation:
        print("Stopping session...")
        conversation.end_session()
        conversation = None


# Assign the physical button actions
# button.when_pressed = start_agent_session
# button.when_released = stop_agent_session

print("Ready! Press and hold the button to talk to the agent...")
# Keep the main thread alive
while True:
    time.sleep(1)
