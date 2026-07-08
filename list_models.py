from dotenv import load_dotenv
import os

load_dotenv()
os.environ.pop("GOOGLE_API_KEY", None)

from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Available models that support generateContent:\n")
for m in client.models.list():
    if "generateContent" in (m.supported_actions or []):
        print(f"  {m.name}")