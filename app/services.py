import json
import os
import re

from app.schemas import Recurrence, TaskCreate


def parse_task_text(text: str) -> TaskCreate:
    \"\"\"Deterministic fallback that only infers recurrence explicitly stated.\"\"\"
    clean = re.sub(r\"\\s+\", \" \", text).strip()
    recurrence = None
    frequency = None
    if re.search(r\"\\b(daily|every day|each day)\\b\", clean, re.IGNORECASE):
        frequency = \"daily\"
    elif re.search(r\"\\b(weekly|every week|each week|every (monday|tuesday|wednesday|thursday|friday|saturday|sunday))\\b\", clean, re.IGNORECASE):
        frequency = \"weekly\"
    elif re.search(r\"\\b(monthly|every month|each month)\\b\", clean, re.IGNORECASE):
        frequency = \"monthly\"
    if frequency:
        recurrence = Recurrence(frequency=frequency)
    title = re.sub(r\"^(please\\s+)?(remind me to|remember to|schedule|create a task to|add a task to)\\s+\", \"\", clean, flags=re.IGNORECASE)
    title = re.sub(r\"\\s+(every|each)\\s+(day|week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday).*?$\", \"\", title, flags=re.IGNORECASE)
    title = title.strip(\" .,!?\") or clean
    return TaskCreate(title=title[:200], recurrence=recurrence)


def _openai_client():
    key = os.getenv(\"OPENAI_API_KEY\")
    if not key:
        return None
    from openai import OpenAI

    return OpenAI(api_key=key)


def generate_task(text: str) -> TaskCreate:
    client = _openai_client()
    if client is None:
        return parse_task_text(text)
    response = client.beta.chat.completions.parse(
        model=os.getenv(\"OPENAI_MODEL\", \"gpt-4o-mini\"),
        messages=[
            {\"role\": \"system\", \"content\": \"Convert the request to one concise task. Only infer recurrence explicitly stated. Do not invent dates.\"},
            {\"role\": \"user\", \"content\": text},
        ],
        response_format=TaskCreate,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError(\"The model did not return a valid task\")
    return parsed


def breakdown_task(text: str) -> list[str]:
    client = _openai_client()
    if client is not None:
        response = client.chat.completions.create(
            model=os.getenv(\"OPENAI_MODEL\", \"gpt-4o-mini\"),
            messages=[
                {\"role\": \"system\", \"content\": \"Break a task into 3-7 actionable subtasks. Return JSON only: {\\\"subtasks\\\":[\\\"...\\\"]}.\"},
                {\"role\": \"user\", \"content\": text},
            ],
            response_format={\"type\": \"json_object\"},
        )
        payload = json.loads(response.choices[0].message.content or \"{}\")
        subtasks = payload.get(\"subtasks\")
        if isinstance(subtasks, list) and 1 <= len(subtasks) <= 10 and all(isinstance(s, str) and s.strip() for s in subtasks):
            return [s.strip()[:200] for s in subtasks]
        raise ValueError(\"The model returned an invalid subtask list\")
    return [
        f\"Define the outcome and requirements for: {text[:160]}\",
        f\"Gather the materials or information needed for: {text[:160]}\",
        f\"Complete the main work for: {text[:160]}\",
        \"Review the result and confirm the task is complete\",
    ]
