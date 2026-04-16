# Two Bugs That Silently Break Your FastAPI App — And How I Found Them

*A real-world story from building MyVastu, a Vastu Shastra floor plan analyzer*

---

I'm building a side project called **MyVastu** — a web app where you upload a floor plan image, mark which direction is North, and get an AI-powered Vastu Shastra compliance score out of 100. The backend is FastAPI, the AI layer calls Google's Gemini vision API, and the frontend is Streamlit.

The app worked. Users could upload a floor plan, click Analyze, and get results back. Tests passed. No crashes.

But hiding inside two lines of code were bugs that would have made the app fall over under real load — and neither of them threw an error.

This post is about what those bugs were, why they're easy to miss, and how to fix them. Both lessons apply to any FastAPI app that makes external API calls.

---

## A quick primer: how FastAPI handles requests

Before we look at the bugs, you need to understand one thing about how FastAPI works.

FastAPI is an **async** web framework. This means it can handle many requests at the same time without creating a new thread for each one. It does this using something called an **event loop** — think of it as a single highly-efficient coordinator that juggles many tasks by switching between them whenever one is waiting for something (like an API response or a database query).

The key word is *waiting*. The event loop can only juggle tasks if each task **yields control** while it waits. In Python, you signal this with `await`:

```python
# This yields control — the event loop can handle other requests while waiting
response = await some_async_function()
```

If a task does something slow **without** yielding control, the entire event loop freezes. No other requests can be handled. Everyone waits. This is called **blocking the event loop**, and it's one of the most common performance bugs in async Python apps.

---

## Bug #1: The synchronous call hiding inside async code

Here's the service function that calls Gemini:

```python
async def analyze_floor_plan(...):
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(model_name=gemini_model)
    image = Image.open(io.BytesIO(image_bytes))
    prompt_text = _build_analysis_prompt(north_direction, rules)

    # This is the problem
    response = model.generate_content(
        [image, prompt_text],
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=0.2,
        ),
    )
```

Look at `model.generate_content(...)`. No `await`. It's a **synchronous call** — it sits there and waits for Gemini to respond, blocking everything.

Gemini takes roughly 15–30 seconds to analyze a floor plan image. During those 15–30 seconds, the FastAPI event loop is completely frozen. If two users submit their floor plans at the same time, the second user doesn't just wait for their own Gemini call — they wait for the first user's call to finish first, *then* their call starts. Three users? They queue up one by one.

The function is marked `async def`, which looks correct. But `async def` alone doesn't make a function non-blocking. What matters is whether the slow work inside it yields control with `await`. If it doesn't, you've written a synchronous function wearing an async costume.

### Why is Gemini's SDK synchronous?

Google's `google-generativeai` Python SDK doesn't have native async support. Its `generate_content()` method is a regular blocking function. This is common with third-party SDKs — many of them were built before async Python became mainstream, or they just haven't added async support yet.

### The fix: `asyncio.to_thread()`

Python's standard library has a clean solution: `asyncio.to_thread()`. It takes a synchronous function and runs it in a **thread pool** — a separate pool of worker threads that run alongside the event loop. The event loop doesn't freeze; it just fires off the work to a thread and moves on to other requests. When the thread finishes, the result comes back.

```python
# Before
response = model.generate_content(
    [image, prompt_text],
    generation_config=genai.types.GenerationConfig(
        max_output_tokens=max_tokens,
        temperature=0.2,
    ),
)

# After
response = await asyncio.to_thread(
    model.generate_content,
    [image, prompt_text],
    generation_config=genai.types.GenerationConfig(
        max_output_tokens=max_tokens,
        temperature=0.2,
    ),
)
```

Two changes: add `await`, and wrap the function call with `asyncio.to_thread()`. Now the event loop is free to handle other requests while Gemini processes the image in a background thread.

### The mental model

Think of the event loop as a restaurant manager. They can coordinate many tables at once — taking orders, checking on food, bringing bills — as long as they're not stuck doing one thing with their hands full.

A synchronous Gemini call is like the manager personally going into the kitchen to cook a dish. Everyone else has to wait until the dish is done. `asyncio.to_thread()` is like handing the cooking off to a chef (a background thread), so the manager can keep running the floor.

---

## Bug #2: Mutating global state on every request

Here's the other problem, also in the same function:

```python
async def analyze_floor_plan(..., gemini_api_key: str, ...):
    # This runs on EVERY request
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(model_name=gemini_model)
    ...
```

`genai.configure(api_key=...)` doesn't configure a local object. It sets a **global variable** inside the `google-generativeai` SDK module. Every time it's called, it writes to shared memory that the entire application can see.

On its own, that's just wasteful — the API key never changes, so calling `configure()` on every request is redundant.

But combined with the `asyncio.to_thread()` fix from Bug #1, it becomes a **race condition**. Now multiple requests can truly run concurrently in threads. Two threads can call `genai.configure()` at the same moment, both writing to the same global variable simultaneously. In Python, this kind of concurrent write to shared state is unpredictable — threads can interleave in ways that corrupt the value or cause subtle errors that are extremely hard to reproduce and debug.

### Why was it written this way?

This is an honest mistake that comes from misunderstanding FastAPI's dependency injection system.

The API key lives in a `Settings` object, which is loaded from a `.env` file using Pydantic's `BaseSettings`. In FastAPI, you typically access `Settings` inside a route handler using `Depends()`:

```python
async def analyze_floor_plan(
    ...,
    settings: Settings = Depends(get_settings),
):
    genai.configure(api_key=settings.gemini_api_key)
```

The natural assumption is: "I can only get `Settings` through `Depends()`, and `Depends()` only runs when a request comes in. So I have to configure Gemini inside the request handler."

That assumption is wrong — but it's a reasonable first instinct.

### What's actually true about `get_settings()`

`get_settings()` is just a regular Python function. `Depends()` is one way to call it, but not the only way. You can call it directly anywhere in your code:

```python
settings = get_settings()
print(settings.gemini_api_key)  # works perfectly
```

And because `get_settings()` is wrapped with `@lru_cache`, it only reads the `.env` file once no matter how many times you call it. Subsequent calls return the same cached `Settings` object instantly. There's no cost to calling it early.

```python
from functools import lru_cache
from app.core.config import Settings

@lru_cache
def get_settings() -> Settings:
    return Settings()  # reads .env once, caches forever
```

### The fix: configure once at startup

Move `genai.configure()` and the `GenerativeModel` instantiation into `main.py`, where the FastAPI app starts up. Call `get_settings()` directly — no `Depends()` needed at this stage.

```python
# main.py
from contextlib import asynccontextmanager
import google.generativeai as genai
from app.core.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup — before any requests are accepted
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    yield
    # Runs at shutdown (cleanup goes here if needed)

app = FastAPI(lifespan=lifespan)
```

Now `genai.configure()` runs exactly once, before the server starts accepting requests, in a single-threaded context. No race condition is possible because there's no concurrency yet at startup.

The `GenerativeModel` instance can be created once here too, and shared across requests via dependency injection — since `generate_content()` doesn't modify the model object's state, sharing it is safe.

---

## The deeper lesson: startup concerns vs request concerns

Both bugs share a common root cause: **startup work was pushed into the request path**.

There are two different moments in the life of a FastAPI application:

| Moment | When | Context |
|--------|------|---------|
| **Startup** | Server boots, before any requests | Single-threaded, runs once |
| **Request** | A user hits an endpoint | Concurrent, runs many times |

Work that only needs to happen once — loading config, configuring SDKs, creating clients, reading files — belongs at startup. Doing it in the request path means you're paying a cost (or introducing risk) on every single request, for something that didn't need to be repeated.

FastAPI makes this clean with the `lifespan` pattern: a single place to put all your startup and shutdown logic, clearly separated from your route handlers.

---

## Summary of the fixes

| Bug | Problem | Fix |
|-----|---------|-----|
| Blocking event loop | `model.generate_content()` is synchronous, freezes the event loop for 15–30s | Wrap with `await asyncio.to_thread()` |
| Global state mutation | `genai.configure()` writes to global SDK state on every request | Move to startup via `lifespan`, call once |

Both fixes are small in terms of lines changed. But the first one transforms the app from "can handle one request at a time" to "can handle many requests concurrently." And the second one removes a race condition that would have caused unpredictable failures under load.

---

## What to watch for in your own FastAPI apps

- Any third-party SDK call inside an `async def` function — check whether it has native async support. If it doesn't, use `asyncio.to_thread()`
- Any call to `configure()`, `setup()`, or similar SDK initialisation methods inside a route handler — these almost always belong at startup
- Any global variable being written to from inside a request handler — this is a race condition waiting to happen once you have concurrent requests

The tricky thing about both of these bugs is that they work fine in development. You test with one request at a time, everything looks good, and you ship. It's only under real concurrent load that the cracks show — and by then, they're hard to trace back to the root cause.

Audit your request handlers. If they're doing work that only needs to happen once, move it to startup.

---

*I'm building MyVastu as a portfolio project to grow as a backend engineer. If you found this useful, I'll be writing more posts as I add features — including a LangChain refactor and a LangGraph multi-agent system.*
