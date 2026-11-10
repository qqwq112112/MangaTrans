# -*- coding: utf-8 -*-
"""LM Studio / OpenAI-compatible chat client."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from .textrender import normalize_punctuation

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"

# LM Studio picks another port when the default is taken (e.g. 1235).
CANDIDATE_PORTS = (1234, 1235, 1236, 1237, 8080, 8000)


class LMStudioError(Exception):
    pass


def normalize_base_url(url: str) -> str:
    url = (url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not re.match(r"^https?://", url):
        url = "http://" + url
    if not url.endswith("/v1"):
        # LM Studio's canonical endpoint is /v1; tolerate either input.
        url += "/v1"
    return url


def _auth_headers(api_key: str) -> dict:
    key = (api_key or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _conn_hint(service: str) -> str:
    if service == "LM Studio":
        return "连不上 LM Studio，请确认本地服务器已开启（Developer → Start Server）。"
    return (f"连不上 {service}：请检查网络、接口地址，以及是否需要代理。"
            "（本机若开了全局代理，云端请求通常可以直接连通）")


def _http_hint(status: int, body: str, service: str) -> str:
    detail = (body or "").strip()[:300]
    if status in (401, 403):
        return (f"{service} 鉴权失败（HTTP {status}）：API Key 无效或没有权限。\n{detail}")
    if status == 402:
        return (f"{service} 余额不足（HTTP 402）：请到平台充值。\n{detail}")
    if status == 429:
        return (f"{service} 触发限流（HTTP 429）：稍后重试或换更小的模型。\n{detail}")
    if status == 404:
        return (f"{service} 找不到接口或模型（HTTP 404）："
                f"请检查地址是否以 /v1 结尾、模型名是否存在。\n{detail}")
    return f"{service} 返回 HTTP {status}：{detail}"


def _models_at(base: str, timeout: float, api_key: str = "") -> list[str]:
    resp = requests.get(f"{base}/models", timeout=timeout,
                        headers=_auth_headers(api_key))
    resp.raise_for_status()
    data = resp.json()
    models = []
    for item in data.get("data", []) if isinstance(data, dict) else []:
        model_id = item.get("id") if isinstance(item, dict) else None
        if model_id:
            models.append(model_id)
    return models


def discover_base_url(preferred: str = "", timeout: float = 1.2,
                      ports: tuple[int, ...] | None = None) -> str | None:
    """Return the first reachable OpenAI-compatible endpoint.

    The user-configured address is tried first, then the usual LM Studio
    ports. LM Studio silently moves to another port when the default is busy,
    so hard-coding 1234 breaks without any visible reason.
    """
    tried: list[str] = []
    candidates = []
    if preferred:
        candidates.append(normalize_base_url(preferred))
    for port in (ports or CANDIDATE_PORTS):
        url = f"http://127.0.0.1:{port}/v1"
        if url not in candidates:
            candidates.append(url)

    for base in candidates:
        if base in tried:
            continue
        tried.append(base)
        try:
            _models_at(base, timeout)
            return base
        except Exception:
            continue
    return None


def list_models(base_url: str, timeout: float = 6.0, api_key: str = "",
                service: str = "LM Studio",
                ports: tuple[int, ...] | None = None) -> list[str]:
    base = normalize_base_url(base_url)
    try:
        return _models_at(base, timeout, api_key)
    except requests.exceptions.ConnectionError as exc:
        # Port auto-discovery only makes sense for a LOCAL server; a cloud
        # endpoint must not be silently redirected to localhost.
        if not api_key:
            found = discover_base_url(base, timeout=1.2, ports=ports)
            if found and found != base:
                try:
                    return _models_at(found, timeout)
                except Exception:
                    pass
        raise LMStudioError(_conn_hint(service)) from exc
    except requests.exceptions.Timeout as exc:
        raise LMStudioError(f"连接 {service} 超时。") from exc
    except Exception as exc:
        raise LMStudioError(f"读取 {service} 模型列表失败：{exc}") from exc


EMBEDDING_HINTS = ("embed", "bge-", "gte-", "e5-", "jina", "nomic")


def _looks_like_embedding(model_id: str) -> bool:
    low = model_id.lower()
    return any(hint in low for hint in EMBEDDING_HINTS)


def pick_chat_model(models: list[str], preferred: str = "") -> str:
    """Choose a chat model, never an embedding model.

    LM Studio lists embedding models in the same /v1/models response, so a
    naive "take the first one" can select an embedding model and every
    translation then fails with an opaque 400.
    """
    if preferred and preferred in models and not _looks_like_embedding(preferred):
        return preferred
    chat = [m for m in models if not _looks_like_embedding(m)]
    if preferred and _looks_like_embedding(preferred) and chat:
        return chat[0]
    for model in chat:
        if "translat" in model.lower() or "instruct" in model.lower():
            return model
    return chat[0] if chat else ""


def ensure_model(base_url: str, preferred: str = "", api_key: str = "",
                 service: str = "LM Studio") -> str:
    models = list_models(base_url, api_key=api_key, service=service)
    chosen = pick_chat_model(models, preferred)
    if chosen:
        return chosen
    raise LMStudioError(
        "LM Studio 里只有 embedding 模型，没有可用的对话模型。"
        "请在 LM Studio 中载入一个翻译/对话模型。"
    )


_QUOTE_PAIRS = {
    "「": "」", "『": "』", "“": "”", "‘": "’", "\"": "\"", "'": "'",
    "（": "）", "(": ")", "【": "】",
}


def _strip_wrapping_quotes(text: str) -> str:
    """Remove one layer of symmetric quotes/brackets around the whole string."""
    for _ in range(2):
        if len(text) < 2:
            break
        close = _QUOTE_PAIRS.get(text[0])
        if close and text[-1] == close:
            text = text[1:-1].strip()
        else:
            break
    return text


def _clean_translation(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^(译文|翻译|中文译文|解释|注)\s*[:：]\s*", "", text)
    text = _strip_wrapping_quotes(text)
    # Normalize punctuation only for Chinese output; Japanese/Latin keep theirs.
    if re.search(r"[\u4e00-\u9fff]", text) and not re.search(r"[\u3040-\u30ff]", text):
        text = to_simplified(text)
        text = normalize_punctuation(text)
    # Models often pad lines with spaces when mirroring the source line breaks.
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def to_simplified(text: str) -> str:
    """Force the output to Simplified Chinese.

    The model is already told to answer in Simplified Chinese, but small models
    slip into Traditional now and then. zhconv is pure Python (~0.6 MB) so it
    costs nothing to bundle; if it is missing we keep the text as-is rather
    than failing the translation.
    """
    if not text:
        return text
    try:
        import zhconv
    except Exception:
        return text
    try:
        return zhconv.convert(text, "zh-cn")
    except Exception:
        return text



def _system_prompt() -> str:
    """Fixed translator prompt: output is always Simplified Chinese."""
    return (
        "你是专业的漫画汉化译者。把用户给出的漫画台词翻译成简体中文。\n"
        "要求：\n"
        "1. 只输出译文，不要解释、不要加引号、不要重复原文。\n"
        "2. 必须使用简体中文（不要繁体字），口语化，符合漫画对白习惯，简短自然。\n"
        "3. 人名、专有名词按常见译法处理，无法确定时保留原文。\n"
        "4. 保留换行（每行对应原文一行）。"
    )


@dataclass
class TranslationOutcome:
    """Result of one translation call, including timing metrics."""

    text: str = ""
    provider: str = ""
    model: str = ""
    ttft: float = 0.0          # seconds until the first token
    total: float = 0.0         # seconds for the whole response
    tokens: int = 0
    speed: float = 0.0         # tokens per second (after the first token)
    estimated: bool = False    # True when the token count was approximated
    streamed: bool = True

    def summary(self) -> str:
        """One-line description for the dialog's status strip."""
        bits = [self.provider, self.model]
        label = " › ".join(b for b in bits if b)
        extra = []
        if self.speed > 0:
            extra.append(f"{self.speed:.1f} tok/s"
                         + ("（估算）" if self.estimated else ""))
        if self.ttft > 0:
            extra.append(f"首字 {self.ttft:.2f}s")
        return f"{label} · " + " · ".join(extra) if extra else label


def _estimate_tokens(text: str) -> int:
    """Rough token count when the backend does not report usage.

    CJK text is close to 1 token per character for most modern tokenizers;
    ASCII words average ~4 characters per token.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff"
              or "\u3040" <= ch <= "\u30ff")
    other = len(text) - cjk
    return max(1, int(cjk + other / 3.5))


def _post_stream(url: str, payload: dict, headers: dict, timeout: float,
                 api_style: str = "openai"):
    """POST and yield content deltas as they arrive."""
    headers = dict(headers)
    headers.setdefault("Accept", "text/event-stream")
    payload = dict(payload)
    payload["stream"] = True
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout,
                         stream=True)
    if resp.status_code >= 400:
        detail = resp.text[:400] if resp.text else ""
        raise LMStudioError(f"HTTP {resp.status_code}：{detail}")

    # Some servers (and simple test doubles) ignore stream=True and answer with
    # one plain JSON body. Detect that and emit the whole message at once so the
    # caller still gets its text and metrics.
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "event-stream" not in ctype:
        try:
            data = resp.json()
        except Exception:
            data = None
        if isinstance(data, dict):
            if api_style == "anthropic":
                blocks = data.get("content") or []
                text = "".join(b.get("text", "") for b in blocks
                               if isinstance(b, dict))
            else:
                try:
                    text = data["choices"][0]["message"]["content"]
                except Exception:
                    text = ""
            usage = data.get("usage") or {}
            tokens = usage.get("output_tokens") or usage.get("completion_tokens")
            if text:
                yield text
            if tokens:
                yield ("__usage__", int(tokens))
            return
        if text_is_error := (resp.text or "").strip()[:200]:
            raise LMStudioError(f"返回内容无法解析：{text_is_error}")

    for raw in resp.iter_lines(decode_unicode=False):
        if not raw:
            continue
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            if chunk == "[DONE]":
                return
            continue
        try:
            data = json.loads(chunk)
        except Exception:
            continue

        if api_style == "anthropic":
            kind = data.get("type")
            if kind == "content_block_delta":
                delta = data.get("delta") or {}
                piece = delta.get("text") or ""
                if piece:
                    yield piece
            elif kind == "message_delta":
                usage = data.get("usage") or {}
                if usage.get("output_tokens"):
                    yield ("__usage__", int(usage["output_tokens"]))
            elif kind == "error":
                raise LMStudioError(str(data.get("error")))
        else:
            choices = data.get("choices") or []
            for choice in choices:
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    yield piece
            usage = data.get("usage") or {}
            if usage.get("completion_tokens"):
                yield ("__usage__", int(usage["completion_tokens"]))


def _request_body(model: str, text: str, temperature: float,
                  api_style: str, max_tokens: int = 1024) -> dict:
    system = _system_prompt()
    if api_style == "anthropic":
        return {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": float(temperature),
            "system": system,
            "messages": [{"role": "user", "content": text}],
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": float(temperature),
        "max_tokens": max_tokens,
    }


def _headers_for(api_style: str, api_key: str) -> dict:
    key = (api_key or "").strip()
    if api_style == "anthropic":
        head = {"anthropic-version": "2023-06-01",
                "content-type": "application/json"}
        if key:
            head["x-api-key"] = key
        return head
    return _auth_headers(key)


def _endpoint(base: str, api_style: str) -> str:
    if api_style == "anthropic":
        return base.rstrip("/") + "/messages"
    return base.rstrip("/") + "/chat/completions"


def translate_full(
    text: str,
    config,
    on_event=None,
    timeout: float = 180.0,
) -> TranslationOutcome:
    """Translate using the configured provider and report live metrics.

    `on_event` receives dicts so the UI can show progress while tokens stream:
        {"kind": "start", "provider": ..., "model": ...}
        {"kind": "delta", "text": partial, "ttft": s, "speed": tok/s}
        {"kind": "done", "outcome": TranslationOutcome}
    """
    import time

    text = (text or "").strip()
    if not text:
        raise LMStudioError("原文为空，无法翻译。")

    prof = provider_profile(config)
    spec = provider_spec(prof["provider_key"])
    if spec.needs_key and not prof["api_key"].strip():
        raise LMStudioError(
            f"当前使用「{spec.name}」，但还没有填写 API Key。\n"
            "请到 设置 → 翻译模型 里填入。")
    if not prof["base_url"].strip():
        raise LMStudioError(f"「{spec.name}」还没有填写接口地址。")

    model = (prof["model"] or "").strip()
    base = normalize_base_url(prof["base_url"])
    if not model and spec.is_local:
        model = ensure_model(base, api_key=prof["api_key"], service=spec.name)
    if not model:
        raise LMStudioError(f"「{spec.name}」还没有选择模型。")

    outcome = TranslationOutcome(provider=spec.name, model=model)
    if on_event:
        on_event({"kind": "start", "provider": spec.name, "model": model})

    headers = _headers_for(spec.api_style, prof["api_key"])
    body = _request_body(model, text, prof["temperature"], spec.api_style)
    url = _endpoint(base, spec.api_style)

    t0 = time.perf_counter()
    first_at = 0.0
    pieces: list[str] = []
    usage_tokens = 0

    try:
        stream_iter = _post_stream(url, body, headers, timeout, spec.api_style)
        for item in stream_iter:
            if isinstance(item, tuple) and item and item[0] == "__usage__":
                usage_tokens = int(item[1])
                continue
            if not first_at:
                first_at = time.perf_counter()
            pieces.append(item)
            if on_event:
                elapsed = max(1e-6, time.perf_counter() - first_at)
                partial = "".join(pieces)
                on_event({
                    "kind": "delta",
                    "text": partial,
                    "ttft": first_at - t0,
                    "speed": _estimate_tokens(partial) / elapsed,
                })
    except requests.exceptions.ConnectionError as exc:
        raise LMStudioError(_conn_hint(spec.name)) from exc
    except requests.exceptions.Timeout as exc:
        raise LMStudioError(f"{spec.name} 请求超时。") from exc

    end = time.perf_counter()
    raw = "".join(pieces)
    result = _clean_translation(raw)
    if not result:
        raise LMStudioError(f"{spec.name} 返回了空译文。")

    outcome.text = result
    outcome.total = end - t0
    outcome.ttft = (first_at - t0) if first_at else outcome.total
    if usage_tokens:
        outcome.tokens = usage_tokens
    else:
        outcome.tokens = _estimate_tokens(result)
        outcome.estimated = True
    span = max(1e-6, end - (first_at or t0))
    outcome.speed = outcome.tokens / span
    if on_event:
        on_event({"kind": "done", "outcome": outcome})
    return outcome


def translate_text(
    text: str,
    base_url: str,
    model: str = "",
    temperature: float = 0.2,
    timeout: float = 180.0,
    api_key: str = "",
    service: str = "LM Studio",
    api_style: str = "openai",
) -> str:
    """Single-call helper used by tests and simple integrations."""
    text = (text or "").strip()
    if not text:
        raise LMStudioError("原文为空，无法翻译。")

    base = normalize_base_url(base_url)
    if not model:
        model = ensure_model(base, api_key=api_key, service=service)

    headers = _headers_for(api_style, api_key)
    body = _request_body(model, text, temperature, api_style)
    url = _endpoint(base, api_style)

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        raise LMStudioError(_conn_hint(service)) from exc
    except requests.exceptions.Timeout as exc:
        raise LMStudioError(f"{service} 请求超时。") from exc
    except Exception as exc:
        raise LMStudioError(f"{service} 请求失败：{exc}") from exc

    if resp.status_code >= 400:
        raise LMStudioError(_http_hint(resp.status_code, resp.text, service))

    try:
        data = resp.json()
        if api_style == "anthropic":
            blocks = data.get("content") or []
            message = "".join(b.get("text", "") for b in blocks
                              if isinstance(b, dict))
        else:
            message = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise LMStudioError(f"无法解析 {service} 响应：{exc}") from exc

    result = _clean_translation(message)
    if not result:
        raise LMStudioError("模型返回了空译文。")
    return result


def test_connection(base_url: str, timeout: float = 6.0, api_key: str = "",
                    service: str = "LM Studio",
                    api_style: str = "openai") -> tuple[bool, str, list[str]]:
    if api_style == "anthropic":
        # Anthropic has no /models endpoint; a HEAD-ish call is enough to prove
        # the key and network work, so report success with an empty list.
        try:
            requests.get(base_url.rstrip("/") + "/messages", timeout=timeout,
                         headers=_headers_for("anthropic", api_key))
        except requests.exceptions.ConnectionError:
            return False, _conn_hint(service), []
        except Exception as exc:
            return False, f"{service} 连接失败：{exc}", []
        return True, f"已连接 {service}（Anthropic 接口不提供模型列表）", []
    try:
        models = list_models(base_url, timeout=timeout, api_key=api_key,
                             service=service)
    except LMStudioError as exc:
        return False, str(exc), []
    if not models:
        return True, f"已连接 {service}，但没有可用模型。", []
    return True, f"已连接 {service}，共 {len(models)} 个模型。", models


# ---------------------------------------------------------------- providers

@dataclass(frozen=True)
class ProviderSpec:
    """A translation backend the user can pick in 设置.

    api_style "openai"  : POST /chat/completions (most vendors)
    api_style "anthropic": POST /messages with x-api-key
    """

    key: str
    name: str
    base_url: str
    needs_key: bool
    is_local: bool
    default_model: str = ""
    models: tuple[str, ...] = ()
    api_style: str = "openai"
    local_ports: tuple[int, ...] = ()
    hint: str = ""


PROVIDERS: tuple[ProviderSpec, ...] = (
    # ---- local runtimes (no API key, data stays on this machine) ----------
    ProviderSpec(
        key="lmstudio", name="本地 · LM Studio",
        base_url="http://127.0.0.1:1234/v1", needs_key=False, is_local=True,
        local_ports=(1234, 1235, 1236, 1237),
        hint="LM Studio → Developer → Start Server",
    ),
    ProviderSpec(
        key="ollama", name="本地 · Ollama",
        base_url="http://127.0.0.1:11434/v1", needs_key=False, is_local=True,
        local_ports=(11434,),
        models=("qwen2.5:7b", "qwen2.5:14b", "gemma2:9b", "llama3.1:8b"),
        hint="先执行 ollama serve，并 ollama pull 一个模型",
    ),
    ProviderSpec(
        key="llamacpp", name="本地 · llama.cpp server",
        base_url="http://127.0.0.1:8080/v1", needs_key=False, is_local=True,
        local_ports=(8080, 8081),
        hint="llama-server -m 模型.gguf --port 8080",
    ),
    ProviderSpec(
        key="koboldcpp", name="本地 · KoboldCpp",
        base_url="http://127.0.0.1:5001/v1", needs_key=False, is_local=True,
        local_ports=(5001,),
        hint="KoboldCpp 启动后启用 OpenAI 兼容接口",
    ),
    ProviderSpec(
        key="mlx", name="本地 · MLX (Apple/MLX-LM)",
        base_url="http://127.0.0.1:8081/v1", needs_key=False, is_local=True,
        local_ports=(8081, 8080),
        hint="mlx_lm.server --model <模型> --port 8081（仅 macOS）",
    ),
    ProviderSpec(
        key="vllm", name="本地 · vLLM",
        base_url="http://127.0.0.1:8000/v1", needs_key=False, is_local=True,
        local_ports=(8000,),
        hint="vllm serve <模型> --port 8000",
    ),
    # ---- cloud APIs -------------------------------------------------------
    ProviderSpec(
        key="openai", name="OpenAI",
        base_url="https://api.openai.com/v1", needs_key=True, is_local=False,
        default_model="gpt-4o-mini",
        models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1",
                "o4-mini"),
    ),
    ProviderSpec(
        key="claude", name="Anthropic Claude",
        base_url="https://api.anthropic.com/v1", needs_key=True, is_local=False,
        default_model="claude-3-5-haiku-20241022",
        models=("claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022",
                "claude-sonnet-4-20250514", "claude-opus-4-20250514"),
        api_style="anthropic",
        hint="使用 Anthropic 原生 Messages 接口（x-api-key 鉴权）",
    ),
    ProviderSpec(
        key="deepseek", name="DeepSeek",
        base_url="https://api.deepseek.com/v1", needs_key=True, is_local=False,
        default_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderSpec(
        key="kimi", name="Kimi (Moonshot)",
        base_url="https://api.moonshot.cn/v1", needs_key=True, is_local=False,
        default_model="moonshot-v1-8k",
        models=("moonshot-v1-8k", "moonshot-v1-32k", "kimi-k2-0905-preview"),
    ),
    ProviderSpec(
        key="qwen", name="通义千问 (DashScope)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        needs_key=True, is_local=False,
        default_model="qwen-plus",
        models=("qwen-turbo", "qwen-plus", "qwen-max", "qwen2.5-7b-instruct"),
    ),
    ProviderSpec(
        key="glm", name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4", needs_key=True,
        is_local=False,
        default_model="glm-4-flash",
        models=("glm-4-flash", "glm-4-air", "glm-4-plus", "glm-4.5"),
    ),
    ProviderSpec(
        key="minimax", name="MiniMax",
        base_url="https://api.minimax.chat/v1", needs_key=True, is_local=False,
        default_model="abab6.5s-chat",
        models=("abab6.5s-chat", "MiniMax-Text-01"),
    ),
    ProviderSpec(
        key="gemini", name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        needs_key=True, is_local=False,
        default_model="gemini-2.0-flash",
        models=("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"),
        hint="走 Gemini 的 OpenAI 兼容端点",
    ),
    ProviderSpec(
        key="siliconflow", name="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1", needs_key=True, is_local=False,
        default_model="Qwen/Qwen2.5-7B-Instruct",
        models=("Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-14B-Instruct",
                "Qwen/Qwen2.5-32B-Instruct", "Qwen/Qwen3-8B",
                "THUDM/GLM-4-9B-0414", "deepseek-ai/DeepSeek-V3"),
    ),
    ProviderSpec(
        key="custom", name="自定义（OpenAI 兼容）",
        base_url="", needs_key=True, is_local=False,
        default_model="",
        hint="任何兼容 /v1/chat/completions 的服务",
    ),
)

_PROVIDER_BY_KEY = {p.key: p for p in PROVIDERS}

# Old configs used "local" for LM Studio.
_LEGACY_KEYS = {"local": "lmstudio"}


def provider_spec(key: str) -> ProviderSpec:
    key = _LEGACY_KEYS.get(key or "", key or "lmstudio")
    return _PROVIDER_BY_KEY.get(key, _PROVIDER_BY_KEY["lmstudio"])


def cloud_providers() -> tuple[ProviderSpec, ...]:
    return tuple(p for p in PROVIDERS if not p.is_local)


def local_providers() -> tuple[ProviderSpec, ...]:
    return tuple(p for p in PROVIDERS if p.is_local)


def provider_profile(config, key: str | None = None) -> dict:
    """Resolve the saved settings for one provider.

    Each provider keeps its own base_url / model / key / temperature, so
    switching back and forth never loses credentials.
    """
    raw_key = key if key is not None else getattr(config, "provider", "lmstudio")
    spec = provider_spec(raw_key)
    profiles = getattr(config, "provider_profiles", None) or {}
    saved = profiles.get(spec.key) or {}

    # Migrate the pre-profile single cloud slot into the matching provider.
    if not saved:
        old_provider = _LEGACY_KEYS.get(getattr(config, "provider", ""),
                                        getattr(config, "provider", ""))
        if spec.key == old_provider and not spec.is_local:
            saved = {
                "base_url": getattr(config, "api_base_url", ""),
                "model": getattr(config, "api_model", ""),
                "api_key": getattr(config, "api_key", ""),
                "temperature": getattr(config, "api_temperature", 0.3),
            }
        elif spec.key == "lmstudio":
            saved = {
                "base_url": getattr(config, "lm_base_url", spec.base_url),
                "model": getattr(config, "lm_model", ""),
                "api_key": "",
                "temperature": getattr(config, "lm_temperature", 0.2),
            }

    base = (saved.get("base_url") or spec.base_url or "").strip()
    return {
        "provider_key": spec.key,
        "base_url": base,
        "model": (saved.get("model") or "").strip(),
        "api_key": (saved.get("api_key") or "").strip(),
        "temperature": float(saved.get("temperature",
                                      0.2 if spec.is_local else 0.3)),
    }


def save_provider_profile(config, key: str, **values) -> None:
    """Write one provider's settings back into the config."""
    spec = provider_spec(key)
    profiles = dict(getattr(config, "provider_profiles", None) or {})
    entry = dict(profiles.get(spec.key) or {})
    for name in ("base_url", "model", "api_key", "temperature"):
        if name in values and values[name] is not None:
            entry[name] = values[name]
    profiles[spec.key] = entry
    config.provider_profiles = profiles
    clear_label_cache()


def provider_settings(config, key: str | None = None) -> dict:
    """Backwards-compatible view used by older call sites."""
    prof = provider_profile(config, key)
    spec = provider_spec(prof["provider_key"])
    return {
        "service": spec.name,
        "base_url": prof["base_url"],
        "model": prof["model"],
        "api_key": prof["api_key"],
        "temperature": prof["temperature"],
        "requires_key": spec.needs_key,
        "is_local": spec.is_local,
        "api_style": spec.api_style,
        "spec": spec,
    }


def translate_with_config(text: str, config, on_event=None) -> str:
    """Translate and return just the text (metrics via `on_event`)."""
    return translate_full(text, config, on_event=on_event).text


def translate_with_metrics(text: str, config, on_event=None) -> TranslationOutcome:
    return translate_full(text, config, on_event=on_event)


def test_provider(config, overrides: dict | None = None
                  ) -> tuple[bool, str, list[str]]:
    prof = provider_profile(config)
    if overrides:
        prof.update({k: v for k, v in overrides.items() if k in prof})
    spec = provider_spec(prof["provider_key"])
    if spec.needs_key and not prof["api_key"].strip():
        return False, f"「{spec.name}」需要 API Key，请先填写。", []
    if not prof["base_url"].strip():
        return False, "请先填写接口地址。", []
    return test_connection(prof["base_url"], api_key=prof["api_key"],
                           service=spec.name, api_style=spec.api_style)


# ---------------------------------------------------------------- model label

_LABEL_CACHE: dict[str, str] = {}


def cached_model_label(config) -> str | None:
    """Non-blocking variant: a previously resolved label, or None.

    The region dialog is built on the UI thread, so it must never wait on the
    network. Callers show a generic label first and refresh later.
    """
    prof = provider_profile(config)
    spec = provider_spec(prof["provider_key"])
    if not spec.is_local:
        return f"{spec.name} · {prof['model'] or '（未选择模型）'}"
    if prof["model"]:
        return f"{spec.name} · {prof['model']}"
    return _LABEL_CACHE.get(f"{spec.key}|{prof['base_url']}")


def active_model_label(config, probe_timeout: float = 1.2) -> str:
    """Human-readable "provider · model". Probes local runtimes when unknown.

    Only ever call this from a worker thread: probing a dead local runtime can
    take a couple of seconds.
    """
    prof = provider_profile(config)
    spec = provider_spec(prof["provider_key"])
    if not spec.is_local:
        return f"{spec.name} · {prof['model'] or '（未选择模型）'}"
    if prof["model"]:
        return f"{spec.name} · {prof['model']}"

    key = f"{spec.key}|{prof['base_url']}"
    if key in _LABEL_CACHE:
        return _LABEL_CACHE[key]

    label = f"{spec.name} · （未连接）"
    try:
        models = list_models(prof["base_url"], timeout=probe_timeout,
                             service=spec.name,
                             ports=spec.local_ports or None)
        chosen = pick_chat_model(models)
        if chosen:
            label = f"{spec.name} · {chosen}"
            _LABEL_CACHE[key] = label
        elif models:
            label = f"{spec.name} · 仅加载了 embedding 模型"
    except Exception:
        pass
    return label


def clear_label_cache() -> None:
    _LABEL_CACHE.clear()
