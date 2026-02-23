from __future__ import annotations

import base64
import json
import os
import random
import re
import string
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from clinicaflow.inference.openai_compatible import InferenceError


@dataclass(frozen=True, slots=True)
class GradioSpaceConfig:
    base_url: str
    api_name: str = "chat"
    timeout_s: float = 45.0
    max_retries: int = 1
    retry_backoff_s: float = 0.5
    max_tokens: int = 600


@dataclass(frozen=True, slots=True)
class _GradioEndpoint:
    api_prefix: str
    fn_index: int
    trigger_id: int
    inputs: list[dict[str, Any]]
    output_mode: str


_ENDPOINT_CACHE: dict[tuple[str, str], _GradioEndpoint] = {}


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, str(default)) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, str(default)) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _rand_session_hash() -> str:
    # Gradio frontends typically use a short base36-ish token.
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(10))


def load_gradio_space_config_from_env() -> GradioSpaceConfig:
    return load_gradio_space_config_from_env_prefix("CLINICAFLOW_REASONING")


def load_gradio_space_configs_from_env() -> list[GradioSpaceConfig]:
    return load_gradio_space_configs_from_env_prefix("CLINICAFLOW_REASONING")


def load_gradio_space_config_from_env_prefix(prefix: str) -> GradioSpaceConfig:
    configs = load_gradio_space_configs_from_env_prefix(prefix)
    if not configs:
        raise InferenceError(f"Missing env var: {prefix}_BASE_URL (expected a Gradio Space root URL)")
    return configs[0]


def _parse_space_url_entries(raw: str, *, default_api_name: str) -> list[tuple[str, str]]:
    items = [s.strip() for s in str(raw or "").split(",")]
    out: list[tuple[str, str]] = []
    for item in items:
        if not item:
            continue
        url = item
        api_name = default_api_name
        if "|" in item:
            left, right = item.split("|", 1)
            url = left.strip()
            api_name = right.strip() or default_api_name
        url = str(url or "").strip().rstrip("/")
        if not url:
            continue
        out.append((url, str(api_name or default_api_name).strip() or "chat"))

    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for url, api_name in out:
        key = (url, api_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((url, api_name))
    return deduped


def load_gradio_space_configs_from_env_prefix(prefix: str) -> list[GradioSpaceConfig]:
    prefix = (prefix or "").strip().upper() or "CLINICAFLOW_REASONING"

    def env(name: str, default: str = "") -> str:
        key = f"{prefix}_{name}"
        return str(os.environ.get(key, default) or "").strip()

    api_name = env("GRADIO_API_NAME", "chat") or "chat"
    base_urls = env("BASE_URLS", "")
    base_url = env("BASE_URL", "")

    timeout_s = _env_float(f"{prefix}_TIMEOUT_S", 45.0)
    max_retries = _env_int(f"{prefix}_MAX_RETRIES", 1)
    retry_backoff_s = _env_float(f"{prefix}_RETRY_BACKOFF_S", 0.5)
    max_tokens = _env_int(f"{prefix}_MAX_TOKENS", 600)

    urls = base_urls or base_url
    entries = _parse_space_url_entries(urls, default_api_name=str(api_name).strip() or "chat") if urls else []
    if not entries:
        raise InferenceError(f"Missing env var: {prefix}_BASE_URL (expected a Gradio Space root URL)")

    configs: list[GradioSpaceConfig] = []
    for url, entry_api_name in entries:
        configs.append(
            GradioSpaceConfig(
                base_url=url,
                api_name=str(entry_api_name).strip() or "chat",
                timeout_s=max(1.0, float(timeout_s)),
                max_retries=max(0, int(max_retries)),
                retry_backoff_s=max(0.0, float(retry_backoff_s)),
                max_tokens=max(1, int(max_tokens)),
            )
        )
    return configs


def gradio_chat_completion(
    *,
    config: GradioSpaceConfig,
    system: str,
    user: str,
    image_data_urls: list[str] | None = None,
    max_images: int = 0,
    max_image_bytes: int = 2_000_000,
) -> str:
    """Call a Gradio Space ChatInterface API (best-effort).

    This is intended for demos: free hosted Spaces can change without notice
    and may enforce quotas/rate-limits.
    """

    endpoint = _discover_endpoint(base_url=config.base_url, api_name=config.api_name)
    session_hash = _rand_session_hash()

    join_url = _join_url(base_url=config.base_url, api_prefix=endpoint.api_prefix)
    queue_url = _queue_data_url(base_url=config.base_url, api_prefix=endpoint.api_prefix, session_hash=session_hash)

    files: list[dict[str, Any]] = []
    if max_images > 0 and image_data_urls:
        files = _upload_image_data_urls(
            base_url=config.base_url,
            api_prefix=endpoint.api_prefix,
            upload_id=session_hash,
            image_data_urls=image_data_urls,
            max_images=max_images,
            max_image_bytes=max_image_bytes,
            timeout_s=config.timeout_s,
        )

    data = _build_input_data(
        endpoint=endpoint,
        system=system,
        user=user,
        max_tokens=config.max_tokens,
        files=files,
    )

    join_body = {
        "data": data,
        "event_data": None,
        "fn_index": endpoint.fn_index,
        "trigger_id": endpoint.trigger_id,
        "session_hash": session_hash,
    }

    last_exc: Exception | None = None
    for attempt in range(config.max_retries + 1):
        try:
            event_id = _queue_join(join_url=join_url, body=join_body, timeout_s=config.timeout_s)
            completed = _queue_wait_for_completed(
                queue_url=queue_url,
                event_id=event_id,
                timeout_s=config.timeout_s,
            )
            return _extract_text_from_completed(completed, output_mode=endpoint.output_mode)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= config.max_retries:
                raise InferenceError(f"Gradio Space request failed: {exc}") from exc
            time.sleep(config.retry_backoff_s * (2**attempt))

    raise InferenceError(f"Gradio Space request failed: {last_exc}")


def _join_url(*, base_url: str, api_prefix: str) -> str:
    base = str(base_url or "").rstrip("/")
    api_prefix = "/" + str(api_prefix or "").strip("/ ")
    return f"{base}{api_prefix}/queue/join?"


def _queue_data_url(*, base_url: str, api_prefix: str, session_hash: str) -> str:
    base = str(base_url or "").rstrip("/")
    api_prefix = "/" + str(api_prefix or "").strip("/ ")
    return f"{base}{api_prefix}/queue/data?session_hash={session_hash}"


def _upload_image_data_urls(
    *,
    base_url: str,
    api_prefix: str,
    upload_id: str,
    image_data_urls: list[str],
    max_images: int,
    max_image_bytes: int,
    timeout_s: float,
) -> list[dict[str, Any]]:
    urls = [str(u).strip() for u in (image_data_urls or []) if isinstance(u, str)]
    urls = [u for u in urls if u.startswith("data:image/")]
    if not urls:
        return []

    to_send = urls[: max(0, int(max_images))]
    if not to_send:
        return []

    file_payloads: list[tuple[bytes, str, str]] = []
    for i, u in enumerate(to_send):
        data, mime = _decode_image_data_url(u)
        if max_image_bytes > 0 and len(data) > int(max_image_bytes):
            raise InferenceError(f"Image too large for Gradio upload: {len(data)} bytes (limit {max_image_bytes})")
        ext = _ext_from_mime(mime) or "png"
        filename = f"image_{i}.{ext}"
        file_payloads.append((data, filename, mime))

    upload_paths = _upload_files_to_gradio(
        base_url=base_url,
        api_prefix=api_prefix,
        upload_id=upload_id,
        files=file_payloads,
        timeout_s=timeout_s,
    )

    filedata: list[dict[str, Any]] = []
    for (data, filename, mime), path in zip(file_payloads, upload_paths, strict=False):
        path = str(path or "").strip()
        if not path:
            continue
        api_prefix_clean = "/" + str(api_prefix or "").strip("/ ")
        file_url = f"{str(base_url or '').rstrip('/')}{api_prefix_clean}/file={path}"
        filedata.append(
            {
                "path": path,
                "url": file_url,
                "orig_name": filename,
                "size": len(data),
                "mime_type": mime,
                "meta": {"_type": "gradio.FileData"},
            }
        )

    return filedata


_DATA_URL_RE = re.compile(r"^data:(?P<mime>image/[^;]+);base64,(?P<b64>.+)$", flags=re.IGNORECASE | re.DOTALL)


def _decode_image_data_url(url: str) -> tuple[bytes, str]:
    raw = str(url or "").strip()
    m = _DATA_URL_RE.match(raw)
    if not m:
        raise InferenceError("Unsupported image_data_url (expected data:image/...;base64,...)")
    mime = str(m.group("mime") or "image/png").strip().lower()
    b64 = (m.group("b64") or "").strip()
    try:
        data = base64.b64decode(b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise InferenceError(f"Invalid base64 image_data_url: {exc}") from exc
    if not data:
        raise InferenceError("Empty image_data_url payload")
    return data, mime


def _ext_from_mime(mime: str) -> str:
    m = str(mime or "").strip().lower()
    if m == "image/jpeg":
        return "jpg"
    if m == "image/jpg":
        return "jpg"
    if m == "image/png":
        return "png"
    if m == "image/webp":
        return "webp"
    if m == "image/gif":
        return "gif"
    return ""


def _upload_files_to_gradio(
    *,
    base_url: str,
    api_prefix: str,
    upload_id: str,
    files: list[tuple[bytes, str, str]],
    timeout_s: float,
) -> list[str]:
    base = str(base_url or "").rstrip("/")
    api_prefix_clean = "/" + str(api_prefix or "").strip("/ ")
    upload_id = str(upload_id or "").strip()

    # Gradio accepts: POST {api_prefix}/upload (optionally with ?upload_id=...).
    upload_url = f"{base}{api_prefix_clean}/upload"
    if upload_id:
        upload_url = f"{upload_url}?upload_id={upload_id}"

    boundary = "----clinicaflowgradio" + _rand_session_hash()
    body = _encode_multipart_files(boundary=boundary, files=files)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    }
    req = urllib.request.Request(upload_url, method="POST", data=body, headers=headers)  # noqa: S310

    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise InferenceError(f"Gradio upload failed: {exc}") from exc

    # Common response: ["tmp_path1", "tmp_path2", ...]
    if isinstance(payload, list) and all(isinstance(x, str) for x in payload):
        return [str(x).strip() for x in payload if str(x).strip()]

    # Some versions may wrap in an object.
    if isinstance(payload, dict):
        items = payload.get("files") or payload.get("data") or payload.get("paths")
        if isinstance(items, list) and all(isinstance(x, str) for x in items):
            return [str(x).strip() for x in items if str(x).strip()]

    raise InferenceError(f"Unexpected Gradio upload response: {payload!r}")


def _encode_multipart_files(*, boundary: str, files: list[tuple[bytes, str, str]]) -> bytes:
    b = str(boundary or "").encode("utf-8")
    out = bytearray()
    for data, filename, mime in files:
        filename = str(filename or "upload.bin")
        mime = str(mime or "application/octet-stream")
        out.extend(b"--" + b + b"\r\n")
        out.extend(
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'.encode("utf-8")
        )
        out.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        out.extend(data)
        out.extend(b"\r\n")
    out.extend(b"--" + b + b"--\r\n")
    return bytes(out)


def _queue_join(*, join_url: str, body: dict[str, Any], timeout_s: float) -> str:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url=join_url,
        method="POST",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise InferenceError(f"Gradio join failed: {exc}") from exc

    event_id = payload.get("event_id") if isinstance(payload, dict) else None
    if not isinstance(event_id, str) or not event_id.strip():
        raise InferenceError(f"Unexpected Gradio join response: {payload!r}")
    return event_id.strip()


def _queue_wait_for_completed(*, queue_url: str, event_id: str, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(  # noqa: S310
        url=queue_url,
        method="GET",
        headers={"Accept": "text/event-stream"},
    )
    deadline = time.time() + max(1.0, timeout_s)

    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:  # noqa: S310
            while time.time() < deadline:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                raw = text[len("data:") :].strip()
                if not raw or raw == "null":
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("event_id") or "") != event_id:
                    continue
                if obj.get("msg") == "process_completed":
                    return obj
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise InferenceError(f"Gradio queue stream failed: {exc}") from exc

    raise InferenceError("Gradio queue timeout waiting for process_completed")


def _extract_text_from_completed(completed: dict[str, Any], *, output_mode: str) -> str:
    if bool(completed.get("success")) is not True:
        out = completed.get("output")
        if isinstance(out, dict):
            err = out.get("error") or out.get("title") or completed.get("title") or "Gradio error"
            raise InferenceError(str(err).strip() or "Gradio error")
        raise InferenceError(str(completed.get("title") or "Gradio error").strip() or "Gradio error")

    output = completed.get("output")
    if not isinstance(output, dict):
        raise InferenceError(f"Unexpected Gradio output: {output!r}")
    data = output.get("data")
    if not isinstance(data, list) or not data:
        raise InferenceError(f"Unexpected Gradio output data: {data!r}")

    primary = data[0]
    if isinstance(primary, str):
        return primary

    # Some Spaces return an OpenAI-like response blob for debugging.
    if isinstance(primary, dict) and output_mode == "openai_like":
        try:
            choice0 = primary["choices"][0]
            msg = choice0.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
        except Exception:  # noqa: BLE001
            pass

    # Fallback: stringify JSON.
    try:
        return json.dumps(primary, ensure_ascii=False)
    except TypeError:
        return str(primary)


def _discover_endpoint(*, base_url: str, api_name: str) -> _GradioEndpoint:
    key = (str(base_url or "").rstrip("/"), str(api_name or "").strip() or "chat")
    cached = _ENDPOINT_CACHE.get(key)
    if cached:
        return cached

    config_url = key[0] + "/config"
    req = urllib.request.Request(  # noqa: S310
        url=config_url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
            cfg = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise InferenceError(f"Failed to load Gradio /config: {exc}") from exc

    if not isinstance(cfg, dict):
        raise InferenceError("Invalid Gradio /config payload")

    api_prefix = str(cfg.get("api_prefix") or "/gradio_api").strip() or "/gradio_api"

    deps = cfg.get("dependencies")
    if not isinstance(deps, list):
        raise InferenceError("Invalid Gradio /config: missing dependencies")

    dep_index = -1
    dep: dict[str, Any] | None = None
    for i, d in enumerate(deps):
        if not isinstance(d, dict):
            continue
        if str(d.get("api_name") or "").strip() == key[1]:
            dep_index = i
            dep = d
            break
    if dep_index < 0 or dep is None:
        raise InferenceError(f"Gradio /config has no dependency with api_name={key[1]!r}")

    trigger_id = 0
    targets = dep.get("targets")
    if isinstance(targets, list):
        for t in targets:
            if (
                isinstance(t, list)
                and len(t) >= 1
                and isinstance(t[0], int)
                and t[0] > 0
            ):
                trigger_id = int(t[0])
                break

    input_ids = dep.get("inputs")
    if not isinstance(input_ids, list):
        raise InferenceError("Invalid Gradio /config: dependency inputs must be a list")

    comps = cfg.get("components")
    if not isinstance(comps, list):
        raise InferenceError("Invalid Gradio /config: components must be a list")

    comp_by_id: dict[int, dict[str, Any]] = {}
    for c in comps:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if isinstance(cid, int):
            comp_by_id[cid] = c

    inputs: list[dict[str, Any]] = []
    for cid_any in input_ids:
        if not isinstance(cid_any, int):
            inputs.append({"id": None, "type": "", "props": {}})
            continue
        c = comp_by_id.get(cid_any) or {}
        inputs.append(
            {
                "id": cid_any,
                "type": str(c.get("type") or ""),
                "props": dict(c.get("props") or {}),
            }
        )

    output_mode = "text"
    outputs = dep.get("outputs")
    if isinstance(outputs, list) and outputs:
        # Heuristic: if first output is a JSON component, it might contain an OpenAI-like blob.
        out0_id = outputs[0] if isinstance(outputs[0], int) else None
        out0 = comp_by_id.get(out0_id) if isinstance(out0_id, int) else None
        if isinstance(out0, dict) and str(out0.get("type") or "") == "json":
            output_mode = "openai_like"

    endpoint = _GradioEndpoint(
        api_prefix=api_prefix,
        fn_index=dep_index,
        trigger_id=trigger_id,
        inputs=inputs,
        output_mode=output_mode,
    )
    _ENDPOINT_CACHE[key] = endpoint
    return endpoint


def _build_input_data(
    *,
    endpoint: _GradioEndpoint,
    system: str,
    user: str,
    max_tokens: int,
    files: list[dict[str, Any]] | None = None,
) -> list[Any]:
    out: list[Any] = []
    system = str(system or "")
    user = str(user or "")
    files = list(files or [])
    user_set = False
    system_set = False

    prompt_hints = (
        "prompt",
        "query",
        "question",
        "message",
        "input",
        "symptom",
        "complaint",
        "case",
        "history",
    )
    prompt_textboxes = 0
    for inp in endpoint.inputs:
        ctype = str(inp.get("type") or "").strip().lower()
        if ctype != "textbox":
            continue
        props = inp.get("props") if isinstance(inp.get("props"), dict) else {}
        label = str(props.get("label") or "").strip().lower()
        if "system" in label:
            continue
        prompt_textboxes += 1
    treat_single_textbox_as_prompt = prompt_textboxes == 1

    for inp in endpoint.inputs:
        ctype = str(inp.get("type") or "").strip().lower()
        props = inp.get("props") if isinstance(inp.get("props"), dict) else {}
        label = str(props.get("label") or "").strip().lower()

        if ctype == "multimodaltextbox":
            out.append({"text": user, "files": files})
            user_set = True
            continue

        if ctype == "textbox" and "system" in label:
            out.append(system)
            system_set = True
            continue

        if ctype == "textbox" and not user_set and (
            treat_single_textbox_as_prompt or not label or any(h in label for h in prompt_hints)
        ):
            out.append(user)
            user_set = True
            continue

        if ctype == "slider" and "token" in label:
            out.append(_clamp_slider_value(props, max_tokens))
            continue

        if ctype in {"state", "chatbot"}:
            out.append([])
            continue

        if ctype == "slider":
            default = props.get("value")
            out.append(default if isinstance(default, (int, float)) else None)
            continue

        if ctype in {"image", "file"}:
            out.append(files[0] if files else (props.get("value") if "value" in props else None))
            continue

        # Safe fallback: try the component default; otherwise pass null.
        out.append(props.get("value") if "value" in props else None)

    # If we didn't find a dedicated system prompt component, fold it into user.
    if system and not system_set:
        combined = f"{system}\n\n{user}".strip()
        if out and isinstance(out[0], dict) and "text" in out[0]:
            out[0] = {"text": combined, "files": files}
        else:
            for i, item in enumerate(out):
                if isinstance(item, str):
                    if not item.strip() or item.strip() == user.strip():
                        out[i] = combined
                        break

    return out


def _clamp_slider_value(props: dict[str, Any], desired: int) -> int:
    try:
        minimum = int(props.get("minimum") or 1)
        maximum = int(props.get("maximum") or max(desired, 1))
        step = int(props.get("step") or 1)
    except (TypeError, ValueError):
        minimum, maximum, step = 1, max(desired, 1), 1

    value = max(minimum, min(int(desired), maximum))
    if step > 1:
        value = minimum + ((value - minimum) // step) * step
        value = max(minimum, min(value, maximum))
    return int(value)
