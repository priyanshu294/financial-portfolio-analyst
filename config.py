import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT")

# Initialize the Groq LLM for reasoning and sentiment analysis
llm = ChatGroq(
    temperature=0,
    model_name="openai/gpt-oss-120b", 
    groq_api_key=GROQ_API_KEY
)
