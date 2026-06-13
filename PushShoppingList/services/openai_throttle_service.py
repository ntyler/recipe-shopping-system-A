import contextlib
import json
import os
import time
import uuid


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
LIMIT_WINDOW_MS = 60 * 1000
CONCURRENCY_STALE_MS = 15 * 60 * 1000
DEFAULT_WAIT_TIMEOUT_SECONDS = 300


class OpenAIThrottleUnavailable(RuntimeError):
    pass


def _env_int(name, default_value=0, minimum=0):
    try:
        value = int(os.getenv(name, str(default_value)))
    except (TypeError, ValueError):
        return int(default_value)
    return max(int(minimum), value)


def redis_url():
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL


def max_requests_per_minute():
    return _env_int("OPENAI_GLOBAL_MAX_REQUESTS_PER_MINUTE", 0, minimum=0)


def max_tokens_per_minute():
    return _env_int("OPENAI_GLOBAL_MAX_TOKENS_PER_MINUTE", 0, minimum=0)


def max_concurrent_calls(kind):
    kind = str(kind or "").strip().lower()
    if kind == "menu":
        return _env_int("OPENAI_MENU_MAX_CONCURRENT_CALLS", 0, minimum=0)
    if kind == "vision":
        return _env_int("OPENAI_VISION_MAX_CONCURRENT_CALLS", 0, minimum=0)
    return 0


def limiter_is_enabled(kind=""):
    return bool(
        max_requests_per_minute()
        or max_tokens_per_minute()
        or max_concurrent_calls(kind)
    )


def _redis_client():
    try:
        from redis import Redis

        client = Redis.from_url(redis_url())
        client.ping()
        return client
    except Exception as exc:
        raise OpenAIThrottleUnavailable(
            "OpenAI throttling is enabled, but Redis is unavailable."
        ) from exc


def _json_size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except Exception:
        return len(str(value or ""))


def estimate_tokens_from_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    messages = payload.get("messages")
    size = _json_size(messages if messages is not None else payload)
    try:
        max_tokens = int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 0)
    except (TypeError, ValueError):
        max_tokens = 0
    return max(1, int(size / 4) + max_tokens + 128)


def limiter_kind_for_call(action_name="", model="", kind=""):
    explicit = str(kind or "").strip().lower()
    if explicit:
        return explicit

    text = f"{action_name} {model}".lower()
    if any(marker in text for marker in ("vision", "image")):
        return "vision"
    if any(marker in text for marker in ("menu", "restaurant")):
        return "menu"
    return "global"


_CONCURRENCY_LUA = """
local key = KEYS[1]
local member = ARGV[1]
local now = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local limit = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - ttl)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, ttl)
  return 0
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
if oldest[2] then
  local wait = tonumber(oldest[2]) + ttl - now
  if wait < 50 then
    wait = 50
  end
  return wait
end
return 100
"""


_ROLLING_LIMIT_LUA = """
local request_key = KEYS[1]
local token_key = KEYS[2]
local request_member = ARGV[1]
local token_member = ARGV[2]
local now = tonumber(ARGV[3])
local window = tonumber(ARGV[4])
local request_limit = tonumber(ARGV[5])
local token_limit = tonumber(ARGV[6])
local tokens = tonumber(ARGV[7])
redis.call('ZREMRANGEBYSCORE', request_key, '-inf', now - window)
redis.call('ZREMRANGEBYSCORE', token_key, '-inf', now - window)

local wait = 0
if request_limit > 0 then
  local request_count = redis.call('ZCARD', request_key)
  if request_count >= request_limit then
    local oldest_request = redis.call('ZRANGE', request_key, 0, 0, 'WITHSCORES')
    if oldest_request[2] then
      wait = math.max(wait, tonumber(oldest_request[2]) + window - now)
    else
      wait = math.max(wait, 100)
    end
  end
end

if token_limit > 0 then
  local token_sum = 0
  local token_members = redis.call('ZRANGE', token_key, 0, -1)
  for _, member in ipairs(token_members) do
    local token_value = string.match(member, ':(%d+)$')
    if token_value then
      token_sum = token_sum + tonumber(token_value)
    end
  end
  if token_sum + tokens > token_limit then
    local oldest_token = redis.call('ZRANGE', token_key, 0, 0, 'WITHSCORES')
    if oldest_token[2] then
      wait = math.max(wait, tonumber(oldest_token[2]) + window - now)
    else
      wait = math.max(wait, 100)
    end
  end
end

if wait > 0 then
  if wait < 50 then
    wait = 50
  end
  return wait
end

redis.call('ZADD', request_key, now, request_member)
redis.call('ZADD', token_key, now, token_member)
redis.call('PEXPIRE', request_key, window * 2)
redis.call('PEXPIRE', token_key, window * 2)
return 0
"""


def _wait_timeout_seconds():
    return _env_int(
        "OPENAI_GLOBAL_LIMIT_WAIT_TIMEOUT_SECONDS",
        DEFAULT_WAIT_TIMEOUT_SECONDS,
        minimum=1,
    )


def _sleep_for_wait(wait_ms):
    time.sleep(min(max(wait_ms / 1000.0, 0.05), 5.0))


def _wait_until_lua_allows(client, script, keys, args, description, now_arg_index):
    started = time.monotonic()
    timeout = _wait_timeout_seconds()
    while True:
        wait_ms = int(client.eval(script, len(keys), *keys, *args) or 0)
        if wait_ms <= 0:
            return
        if time.monotonic() - started > timeout:
            raise TimeoutError(f"Timed out waiting for OpenAI {description} capacity.")
        _sleep_for_wait(wait_ms)
        args = list(args)
        args[now_arg_index] = str(int(time.time() * 1000))


def _acquire_concurrency(client, kind, member):
    limit = max_concurrent_calls(kind)
    if limit <= 0:
        return None

    now = int(time.time() * 1000)
    key = f"shopping-app:openai:concurrent:{kind}"
    _wait_until_lua_allows(
        client,
        _CONCURRENCY_LUA,
        [key],
        [member, str(now), str(CONCURRENCY_STALE_MS), str(limit)],
        f"{kind} concurrency",
        now_arg_index=1,
    )
    return key


def _release_concurrency(client, key, member):
    if not key:
        return
    try:
        client.zrem(key, member)
    except Exception:
        pass


def _record_rolling_capacity(client, action_name, estimated_tokens):
    request_limit = max_requests_per_minute()
    token_limit = max_tokens_per_minute()
    if request_limit <= 0 and token_limit <= 0:
        return

    now = int(time.time() * 1000)
    event_id = uuid.uuid4().hex
    token_count = max(1, int(estimated_tokens or 1))
    _wait_until_lua_allows(
        client,
        _ROLLING_LIMIT_LUA,
        [
            "shopping-app:openai:requests",
            "shopping-app:openai:tokens",
        ],
        [
            f"{now}:{event_id}:{action_name or 'openai'}",
            f"{now}:{event_id}:{token_count}",
            str(now),
            str(LIMIT_WINDOW_MS),
            str(request_limit),
            str(token_limit),
            str(token_count),
        ],
        "request/token",
        now_arg_index=2,
    )


@contextlib.contextmanager
def throttle_openai_call(action_name="", model="", payload=None, estimated_tokens=None, kind=""):
    call_kind = limiter_kind_for_call(action_name=action_name, model=model, kind=kind)
    if not limiter_is_enabled(call_kind):
        yield
        return

    client = _redis_client()
    member = f"{os.getpid()}:{uuid.uuid4().hex}:{action_name or 'openai'}"
    concurrency_key = None
    token_count = estimated_tokens or estimate_tokens_from_payload(payload)
    try:
        concurrency_key = _acquire_concurrency(client, call_kind, member)
        _record_rolling_capacity(client, action_name, token_count)
        yield
    finally:
        _release_concurrency(client, concurrency_key, member)


def throttled_chat_completion(client, payload, action_name="", model="", kind=""):
    payload = payload if isinstance(payload, dict) else {}
    resolved_model = str(model or payload.get("model") or "").strip()
    with throttle_openai_call(
        action_name=action_name,
        model=resolved_model,
        payload=payload,
        kind=kind,
    ):
        return client.chat.completions.create(**payload)


def throttled_image_generation(client, payload, action_name="image-generation", model="", kind="vision"):
    payload = payload if isinstance(payload, dict) else {}
    resolved_model = str(model or payload.get("model") or "").strip()
    with throttle_openai_call(
        action_name=action_name,
        model=resolved_model,
        payload=payload,
        kind=kind,
    ):
        return client.images.generate(**payload)


def throttled_audio_transcription(client, payload, action_name="audio-transcription", model=""):
    payload = payload if isinstance(payload, dict) else {}
    resolved_model = str(model or payload.get("model") or "").strip()
    with throttle_openai_call(
        action_name=action_name,
        model=resolved_model,
        payload=payload,
    ):
        return client.audio.transcriptions.create(**payload)
